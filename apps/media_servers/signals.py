from __future__ import annotations

import logging

from celery.signals import task_postrun
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.scheduling import create_or_update_periodic_task, delete_periodic_task

from .models import MediaLibrarySource

logger = logging.getLogger(__name__)

VOD_TASKS_TRIGGERING_EXPORT = {
    "apps.vod.tasks.refresh_vod_content",
    "apps.vod.tasks.cleanup_orphaned_vod_content",
}


@receiver(post_save, sender=MediaLibrarySource)
def update_source_schedule(sender, instance, **kwargs):
    task = create_or_update_periodic_task(
        task_name=f"media-library-import-{instance.id}",
        celery_task_path="apps.media_servers.tasks.sync_media_server_integration",
        kwargs={"integration_id": instance.id},
        interval_hours=int(instance.sync_interval or 0),
        enabled=bool(
            instance.enabled
            and instance.add_to_vod
            and int(instance.sync_interval or 0) > 0
        ),
    )
    if instance.sync_task_id != task.id:
        MediaLibrarySource.objects.filter(id=instance.id).update(sync_task=task)


@receiver(post_delete, sender=MediaLibrarySource)
def delete_source_schedule(sender, instance, **kwargs):
    delete_periodic_task(f"media-library-import-{instance.id}")


@receiver(task_postrun)
def queue_export_after_vod_task(sender=None, task=None, state=None, **kwargs):
    task_name = getattr(sender, "name", "") or getattr(task, "name", "")
    if task_name not in VOD_TASKS_TRIGGERING_EXPORT:
        return
    if str(state or "").upper() != "SUCCESS":
        return
    from .export_tasks import queue_automatic_exports

    queue_automatic_exports.delay(f"vod-task:{task_name}")
