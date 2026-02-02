# apps/channels/signals.py

from django.db.models.signals import m2m_changed, pre_save, post_save, post_delete
from django.dispatch import receiver
from django.utils.timezone import now
from celery.result import AsyncResult
from .models import Channel, Stream, ChannelGroup, ChannelProfile, ChannelProfileMembership, Recording, RecurringRecordingRule
from apps.m3u.models import M3UAccount
from apps.epg.tasks import parse_programs_for_tvg_id
import logging, requests, time
from .tasks import run_recording, prefetch_recording_artwork
from django.utils.timezone import now, is_aware, make_aware
from datetime import timedelta
from core import events

logger = logging.getLogger(__name__)


# ─────────────────────────────
# Channel Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=Channel)
def emit_channel_created_event(sender, instance, created, **kwargs):
    """Emit channel.created when a new channel is created."""
    if created:
        events.emit("channel.created", instance)


@receiver(post_delete, sender=Channel)
def emit_channel_deleted_event(sender, instance, **kwargs):
    """Emit channel.deleted when a channel is deleted."""
    events.emit("channel.deleted", instance)


@receiver(pre_save, sender=Channel)
def track_channel_changes(sender, instance, **kwargs):
    """Track which fields changed for channel.updated event."""
    if not instance.pk:
        return  # New instance, will emit created event instead

    try:
        old = Channel.objects.get(pk=instance.pk)
        changed_fields = []
        for field in ['name', 'channel_number', 'channel_group_id', 'epg_data_id', 'logo_id', 'stream_profile_id']:
            old_val = getattr(old, field)
            new_val = getattr(instance, field)
            if old_val != new_val:
                changed_fields.append(field.replace('_id', ''))
        if changed_fields:
            instance._changed_fields = changed_fields
    except Channel.DoesNotExist:
        pass


@receiver(post_save, sender=Channel)
def emit_channel_updated_event(sender, instance, created, **kwargs):
    """Emit channel.updated when a channel is modified."""
    if created:
        return  # Handled by channel.created

    if hasattr(instance, '_changed_fields') and instance._changed_fields:
        events.emit("channel.updated", instance, changed_fields=instance._changed_fields)
        del instance._changed_fields


@receiver(m2m_changed, sender=Channel.streams.through)
def emit_channel_stream_events(sender, instance, action, reverse, model, pk_set, **kwargs):
    """Emit channel.stream_added/removed when streams are added/removed from a channel."""
    if pk_set is None:
        return

    stream_ids = list(pk_set)
    if action == "post_add":
        events.emit("channel.stream_added", instance, stream_ids=stream_ids)
    elif action == "post_remove":
        events.emit("channel.stream_removed", instance, stream_ids=stream_ids)


# ─────────────────────────────
# Stream Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=Stream)
def emit_stream_created_event(sender, instance, created, **kwargs):
    """Emit stream.created when a new stream is created."""
    if created:
        events.emit("stream.created", instance)


@receiver(post_delete, sender=Stream)
def emit_stream_deleted_event(sender, instance, **kwargs):
    """Emit stream.deleted when a stream is deleted."""
    events.emit("stream.deleted", instance)


@receiver(pre_save, sender=Stream)
def track_stream_changes(sender, instance, **kwargs):
    """Track which fields changed for stream.updated event."""
    if not instance.pk:
        return  # New instance, will emit created event instead

    try:
        old = Stream.objects.get(pk=instance.pk)
        changed_fields = []
        for field in ['name', 'url', 'tvg_id', 'channel_group_id', 'stream_profile_id', 'is_custom']:
            old_val = getattr(old, field)
            new_val = getattr(instance, field)
            if old_val != new_val:
                changed_fields.append(field.replace('_id', ''))
        if changed_fields:
            instance._changed_fields = changed_fields
    except Stream.DoesNotExist:
        pass


@receiver(post_save, sender=Stream)
def emit_stream_updated_event(sender, instance, created, **kwargs):
    """Emit stream.updated when a stream is modified."""
    if created:
        return  # Handled by stream.created

    if hasattr(instance, '_changed_fields') and instance._changed_fields:
        events.emit("stream.updated", instance, changed_fields=instance._changed_fields)
        del instance._changed_fields


# ─────────────────────────────
# ChannelGroup Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=ChannelGroup)
def emit_channel_group_created_event(sender, instance, created, **kwargs):
    """Emit channel_group.created when a new channel group is created."""
    if created:
        events.emit("channel_group.created", instance)


@receiver(post_delete, sender=ChannelGroup)
def emit_channel_group_deleted_event(sender, instance, **kwargs):
    """Emit channel_group.deleted when a channel group is deleted."""
    events.emit("channel_group.deleted", instance)


@receiver(pre_save, sender=ChannelGroup)
def track_channel_group_changes(sender, instance, **kwargs):
    """Track which fields changed for channel_group.updated event."""
    if not instance.pk:
        return  # New instance, will emit created event instead

    try:
        old = ChannelGroup.objects.get(pk=instance.pk)
        if old.name != instance.name:
            instance._name_changed = True
    except ChannelGroup.DoesNotExist:
        pass


