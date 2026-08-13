from __future__ import annotations

import logging

from celery.signals import task_postrun
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_migrate, post_save
from django.dispatch import receiver

from core.scheduling import create_or_update_periodic_task, delete_periodic_task

from apps.vod.models import Movie, Series, VODLogo

from .artwork import (
    delete_media_library_logo_if_unused,
    media_library_artwork_path,
    remove_media_library_artwork_file,
)
from .models import MediaLibraryExportTarget, MediaLibrarySource

logger = logging.getLogger(__name__)

VOD_TASKS_TRIGGERING_EXPORT = {
    "apps.vod.tasks.refresh_vod_content",
    "apps.vod.tasks.batch_refresh_series_episodes",
    "apps.vod.tasks.cleanup_orphaned_vod_content",
}


@receiver(post_migrate)
def create_default_dvr_media_library(sender, app_config=None, **kwargs):
    if not app_config or app_config.label != "media_servers":
        return
    from .dvr_library import ensure_dvr_media_library_source

    ensure_dvr_media_library_source()


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


def _update_export_series_schedule(target):
    task = create_or_update_periodic_task(
        task_name=f"media-library-series-refresh-{target.id}",
        celery_task_path=(
            "apps.media_servers.export_tasks.refresh_selected_series_and_export"
        ),
        kwargs={"target_id": target.id},
        interval_hours=int(target.series_refresh_interval or 0),
        enabled=bool(
            target.enabled
            and int(target.series_refresh_interval or 0) > 0
            and target.selected_series.exists()
        ),
    )
    if target.series_refresh_task_id != task.id:
        MediaLibraryExportTarget.objects.filter(id=target.id).update(
            series_refresh_task=task
        )


@receiver(post_save, sender=MediaLibraryExportTarget)
def update_export_series_schedule(sender, instance, **kwargs):
    _update_export_series_schedule(instance)


@receiver(
    m2m_changed,
    sender=MediaLibraryExportTarget.selected_series.through,
)
def update_export_series_schedule_after_selection(sender, instance, action, **kwargs):
    if action in {"post_add", "post_remove", "post_clear"}:
        _update_export_series_schedule(instance)


@receiver(post_delete, sender=MediaLibraryExportTarget)
def delete_export_series_schedule(sender, instance, **kwargs):
    delete_periodic_task(f"media-library-series-refresh-{instance.id}")


@receiver(post_delete, sender=Movie)
@receiver(post_delete, sender=Series)
def cleanup_unused_media_library_logo(sender, instance, **kwargs):
    logo_id = instance.logo_id
    if logo_id:
        transaction.on_commit(
            lambda: delete_media_library_logo_if_unused(logo_id)
        )


@receiver(post_delete, sender=VODLogo)
def cleanup_media_library_artwork_file(sender, instance, **kwargs):
    if media_library_artwork_path(instance.url) is not None:
        value = instance.url
        transaction.on_commit(
            lambda: remove_media_library_artwork_file(value)
        )


def _vod_task_result_succeeded(result) -> bool:
    if isinstance(result, dict):
        if result.get("error"):
            return False
        try:
            if int(result.get("failed") or 0) > 0:
                return False
        except (TypeError, ValueError):
            return False
    if isinstance(result, str):
        normalized = result.strip().lower()
        if "failed" in normalized or "only available" in normalized:
            return False
    return True


@receiver(task_postrun)
def queue_export_after_vod_task(
    sender=None,
    task=None,
    state=None,
    retval=None,
    **kwargs,
):
    task_name = getattr(sender, "name", "") or getattr(task, "name", "")
    if task_name not in VOD_TASKS_TRIGGERING_EXPORT:
        return
    if str(state or "").upper() != "SUCCESS":
        return
    if not _vod_task_result_succeeded(retval):
        logger.warning(
            "Skipping automatic Media Library export after semantic VOD task failure: %s",
            task_name,
        )
        return
    from .export_tasks import queue_automatic_exports

    queue_automatic_exports.delay(f"vod-task:{task_name}")
