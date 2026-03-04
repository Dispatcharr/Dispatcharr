# apps/channels/signals.py

from django.db.models.signals import m2m_changed, pre_save, post_save, post_delete
from django.dispatch import receiver
from django.utils.timezone import now, is_aware, make_aware
from celery.result import AsyncResult
from django_celery_beat.models import ClockedSchedule, PeriodicTask
from .models import Channel, Stream, ChannelProfile, ChannelProfileMembership, Recording
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
            logger.info(f"Triggering EPG program refresh for {instance.epg_data.tvg_id}")
            parse_programs_for_tvg_id.delay(instance.epg_data.id)
    # For new channels with EPG data, also refresh
    elif created and instance.epg_data:
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