@receiver(post_save, sender=ChannelGroup)
def emit_channel_group_updated_event(sender, instance, created, **kwargs):
    """Emit channel_group.updated when a channel group is modified."""
    if created:
        return  # Handled by channel_group.created

    if hasattr(instance, '_name_changed') and instance._name_changed:
        events.emit("channel_group.updated", instance)
        del instance._name_changed


# ─────────────────────────────
# ChannelProfile Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=ChannelProfile)
def emit_channel_profile_created_event(sender, instance, created, **kwargs):
    """Emit channel_profile.created when a new channel profile is created."""
    if created:
        events.emit("channel_profile.created", instance)


@receiver(post_delete, sender=ChannelProfile)
def emit_channel_profile_deleted_event(sender, instance, **kwargs):
    """Emit channel_profile.deleted when a channel profile is deleted."""
    events.emit("channel_profile.deleted", instance)


@receiver(pre_save, sender=ChannelProfile)
def track_channel_profile_changes(sender, instance, **kwargs):
    """Track which fields changed for channel_profile.updated event."""
    if not instance.pk:
        return  # New instance, will emit created event instead

    try:
        old = ChannelProfile.objects.get(pk=instance.pk)
        if old.name != instance.name:
            instance._name_changed = True
    except ChannelProfile.DoesNotExist:
        pass


@receiver(post_save, sender=ChannelProfile)
def emit_channel_profile_updated_event(sender, instance, created, **kwargs):
    """Emit channel_profile.updated when a channel profile is modified."""
    if created:
        return  # Handled by channel_profile.created

    if hasattr(instance, '_name_changed') and instance._name_changed:
        events.emit("channel_profile.updated", instance)
        del instance._name_changed


# ─────────────────────────────
# RecurringRecordingRule Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=RecurringRecordingRule)
def emit_recording_rule_created_event(sender, instance, created, **kwargs):
    """Emit recording_rule.created when a new recording rule is created."""
    if created:
        events.emit("recording_rule.created", instance)


@receiver(post_delete, sender=RecurringRecordingRule)
def emit_recording_rule_deleted_event(sender, instance, **kwargs):
    """Emit recording_rule.deleted when a recording rule is deleted."""
    events.emit("recording_rule.deleted", instance)


@receiver(pre_save, sender=RecurringRecordingRule)
def track_recording_rule_changes(sender, instance, **kwargs):
    """Track which fields changed for recording_rule.updated event."""
    if not instance.pk:
        return  # New instance, will emit created event instead

    try:
        old = RecurringRecordingRule.objects.get(pk=instance.pk)
        changed_fields = []
        for field in ['channel_id', 'days_of_week', 'start_time', 'end_time', 'enabled', 'name', 'start_date', 'end_date']:
            old_val = getattr(old, field)
            new_val = getattr(instance, field)
            if old_val != new_val:
                changed_fields.append(field.replace('_id', ''))
        if changed_fields:
            instance._changed_fields = changed_fields
    except RecurringRecordingRule.DoesNotExist:
        pass


@receiver(post_save, sender=RecurringRecordingRule)
def emit_recording_rule_updated_event(sender, instance, created, **kwargs):
    """Emit recording_rule.updated when a recording rule is modified."""
    if created:
        return  # Handled by recording_rule.created

    if hasattr(instance, '_changed_fields') and instance._changed_fields:
        events.emit("recording_rule.updated", instance, changed_fields=instance._changed_fields)
        del instance._changed_fields


# ─────────────────────────────
# Existing Channel Signals
# ─────────────────────────────
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

def schedule_recording_task(instance):
    eta = instance.start_time
    # Pass recording_id first so task can persist metadata to the correct row
    task = run_recording.apply_async(
        args=[instance.id, instance.channel_id, str(instance.start_time), str(instance.end_time)],
        eta=eta
    )
    return task.id

def revoke_task(task_id):
    if task_id:
        AsyncResult(task_id).revoke()

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
            revoke_task(old.task_id)
            instance.task_id = None
            events.emit("recording.changed", instance,
                 previous_start_time=str(old.start_time),
                 previous_end_time=str(old.end_time))
    except Recording.DoesNotExist:
        pass

@receiver(post_save, sender=Recording)
def schedule_task_on_save(sender, instance, created, **kwargs):
    try:
        if not instance.task_id:
            start_time = instance.start_time

            # Make both datetimes aware (in UTC)
            if not is_aware(start_time):
                print("Start time was not aware, making aware")
                start_time = make_aware(start_time)

            current_time = now()

            # Debug log
            print(f"Start time: {start_time}, Now: {current_time}")

            # Optionally allow slight fudge factor (1 second) to ensure scheduling happens
            if start_time > current_time - timedelta(seconds=1):
                print("Scheduling recording task!")
                task_id = schedule_recording_task(instance)
                instance.task_id = task_id
                instance.save(update_fields=['task_id'])
                events.emit("recording.scheduled", instance)
            else:
                print("Start time is in the past. Not scheduling.")
        # Kick off poster/artwork prefetch to enrich Upcoming cards
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
    cp = instance.custom_properties or {}
    status = cp.get("status")
    # If recording was completed or interrupted, it's a deletion of existing content
    # Otherwise it's a cancellation of a scheduled/in-progress recording
    if status in ("completed", "interrupted"):
        events.emit("recording.deleted", instance)
    else:
        events.emit("recording.cancelled", instance)
