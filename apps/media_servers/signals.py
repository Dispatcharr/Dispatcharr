import logging

from celery.signals import task_postrun
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.m3u.models import M3UAccount
from apps.media_servers.models import MediaServerIntegration
from core.scheduling import create_or_update_periodic_task, delete_periodic_task

logger = logging.getLogger(__name__)
VOD_TASKS_TRIGGERING_OUTPUT_SYNC = {
    'apps.vod.tasks.refresh_vod_content',
    'apps.vod.tasks.cleanup_orphaned_vod_content',
}


@receiver(post_save, sender=MediaServerIntegration)
def create_or_update_sync_task(sender, instance, **kwargs):
    task_name = f"media_server-sync-{instance.id}"
    should_be_enabled = bool(instance.enabled and instance.add_to_vod)

    task = create_or_update_periodic_task(
        task_name=task_name,
        celery_task_path="apps.media_servers.tasks.sync_media_server_integration",
        kwargs={"integration_id": instance.id},
        interval_hours=int(instance.sync_interval or 0),
        enabled=should_be_enabled,
    )

    if instance.sync_task_id != task.id:
        MediaServerIntegration.objects.filter(id=instance.id).update(sync_task=task)


@receiver(post_delete, sender=MediaServerIntegration)
def delete_sync_task(sender, instance, **kwargs):
    task_name = f"media_server-sync-{instance.id}"
    deleted = delete_periodic_task(task_name)
    if not deleted:
        logger.debug(
            "No periodic sync task existed for media server integration %s",
            instance.id,
        )


@receiver(post_delete, sender=M3UAccount)
def queue_output_sync_after_provider_account_delete(sender, instance, **kwargs):
    custom_props = (
        instance.custom_properties if isinstance(instance.custom_properties, dict) else {}
    )
    managed_source = str(custom_props.get('managed_source') or '').strip().lower()
    if managed_source in {'media_server', 'media-library'}:
        return

    try:
        from apps.media_servers.tasks import _queue_output_export_sync

        _queue_output_export_sync(reason=f'm3u_account_deleted:{instance.id}')
    except Exception:
        logger.exception(
            "Failed to queue output export sync after provider account delete %s",
            instance.id,
        )


@receiver(task_postrun)
def queue_output_sync_after_vod_refresh(
    sender=None,
    task_id=None,
    task=None,
    args=None,
    kwargs=None,
    retval=None,
    state=None,
    **extra,
):
    task_name = getattr(sender, 'name', '') or getattr(task, 'name', '')
    if task_name not in VOD_TASKS_TRIGGERING_OUTPUT_SYNC:
        return

    if str(state or '').upper() != 'SUCCESS':
        logger.debug(
            "Skipping output export sync after task %s (%s)",
            task_name,
            state,
        )
        return

    try:
        from apps.media_servers.tasks import _queue_output_export_sync

        safe_task_id = str(task_id or '')[:64]
        _queue_output_export_sync(reason=f'vod_task:{task_name}:{safe_task_id}')
    except Exception:
        logger.exception(
            "Failed to queue output export sync after %s",
            task_name,
        )
