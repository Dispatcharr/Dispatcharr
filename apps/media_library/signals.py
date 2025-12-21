import json
import logging

from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from apps.media_library.models import Library, MediaItem
from apps.media_library.vod import cleanup_library_vod, cleanup_media_item_vod

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Library)
def create_or_update_scan_task(sender, instance, **kwargs):
    interval_minutes = int(instance.scan_interval_minutes or 0)
    task_name = f"media-library-scan-{instance.id}"
    should_be_enabled = instance.auto_scan_enabled and interval_minutes > 0

    if interval_minutes <= 0:
        if should_be_enabled:
            logger.warning("Scan interval invalid for library %s", instance.id)
        try:
            task = PeriodicTask.objects.get(name=task_name)
            if task.enabled:
                task.enabled = False
                task.save(update_fields=["enabled"])
        except PeriodicTask.DoesNotExist:
            pass
        return

    interval, _ = IntervalSchedule.objects.get_or_create(
        every=interval_minutes, period=IntervalSchedule.MINUTES
    )

    kwargs_payload = json.dumps({"library_id": instance.id, "full": False})

    try:
        task = PeriodicTask.objects.get(name=task_name)
        updated_fields = []

        if task.enabled != should_be_enabled:
            task.enabled = should_be_enabled
            updated_fields.append("enabled")
        if task.interval != interval:
            task.interval = interval
            updated_fields.append("interval")
        if task.kwargs != kwargs_payload:
            task.kwargs = kwargs_payload
            updated_fields.append("kwargs")

        if updated_fields:
            task.save(update_fields=updated_fields)
    except PeriodicTask.DoesNotExist:
        PeriodicTask.objects.create(
            name=task_name,
            interval=interval,
            task="apps.media_library.tasks.scan_library",
            kwargs=kwargs_payload,
            enabled=should_be_enabled,
        )


@receiver(post_delete, sender=Library)
def delete_scan_task(sender, instance, **kwargs):
    task_name = f"media-library-scan-{instance.id}"
    try:
        PeriodicTask.objects.filter(name=task_name).delete()
    except Exception as exc:
        logger.warning("Failed to delete scan task for library %s: %s", instance.id, exc)


@receiver(pre_delete, sender=Library)
def delete_library_vod(sender, instance, **kwargs):
    try:
        cleanup_library_vod(instance)
    except Exception as exc:
        logger.warning("Failed to cleanup VOD for library %s: %s", instance.id, exc)


@receiver(pre_delete, sender=MediaItem)
def delete_media_item_vod(sender, instance, **kwargs):
    try:
        cleanup_media_item_vod(instance)
    except Exception as exc:
        logger.warning("Failed to cleanup VOD for media item %s: %s", instance.id, exc)
