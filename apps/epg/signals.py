from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import EPGSource, EPGData
from .tasks import refresh_epg_data, delete_epg_refresh_task_by_id
from django_celery_beat.models import PeriodicTask, IntervalSchedule
from core.utils import is_protected_path, send_websocket_update
import json
import logging
import os

logger = logging.getLogger(__name__)

@receiver(post_save, sender=EPGSource)
def trigger_refresh_on_new_epg_source(sender, instance, created, **kwargs):
    # Trigger refresh only if the source is newly created, active, and not a dummy EPG
    if created and instance.is_active and instance.source_type != 'dummy':
        refresh_epg_data.delay(instance.id)

@receiver(post_save, sender=EPGSource)
def create_dummy_epg_data(sender, instance, created, **kwargs):
    """
    Automatically create EPGData for dummy EPG sources when they are created.
    This allows channels to be assigned to dummy EPGs immediately without
    requiring a refresh first.
    """
    if instance.source_type == 'dummy':
        # Ensure dummy EPGs always have idle status and no status message
        if instance.status != EPGSource.STATUS_IDLE or instance.last_message:
            instance.status = EPGSource.STATUS_IDLE
            instance.last_message = None
            instance.save(update_fields=['status', 'last_message'])

        # Create a URL-friendly tvg_id from the dummy EPG name
        # Replace spaces and special characters with underscores
        friendly_tvg_id = instance.name.replace(' ', '_').replace('-', '_')
        # Remove any characters that aren't alphanumeric or underscores
        friendly_tvg_id = ''.join(c for c in friendly_tvg_id if c.isalnum() or c == '_')
        # Convert to lowercase for consistency
        friendly_tvg_id = friendly_tvg_id.lower()
        # Prefix with 'dummy_' to make it clear this is a dummy EPG
        friendly_tvg_id = f"dummy_{friendly_tvg_id}"

        # Create or update the EPGData record
        epg_data, data_created = EPGData.objects.get_or_create(
            tvg_id=friendly_tvg_id,
            epg_source=instance,
            defaults={
                'name': instance.name,
                'icon_url': None
            }
        )

        # Update name if it changed and record already existed
        if not data_created and epg_data.name != instance.name:
            epg_data.name = instance.name
            epg_data.save(update_fields=['name'])

        if data_created:
            logger.info(f"Auto-created EPGData for dummy EPG source: {instance.name} (ID: {instance.id})")

            # Send websocket update to notify frontend that EPG data has been created
            # This allows the channel form to immediately show the new dummy EPG without refreshing
            send_websocket_update('updates', 'update', {
                'type': 'epg_data_created',
                'source_id': instance.id,
                'source_name': instance.name,
                'epg_data_id': epg_data.id
            })
        else:
            logger.debug(f"EPGData already exists for dummy EPG source: {instance.name} (ID: {instance.id})")

@receiver(post_save, sender=EPGSource)
def create_or_update_refresh_task(sender, instance, **kwargs):
    """
    Create or update a Celery Beat periodic task when an EPGSource is created/updated.
    Skip creating tasks for dummy EPG sources as they don't need refreshing.
    """
    # Skip task creation for dummy EPGs
    if instance.source_type == 'dummy':
        # If there's an existing task, disable it
        if instance.refresh_task:
            instance.refresh_task.enabled = False
            instance.refresh_task.save(update_fields=['enabled'])
        return

    task_name = f"epg_source-refresh-{instance.id}"
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=int(instance.refresh_interval),
        period=IntervalSchedule.HOURS
    )

    task, created = PeriodicTask.objects.get_or_create(name=task_name, defaults={
        "interval": interval,
        "task": "apps.epg.tasks.refresh_epg_data",
        "kwargs": json.dumps({"source_id": instance.id}),
        "enabled": instance.refresh_interval != 0 and instance.is_active,
    })

    update_fields = []
    if created:
        task.interval = interval

    if task.interval != interval:
        task.interval = interval
        update_fields.append("interval")

    # Check both refresh_interval and is_active to determine if task should be enabled
    should_be_enabled = instance.refresh_interval != 0 and instance.is_active
    if task.enabled != should_be_enabled:
        task.enabled = should_be_enabled
        update_fields.append("enabled")

    if update_fields:
        task.save(update_fields=update_fields)

    if instance.refresh_task != task:
        instance.refresh_task = task
        instance.save(update_fields=["refresh_task"])  # Fixed field name

@receiver(post_delete, sender=EPGSource)
def delete_refresh_task(sender, instance, **kwargs):
    """
    Delete the associated Celery Beat periodic task when an EPGSource is deleted.
    """
    try:
        # First try the foreign key relationship to find the task ID
        task = None
        if instance.refresh_task:
            logger.info(f"Found task via foreign key: {instance.refresh_task.id} for EPGSource {instance.id}")
            task = instance.refresh_task

            # Store task ID before deletion if we need to bypass the helper function
            if task:
                delete_epg_refresh_task_by_id(instance.id)
        else:
            # Otherwise use the helper function
            delete_epg_refresh_task_by_id(instance.id)
    except Exception as e:
        logger.error(f"Error in delete_refresh_task signal handler: {str(e)}", exc_info=True)

@receiver(pre_save, sender=EPGSource)
def update_status_on_active_change(sender, instance, **kwargs):
    """
    When an EPGSource's is_active field changes, update the status accordingly.
    For dummy EPGs, always ensure status is idle and no status message.
    """
    # Dummy EPGs should always be idle with no status message
    if instance.source_type == 'dummy':
        instance.status = EPGSource.STATUS_IDLE
        instance.last_message = None
        return

    if instance.pk:  # Only for existing records, not new ones
        try:
            # Get the current record from the database
            old_instance = EPGSource.objects.get(pk=instance.pk)

            # If is_active changed, update the status
            if old_instance.is_active != instance.is_active:
                if instance.is_active:
                    # When activating, set status to idle
                    instance.status = 'idle'
                else:
                    # When deactivating, set status to disabled
                    instance.status = 'disabled'
        except EPGSource.DoesNotExist:
            # New record, will use default status
            pass

@receiver(post_delete, sender=EPGSource)
def delete_cached_files(sender, instance, **kwargs):
    """
    Delete cached files associated with an EPGSource when it's deleted.
    Only deletes files that aren't in protected directories.
    """
    # Check and delete the main file path if not protected
    if instance.file_path and os.path.exists(instance.file_path):
        if is_protected_path(instance.file_path):
            logger.info(f"Skipping deletion of protected file: {instance.file_path}")
        else:
            try:
                os.remove(instance.file_path)
                logger.info(f"Deleted cached file: {instance.file_path}")
            except OSError as e:
                logger.error(f"Error deleting cached file {instance.file_path}: {e}")

    # Check and delete the extracted file path if it exists, is different from main path, and not protected
    if instance.extracted_file_path and os.path.exists(instance.extracted_file_path) and instance.extracted_file_path != instance.file_path:
        if is_protected_path(instance.extracted_file_path):
            logger.info(f"Skipping deletion of protected extracted file: {instance.extracted_file_path}")
        else:
            try:
                os.remove(instance.extracted_file_path)
                logger.info(f"Deleted extracted file: {instance.extracted_file_path}")
            except OSError as e:
                logger.error(f"Error deleting extracted file {instance.extracted_file_path}: {e}")
