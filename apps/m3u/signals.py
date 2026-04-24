# apps/m3u/signals.py
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import M3UAccount, M3UAccountProfile
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
    if created and instance.account_type != M3UAccount.Types.XC:
        refresh_m3u_groups.delay(instance.id)

@receiver(post_save, sender=M3UAccount)
def create_or_update_refresh_task(sender, instance, created, update_fields=None, **kwargs):
    """
    Create or update a Celery Beat periodic task when an M3UAccount is created/updated.
    Supports both interval-based and cron-based scheduling via the shared utility.
    """
    # Skip rescheduling when only non-schedule fields were saved (e.g. status/last_message
    # updates from the refresh task itself). We only need to reschedule when schedule-relevant
    # fields change or when _cron_expression was explicitly set by the serializer.
    SCHEDULE_FIELDS = {'refresh_interval', 'is_active', 'refresh_task'}
    if (
        not created
        and update_fields is not None
        and not (set(update_fields) & SCHEDULE_FIELDS)
        and not hasattr(instance, '_cron_expression')
    ):
        return

    task_name = f"m3u_account-refresh-{instance.id}"
    should_be_enabled = instance.is_active

    # Read cron_expression from transient attribute set by the serializer.
    # If not set (e.g. save came from a task updating status/last_message),
    # preserve the existing crontab so we don't accidentally revert to interval.
    if hasattr(instance, "_cron_expression"):
        cron_expr = instance._cron_expression
    else:
        cron_expr = ""
        try:
            existing_task = instance.refresh_task
            if existing_task and existing_task.crontab:
                ct = existing_task.crontab
                cron_expr = f"{ct.minute} {ct.hour} {ct.day_of_month} {ct.month_of_year} {ct.day_of_week}"
        except Exception:
            pass

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

@receiver(post_save, sender=M3UAccountProfile)
def update_profile_expiration_notification(sender, instance, created, update_fields=None, **kwargs):
    """
    When a profile's exp_date is set or changed, immediately update its expiration notification
    so the frontend reflects the new state without waiting for the daily celery task.
    """
    # Only act when exp_date was involved in the save
    if not created and update_fields is not None and "exp_date" not in update_fields:
        return

    try:
        if not instance.exp_date:
            # exp_date was cleared — remove any existing notifications immediately
            from core.models import SystemNotification
            from core.utils import send_notification_dismissed

            keys = [f"xc-exp-warning-{instance.id}", f"xc-exp-expired-{instance.id}"]
            deleted_keys = list(
                SystemNotification.objects.filter(notification_key__in=keys)
                .values_list("notification_key", flat=True)
            )
            SystemNotification.objects.filter(notification_key__in=deleted_keys).delete()
            for key in deleted_keys:
                send_notification_dismissed(key)
            return

        from apps.m3u.tasks import evaluate_profile_expiration_notification
        evaluate_profile_expiration_notification(instance)
    except Exception as e:
        logger.error(f"Error updating expiration notification for profile {instance.id}: {str(e)}")


@receiver(post_delete, sender=M3UAccountProfile)
def cleanup_profile_notifications(sender, instance, **kwargs):
    """
    Delete expiration notifications for a profile when it is deleted.
    Handles both direct deletion and cascade deletion from M3UAccount.
    """
    try:
        from core.models import SystemNotification
        from core.utils import send_notification_dismissed

        keys = [f"xc-exp-warning-{instance.id}", f"xc-exp-expired-{instance.id}"]
        deleted_keys = list(
            SystemNotification.objects.filter(notification_key__in=keys)
            .values_list("notification_key", flat=True)
        )
        if deleted_keys:
            SystemNotification.objects.filter(notification_key__in=deleted_keys).delete()
            for key in deleted_keys:
                send_notification_dismissed(key)
            logger.debug(f"Cleaned up {len(deleted_keys)} notifications for deleted profile {instance.id}")
    except Exception as e:
        logger.error(f"Error cleaning up notifications for profile {instance.id}: {str(e)}")


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
                    # Clean up any expiration notifications for all profiles of this account
                    try:
                        from core.models import SystemNotification
                        from core.utils import send_notification_dismissed

                        profile_ids = list(
                            M3UAccountProfile.objects.filter(m3u_account=instance)
                            .values_list("id", flat=True)
                        )
                        keys = [
                            key
                            for pid in profile_ids
                            for key in [f"xc-exp-warning-{pid}", f"xc-exp-expired-{pid}"]
                        ]
                        if keys:
                            deleted_keys = list(
                                SystemNotification.objects.filter(notification_key__in=keys)
                                .values_list("notification_key", flat=True)
                            )
                            if deleted_keys:
                                SystemNotification.objects.filter(notification_key__in=deleted_keys).delete()
                                for key in deleted_keys:
                                    send_notification_dismissed(key)
                                logger.debug(
                                    f"Cleaned up {len(deleted_keys)} notifications for deactivated M3U account {instance.id}"
                                )
                    except Exception as notify_err:
                        logger.error(f"Error cleaning up notifications on account deactivation: {notify_err}")
        except M3UAccount.DoesNotExist:
            # New record, will use default status
            pass
