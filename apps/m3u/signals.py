# apps/m3u/signals.py
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import M3UAccount
from .tasks import refresh_single_m3u_account, refresh_m3u_groups, delete_m3u_refresh_task_by_id
from core.scheduling import create_or_update_periodic_task, delete_periodic_task
import json
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=M3UAccount)
def refresh_account_on_save(sender, instance, created, **kwargs):
    """
    When an M3UAccount is saved (created or updated),
    call a Celery task that fetches & parses that single account
    if it is active or newly created.
    """
    if not created:
        return

    managed_source = (instance.custom_properties or {}).get("managed_source")
    if managed_source in {"media_server", "media-library"}:
        return

    if instance.account_type != M3UAccount.Types.XC:
        refresh_m3u_groups.delay(instance.id)

@receiver(post_save, sender=M3UAccount)
def create_or_update_refresh_task(sender, instance, **kwargs):
    """
    Create or update a Celery Beat periodic task when an M3UAccount is created/updated.
    Supports both interval-based and cron-based scheduling via the shared utility.
    """
    task_name = f"m3u_account-refresh-{instance.id}"
    should_be_enabled = instance.is_active

    # Read cron_expression from transient attribute set by the serializer
    cron_expr = getattr(instance, "_cron_expression", "")

    task = create_or_update_periodic_task(
        task_name=task_name,
        celery_task_path="apps.m3u.tasks.refresh_single_m3u_account",
        kwargs={"account_id": instance.id},
        interval_hours=int(instance.refresh_interval),
        cron_expression=cron_expr,
        enabled=should_be_enabled,
    )

    # Ensure instance has the task linked
    if instance.refresh_task_id != task.id:
        M3UAccount.objects.filter(id=instance.id).update(refresh_task=task)

@receiver(post_delete, sender=M3UAccount)
def delete_refresh_task(sender, instance, **kwargs):
    """
    Delete the associated Celery Beat periodic task when a Channel is deleted.
    """
    try:
        # First try the foreign key relationship to find the task ID
        task = None
        if instance.refresh_task:
            logger.info(f"Found task via foreign key: {instance.refresh_task.id} for M3UAccount {instance.id}")
            task = instance.refresh_task

            # Use the helper function to delete the task
            if task:
                delete_m3u_refresh_task_by_id(instance.id)
        else:
            # Otherwise use the helper function
            delete_m3u_refresh_task_by_id(instance.id)
    except Exception as e:
        logger.error(f"Error in delete_refresh_task signal handler: {str(e)}", exc_info=True)

@receiver(pre_save, sender=M3UAccount)
def update_status_on_active_change(sender, instance, **kwargs):
    """
    When an M3UAccount's is_active field changes, update the status accordingly.
    """
    if instance.pk:  # Only for existing records, not new ones
        try:
            # Get the current record from the database
            old_instance = M3UAccount.objects.get(pk=instance.pk)

            # If is_active changed, update the status
            if old_instance.is_active != instance.is_active:
                if instance.is_active:
                    # When activating, set status to idle
                    instance.status = M3UAccount.Status.IDLE
                else:
                    # When deactivating, set status to disabled
                    instance.status = M3UAccount.Status.DISABLED
        except M3UAccount.DoesNotExist:
            # New record, will use default status
            pass
