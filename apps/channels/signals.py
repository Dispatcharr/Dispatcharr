# apps/channels/signals.py

from django.db.models.signals import m2m_changed, pre_save, post_save, post_delete
from django.dispatch import receiver
from django.utils.timezone import now
from celery.result import AsyncResult
from .models import Channel, Stream, ChannelProfile, ChannelProfileMembership, Recording
from apps.m3u.models import M3UAccount
from apps.epg.tasks import parse_programs_for_tvg_id
import logging, requests, time
from .tasks import run_recording, prefetch_recording_artwork
from django.utils.timezone import now, is_aware, make_aware
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
