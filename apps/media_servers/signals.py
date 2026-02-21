import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.media_servers.models import MediaServerIntegration
from core.scheduling import create_or_update_periodic_task, delete_periodic_task

logger = logging.getLogger(__name__)


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
