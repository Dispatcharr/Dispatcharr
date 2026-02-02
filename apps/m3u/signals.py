# apps/m3u/signals.py
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django_celery_beat.models import PeriodicTask, IntervalSchedule

import json
import logging

from core import events
from core.signal_helpers import _get_instance_context, _set_context, _clear_context
from .models import M3UAccount
from .tasks import refresh_single_m3u_account, refresh_m3u_groups, delete_m3u_refresh_task_by_id

logger = logging.getLogger(__name__)


# ─────────────────────────────
# Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=M3UAccount)
def emit_source_created_event(sender, instance, created, **kwargs):
    """Emit m3u.source_created when a new M3U account is created."""
    if created:
        events.emit("m3u.source_created", instance)


@receiver(post_delete, sender=M3UAccount)
def emit_source_deleted_event(sender, instance, **kwargs):
    """Emit m3u.source_deleted when an M3U account is deleted."""
    events.emit("m3u.source_deleted", instance)


@receiver(pre_save, sender=M3UAccount)
def emit_enabled_disabled_events(sender, instance, **kwargs):
    """Emit m3u.source_enabled or m3u.source_disabled when is_active changes."""
    if not instance.pk:
        return  # New instance, will emit created event instead

    try:
        old = M3UAccount.objects.get(pk=instance.pk)
        if old.is_active != instance.is_active:
            _set_context('M3UAccount', instance.pk, {
                'emit_enabled_event': instance.is_active
            })
    except M3UAccount.DoesNotExist:
        pass


@receiver(post_save, sender=M3UAccount)
def emit_enabled_disabled_events_post(sender, instance, created, **kwargs):
    """Emit the enabled/disabled event after save completes."""
    if created:
        return  # Handled by source_created event

    ctx = _get_instance_context('M3UAccount', instance.pk)
    if 'emit_enabled_event' in ctx:
        if ctx['emit_enabled_event']:
            events.emit("m3u.source_enabled", instance)
        else:
            events.emit("m3u.source_disabled", instance)
        _clear_context('M3UAccount', instance.pk)


# ─────────────────────────────
# Existing Signals
# ─────────────────────────────
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
def create_or_update_refresh_task(sender, instance, **kwargs):
    """
    Create or update a Celery Beat periodic task when an M3UAccount is created/updated.
    """
    task_name = f"m3u_account-refresh-{instance.id}"

    interval, _ = IntervalSchedule.objects.get_or_create(
        every=int(instance.refresh_interval),
        period=IntervalSchedule.HOURS
    )

    # Task should be enabled only if refresh_interval != 0 AND account is active
    should_be_enabled = (instance.refresh_interval != 0) and instance.is_active

    # First check if the task already exists to avoid validation errors
    try:
        task = PeriodicTask.objects.get(name=task_name)
        # Task exists, just update it
        updated_fields = []

        if task.enabled != should_be_enabled:
            task.enabled = should_be_enabled
            updated_fields.append("enabled")

        if task.interval != interval:
            task.interval = interval
            updated_fields.append("interval")

        if updated_fields:
            task.save(update_fields=updated_fields)

        # Ensure instance has the task
        if instance.refresh_task_id != task.id:
            M3UAccount.objects.filter(id=instance.id).update(refresh_task=task)

    except PeriodicTask.DoesNotExist:
        # Create new task if it doesn't exist
        refresh_task = PeriodicTask.objects.create(
            name=task_name,
            interval=interval,
            task="apps.m3u.tasks.refresh_single_m3u_account",
            kwargs=json.dumps({"account_id": instance.id}),
            enabled=should_be_enabled,
        )
        M3UAccount.objects.filter(id=instance.id).update(refresh_task=refresh_task)

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
