# apps/channels/signals.py

from django.db.models.signals import m2m_changed, pre_save, post_save, post_delete, pre_delete
from django.dispatch import receiver
from django.utils.timezone import now, is_aware, make_aware
from celery.result import AsyncResult
from django_celery_beat.models import ClockedSchedule, PeriodicTask
from .models import Channel, Stream, ChannelStream, ChannelProfile, ChannelProfileMembership, Recording
from apps.m3u.models import M3UAccount
from apps.epg.tasks import parse_programs_for_tvg_id
import json
import logging
from .tasks import run_recording, prefetch_recording_artwork
from datetime import timedelta

logger = logging.getLogger(__name__)

@receiver(m2m_changed, sender=Channel.streams.through)
def update_channel_tvg_id_and_logo(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    Whenever streams are added to a channel:
      1) If the channel doesn't have a tvg_id, fill it from the first newly-added stream that has one.
    """
    # We only care about post_add, i.e. once the new streams are fully associated
    if action == "post_add":
        # --- 1) Populate channel.tvg_id if empty ---
        if not instance.tvg_id:
            # Look for newly added streams that have a nonempty tvg_id
            streams_with_tvg = model.objects.filter(pk__in=pk_set).exclude(tvg_id__exact='')
            if streams_with_tvg.exists():
                instance.tvg_id = streams_with_tvg.first().tvg_id
                instance.save(update_fields=['tvg_id'])

@receiver(pre_save, sender=Stream)
def set_default_m3u_account(sender, instance, **kwargs):
    """
    This function will be triggered before saving a Stream instance.
    It sets the default m3u_account if not provided.
    """
    if not instance.m3u_account:
        instance.is_custom = True
        default_account = M3UAccount.get_custom_account()

        if default_account:
            instance.m3u_account = default_account
        else:
            raise ValueError("No default M3UAccount found.")

@receiver(post_save, sender=Stream)
def generate_custom_stream_hash(sender, instance, created, **kwargs):
    """
    Generate a stable stream_hash for custom streams after creation.
    Uses the stream's ID to ensure the hash never changes even if name/url is edited.
    """
    if instance.is_custom and not instance.stream_hash and created:
        import hashlib
        # Use stream ID for a stable, unique hash that never changes
        unique_string = f"custom_stream_{instance.id}"
        instance.stream_hash = hashlib.sha256(unique_string.encode()).hexdigest()
        # Use update to avoid triggering signals again
        Stream.objects.filter(id=instance.id).update(stream_hash=instance.stream_hash)

@receiver(pre_delete, sender=Channel)
def stop_proxy_session_before_channel_delete(sender, instance, **kwargs):
    """
    When a Channel is deleted, stop any active TS proxy session for it first.

    Without this, the proxy's Redis state (live:channel:{uuid}:*) survives
    the Channel row and the connected clients' "Stop" button hits
    `ChannelService.stop_channel(uuid)`, which calls `Channel.objects.get(uuid=...)`
    and crashes with DoesNotExist (reported as 'Channel not found' in the UI).
    Users then cannot close the stream; source-side connection limits stay
    consumed. Covers manual deletes, bulk deletes, and sync-driven deletes
    via the same signal path.
    """
    try:
        from apps.proxy.live_proxy.services.channel_service import ChannelService

        channel_uuid = str(instance.uuid) if instance.uuid else None
        if not channel_uuid:
            return
        # Best-effort: if the channel has no active session the service
        # returns a benign 'Channel not found' result, which is ignored.
        ChannelService.stop_channel(channel_uuid)
    except Exception as e:
        # Never block a channel delete on proxy cleanup failure. Log and
        # continue so at least the DB row is removed.
        logger.warning(
            "Failed to stop proxy session before deleting channel %s: %s",
            getattr(instance, "id", "<unknown>"),
            e,
        )


@receiver(post_save, sender=Channel)
def assign_compact_number_on_unhide(sender, instance, created, **kwargs):
    """When a channel transitions from hidden to visible under compact
    numbering, immediately assign the next available number from its
    group's range. Without this, an unhide would leave the channel at
    NULL until the next M3U refresh, which is too long a delay for what
    is meant to feel like an instant action.

    Bails out for the common cases where assignment is not appropriate:
    a fresh channel (newly created), a channel that already has a
    number, a hidden channel, a manual channel, or a channel whose group
    is not in compact mode. The assignment helper does the same checks
    defensively, but bailing here keeps the signal out of the helper
    code path on every channel save.
    """
    if created:
        return
    # Skip the signal when update_fields proves hidden_from_output was not
    # touched. Sync sets update_fields on every save, so this keeps the
    # signal off the sync hot path.
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "hidden_from_output" not in update_fields:
        return
    if instance.hidden_from_output:
        return
    if instance.channel_number is not None:
        return
    if not instance.auto_created or not instance.auto_created_by_id:
        return
    try:
        from .compact_numbering import assign_compact_numbers_for_channels

        assign_compact_numbers_for_channels([instance.id])
        # The helper writes via queryset .update() which skips
        # in-memory state. Reload so a same-request serializer
        # response carries the assigned number, not stale None.
        try:
            instance.refresh_from_db(fields=["channel_number"])
        except Exception:
            # Refresh failure (race with delete) is non-fatal.
            pass
    except Exception as e:
        # Do not propagate. The save succeeded; the assignment is
        # recoverable on next sync or manual repack.
        logger.warning(
            "Compact unhide assignment failed for channel %s: %s",
            instance.id,
            e,
        )


@receiver(post_save, sender=Channel)
def release_compact_number_on_hide(sender, instance, created, **kwargs):
    """When a channel transitions from visible to hidden under compact
    numbering, immediately release its channel_number slot. Without
    this, the slot stays occupied until the next sync's repack pass,
    so the user sees their hidden channels still consuming numbers in
    the table for an indeterminate window. Mirror image of
    `assign_compact_number_on_unhide` above.

    Bails out for the common cases where release is not appropriate:
    a fresh channel (newly created), a non-hidden channel, a channel
    that has no number to release, a manual channel, a channel without
    a known auto_created_by, or a channel whose group is not in
    compact mode.
    """
    if created:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "hidden_from_output" not in update_fields:
        return
    if not instance.hidden_from_output:
        return
    if instance.channel_number is None:
        return
    if not instance.auto_created or not instance.auto_created_by_id:
        return
    try:
        from .compact_numbering import (
            get_group_relation_for_channel,
            is_compact_group,
        )

        relation = get_group_relation_for_channel(instance)
        if not relation or not is_compact_group(relation):
            return
    except Exception:
        return
    # Release the slot. Queryset .update() bypasses the post_save signal
    # chain that this handler is itself running inside.
    Channel.objects.filter(id=instance.id).update(channel_number=None)
    # Refresh in-memory instance so the same-request serializer
    # response surfaces channel_number=None instead of stale value.
    try:
        instance.refresh_from_db(fields=["channel_number"])
    except Exception:
        pass


@receiver(post_save, sender=Channel)
def refresh_epg_programs(sender, instance, created, **kwargs):
    """
    When a channel is saved, check if the EPG data has changed.
    If so, trigger a refresh of the program data for the EPG.
    """
    # Check if this is an update (not a new channel) and the epg_data has changed
    if not created and kwargs.get('update_fields') and 'epg_data' in kwargs['update_fields']:
        logger.info(f"Channel {instance.id} ({instance.name}) EPG data updated, refreshing program data")
        if instance.epg_data:
            if instance.epg_data.epg_source and instance.epg_data.epg_source.source_type == 'dummy':
                return
            logger.info(f"Triggering EPG program refresh for {instance.epg_data.tvg_id}")
            parse_programs_for_tvg_id.delay(instance.epg_data.id)
    # For new channels with EPG data, also refresh
    elif created and instance.epg_data:
        if instance.epg_data.epg_source and instance.epg_data.epg_source.source_type == 'dummy':
            return
        logger.info(f"New channel {instance.id} ({instance.name}) created with EPG data, refreshing program data")
        parse_programs_for_tvg_id.delay(instance.epg_data.id)

@receiver(post_save, sender=ChannelProfile)
def create_profile_memberships(sender, instance, created, **kwargs):
    if created:
        channels = Channel.objects.all()
        ChannelProfileMembership.objects.bulk_create([
            ChannelProfileMembership(channel_profile=instance, channel=channel)
            for channel in channels
        ])

def _dvr_task_name(recording_id):
    """Predictable PeriodicTask name for a DVR recording."""
    return f"dvr-recording-{recording_id}"


def schedule_recording_task(instance, eta=None):
    """Schedule a recording task via ClockedSchedule + one-off PeriodicTask.

    The task is stored in the database and dispatched by Celery Beat at the
    scheduled time with no countdown.  This avoids the Redis visibility_timeout
    redelivery bug that caused duplicate recordings when using apply_async
    with long countdowns.
    """
    if eta is None:
        eta = instance.start_time
    if eta is not None and not is_aware(eta):
        eta = make_aware(eta)
    # Clamp to now so Beat dispatches immediately for past/current start times
    if eta <= now():
        eta = now()

    task_args = [
        instance.id,
        instance.channel_id,
        str(instance.start_time),
        str(instance.end_time),
    ]

    clocked, _ = ClockedSchedule.objects.get_or_create(clocked_time=eta)
    task_name = _dvr_task_name(instance.id)
    PeriodicTask.objects.update_or_create(
        name=task_name,
        defaults={
            "task": "apps.channels.tasks.run_recording",
            "clocked": clocked,
            "args": json.dumps(task_args),
            "one_off": True,
            "enabled": True,
            "interval": None,
            "crontab": None,
            "solar": None,
        },
    )
    return task_name


def revoke_task(task_id):
    """Cancel a pending recording task.

    task_id is normally a PeriodicTask name (e.g. "dvr-recording-42").
    For backwards compatibility with legacy Celery async-result UUIDs,
    falls back to AsyncResult.revoke().
    """
    if not task_id:
        return
    # Primary path: delete the PeriodicTask and clean up its ClockedSchedule
    try:
        pt = PeriodicTask.objects.get(name=task_id)
        old_clocked = pt.clocked
        pt.delete()
        if old_clocked and not PeriodicTask.objects.filter(clocked=old_clocked).exists():
            old_clocked.delete()
        return
    except PeriodicTask.DoesNotExist:
        pass
    # Fallback for legacy Celery task UUIDs
    try:
        AsyncResult(task_id).revoke()
    except Exception:
        pass

@receiver(pre_save, sender=Recording)
def revoke_old_task_on_update(sender, instance, **kwargs):
    if not instance.pk:
        return  # New instance
    try:
        old = Recording.objects.get(pk=instance.pk)
        if old.task_id and (
            old.start_time != instance.start_time or
            old.end_time != instance.end_time or
            old.channel_id != instance.channel_id
        ):
            # Do NOT revoke while the recording is actively streaming.
            # run_recording re-reads end_time from the DB every ~2 s and extends
            # its internal deadline dynamically — revoking here would kill the task.
            old_status = (old.custom_properties or {}).get("status", "")
            if old_status == "recording":
                return
            revoke_task(old.task_id)
            instance.task_id = None
    except Recording.DoesNotExist:
        pass

@receiver(post_save, sender=Recording)
def schedule_task_on_save(sender, instance, created, **kwargs):
    try:
        # Skip processing for internal field-only saves (metadata updates,
        # task_id assignment, end_time extensions) to prevent re-entrant
        # artwork dispatch and redundant recording_updated WS events.
        update_fields = kwargs.get('update_fields')
        if not created and update_fields is not None and set(update_fields) <= {'custom_properties', 'task_id', 'end_time'}:
            return

        if not instance.task_id:
            start_time = instance.start_time
            end_time = instance.end_time

            # Make datetimes aware (in UTC)
            if not is_aware(start_time):
                start_time = make_aware(start_time)
            if end_time and not is_aware(end_time):
                end_time = make_aware(end_time)

            current_time = now()

            if start_time > current_time - timedelta(seconds=1):
                # Future recording — schedule at start_time
                logger.info(f"Recording {instance.id}: scheduling task at {start_time}")
                task_id = schedule_recording_task(instance, eta=start_time)
                instance.task_id = task_id
                instance.save(update_fields=['task_id'])
            elif end_time and end_time > current_time:
                # Currently-playing — start immediately (e.g. series rule for in-progress program)
                logger.info(f"Recording {instance.id}: start_time in past but end_time still future, scheduling immediately")
                task_id = schedule_recording_task(instance, eta=current_time)
                instance.task_id = task_id
                instance.save(update_fields=['task_id'])
            else:
                logger.info(f"Recording {instance.id}: start_time and end_time both in past, not scheduling")
        # Kick off poster/artwork prefetch to enrich Upcoming cards.
        # Skip when the recording is already active or finished — run_recording
        # handles its own poster resolution, and scheduling artwork prefetch
        # while the task is running causes a race that can overwrite status.
        cp = instance.custom_properties or {}
        rec_status = cp.get("status", "")
        if rec_status not in ("recording", "completed", "stopped", "interrupted"):
            try:
                prefetch_recording_artwork.apply_async(args=[instance.id], countdown=1)
            except Exception as e:
                print("Error scheduling artwork prefetch:", e)
    except Exception as e:
        import traceback
        print("Error in post_save signal:", e)
        traceback.print_exc()

@receiver(post_delete, sender=Recording)
def revoke_task_on_delete(sender, instance, **kwargs):
    revoke_task(instance.task_id)


@receiver([post_save, post_delete], sender=ChannelStream)
def update_channel_catchup_fields(sender, instance, **kwargs):
    """Roll up denormalized catch-up fields from streams to the channel.

    Covers the UI/API path (admin adds/removes a stream from a channel).
    The bulk-import path bypasses signals and uses explicit SQL instead —
    see rollup_channel_catchup_fields() in apps/m3u/tasks.py. Same semantics
    as that rollup: is_catchup = any catch-up stream, catchup_days = MAX of
    the catch-up streams' archive depth.
    """
    from django.db.models import Max

    channel = instance.channel
    max_days = (
        channel.streams
        .filter(is_catchup=True)
        .aggregate(max_days=Max("catchup_days"))["max_days"]
    )
    Channel.objects.filter(pk=channel.pk).update(
        is_catchup=max_days is not None,
        catchup_days=max_days or 0,
    )
