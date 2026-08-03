from __future__ import annotations

import logging
from typing import Optional
from time import monotonic

from celery import shared_task
from django.db import IntegrityError
from django.utils import timezone

from core.utils import RedisClient

from .models import MediaLibraryExportRun, MediaLibraryExportTarget
from .strm_export import build_strm_nfo_snapshot

logger = logging.getLogger(__name__)


class ExportCancelled(Exception):
    pass


@shared_task
def queue_automatic_exports(reason: str = "vod-change"):
    queued = []
    for target in MediaLibraryExportTarget.objects.filter(
        enabled=True,
        auto_export_on_vod_change=True,
    ):
        try:
            run = MediaLibraryExportRun.objects.create(
                target=target,
                status=MediaLibraryExportRun.Status.QUEUED,
                reason=str(reason or "")[:255],
                message="Export queued.",
            )
        except IntegrityError:
            continue
        result = export_media_library.delay(target.id, run.id)
        run.task_id = result.id or ""
        run.save(update_fields=["task_id", "updated_at"])
        queued.append(run.id)
    return queued


@shared_task(bind=True)
def export_media_library(
    self,
    target_id: int,
    export_run_id: Optional[int] = None,
):
    target = MediaLibraryExportTarget.objects.filter(id=target_id).first()
    if not target:
        return f"Export target {target_id} not found"

    run = None
    if export_run_id:
        run = MediaLibraryExportRun.objects.filter(
            id=export_run_id,
            target=target,
        ).first()
    if not run:
        try:
            run = MediaLibraryExportRun.objects.create(
                target=target,
                status=MediaLibraryExportRun.Status.QUEUED,
                reason="scheduled",
                message="Export queued.",
            )
        except IntegrityError:
            return "An export is already active for this target."
    if run.status == MediaLibraryExportRun.Status.CANCELLED:
        return f"Export run {run.id} was cancelled before starting."

    lock = RedisClient.get_client().lock(
        f"media_library_export:{target.id}",
        timeout=24 * 60 * 60,
        blocking_timeout=0,
    )
    if not lock.acquire(blocking=False):
        run.status = MediaLibraryExportRun.Status.FAILED
        run.message = "Another export is already running for this target."
        run.finished_at = timezone.now()
        run.save()
        return run.message

    last_lock_refresh = monotonic()

    def check_cancel():
        nonlocal last_lock_refresh
        now = monotonic()
        if now - last_lock_refresh >= 300:
            try:
                lock.extend(24 * 60 * 60, replace_ttl=True)
            except Exception as exc:
                raise RuntimeError(
                    "The distributed export lock was lost."
                ) from exc
            last_lock_refresh = now
        run.refresh_from_db(fields=["status", "cancellation_requested_at"])
        if (
            run.status == MediaLibraryExportRun.Status.CANCELLED
            or run.cancellation_requested_at
        ):
            raise ExportCancelled("Export cancelled by administrator.")

    try:
        check_cancel()
        if not target.enabled:
            raise ValueError("Export target is disabled.")
        run.status = MediaLibraryExportRun.Status.RUNNING
        run.task_id = getattr(self.request, "id", "") or run.task_id
        run.started_at = timezone.now()
        run.finished_at = None
        run.message = "Building STRM/NFO library."
        run.save()
        target.last_export_status = MediaLibraryExportTarget.ExportStatus.RUNNING
        target.last_export_message = "Export running."
        target.save(
            update_fields=[
                "last_export_status",
                "last_export_message",
                "updated_at",
            ]
        )

        summary = build_strm_nfo_snapshot(
            target,
            cancel_check=check_cancel,
        )
        run.status = MediaLibraryExportRun.Status.COMPLETED
        run.summary = summary
        run.message = (
            f'{summary["strm_files_written"]} STRM and '
            f'{summary["nfo_files_written"]} NFO files written.'
        )
        run.finished_at = timezone.now()
        run.save()
        target.last_exported_at = run.finished_at
        target.last_export_status = MediaLibraryExportTarget.ExportStatus.SUCCESS
        target.last_export_message = run.message
        target.last_export_summary = summary
        target.save()
        return summary
    except ExportCancelled as exc:
        run.status = MediaLibraryExportRun.Status.CANCELLED
        run.message = str(exc)
        run.finished_at = timezone.now()
        run.save()
        target.last_export_status = MediaLibraryExportTarget.ExportStatus.ERROR
        target.last_export_message = str(exc)
        target.save(
            update_fields=[
                "last_export_status",
                "last_export_message",
                "updated_at",
            ]
        )
        return str(exc)
    except Exception as exc:
        logger.exception("Media library export failed for target %s", target.id)
        run.status = MediaLibraryExportRun.Status.FAILED
        run.message = str(exc)[:4000]
        run.finished_at = timezone.now()
        run.save()
        target.last_export_status = MediaLibraryExportTarget.ExportStatus.ERROR
        target.last_export_message = str(exc)[:2000]
        target.save(
            update_fields=[
                "last_export_status",
                "last_export_message",
                "updated_at",
            ]
        )
        raise
    finally:
        try:
            lock.release()
        except Exception:
            logger.warning("Export lock for target %s was already released", target.id)
