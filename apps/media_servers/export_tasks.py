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
def refresh_selected_series_and_export(
    target_id: int,
    export_run_id: Optional[int] = None,
    reason: str = "scheduled-series-refresh",
):
    """Refresh selected XC shows, then rebuild this target's STRM snapshot."""
    target = MediaLibraryExportTarget.objects.filter(id=target_id).first()
    if not target:
        return f"Export target {target_id} not found"

    if not target.enabled:
        if export_run_id:
            MediaLibraryExportRun.objects.filter(
                id=export_run_id,
                target=target,
                status__in=(
                    MediaLibraryExportRun.Status.PENDING,
                    MediaLibraryExportRun.Status.QUEUED,
                    MediaLibraryExportRun.Status.RUNNING,
                ),
            ).update(
                status=MediaLibraryExportRun.Status.FAILED,
                message="Export target is disabled.",
                finished_at=timezone.now(),
                updated_at=timezone.now(),
            )
        return f"Export target {target_id} is disabled"

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
                reason=str(reason or "scheduled-series-refresh")[:255],
                message="Selected-series refresh queued.",
            )
        except IntegrityError:
            return "An export is already active for this target."
    if run.status == MediaLibraryExportRun.Status.CANCELLED:
        return f"Export run {run.id} was cancelled before starting."

    lock = RedisClient.get_client().lock(
        f"media_library_series_refresh:{target.id}",
        timeout=24 * 60 * 60,
        blocking_timeout=0,
    )
    if not lock.acquire(blocking=False):
        message = "A selected-series refresh is already running for this target."
        run.status = MediaLibraryExportRun.Status.FAILED
        run.message = message
        run.finished_at = timezone.now()
        run.save()
        return message

    last_lock_refresh = monotonic()

    def check_refresh_cancel():
        nonlocal last_lock_refresh
        now = monotonic()
        if now - last_lock_refresh >= 300:
            try:
                lock.extend(24 * 60 * 60, replace_ttl=True)
            except Exception as exc:
                raise RuntimeError(
                    "The distributed selected-series refresh lock was lost."
                ) from exc
            last_lock_refresh = now
        run.refresh_from_db(fields=["status", "cancellation_requested_at"])
        if (
            run.status == MediaLibraryExportRun.Status.CANCELLED
            or run.cancellation_requested_at
        ):
            raise ExportCancelled(
                "Export cancelled while refreshing selected TV series."
            )

    try:
        from apps.m3u.models import M3UAccount
        from apps.vod.tasks import refresh_due_series_episodes

        run.status = MediaLibraryExportRun.Status.RUNNING
        run.message = "Refreshing episode lists for selected TV series."
        run.started_at = run.started_at or timezone.now()
        run.save()
        target.last_export_status = MediaLibraryExportTarget.ExportStatus.RUNNING
        target.last_export_message = run.message
        target.save(
            update_fields=[
                "last_export_status",
                "last_export_message",
                "updated_at",
            ]
        )

        selected_ids = list(target.selected_series.values_list("id", flat=True))
        refresh_summary = {"series": len(selected_ids), "accounts": {}}
        failed_refreshes = 0
        if selected_ids:
            accounts = M3UAccount.objects.filter(
                is_active=True,
                account_type=M3UAccount.Types.XC,
                series_relations__series_id__in=selected_ids,
            ).select_related("user_agent").distinct()
            for account in accounts:
                account_series_ids = list(
                    target.selected_series.filter(
                        m3u_relations__m3u_account=account,
                    ).values_list("id", flat=True)
                )
                refresh_summary["accounts"][str(account.id)] = (
                    refresh_due_series_episodes(
                        account,
                        series_ids=account_series_ids,
                        progress_callback=check_refresh_cancel,
                    )
                )
                failed_refreshes += int(
                    refresh_summary["accounts"][str(account.id)].get("failed")
                    or 0
                )

        refresh_summary["failed"] = failed_refreshes
        run.summary = {"series_refresh": refresh_summary}
        run.save(update_fields=["summary", "updated_at"])
        if failed_refreshes:
            raise RuntimeError(
                f"{failed_refreshes} selected TV series failed to refresh; "
                "the STRM/NFO export was not rebuilt."
            )

        check_refresh_cancel()
        run.status = MediaLibraryExportRun.Status.QUEUED
        run.message = "Selected TV series refreshed; STRM/NFO export queued."
        run.save()
        result = export_media_library.delay(target.id, run.id)
        run.task_id = result.id or ""
        run.save(update_fields=["task_id", "updated_at"])
        refresh_summary["export_run"] = run.id
        return refresh_summary
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
        logger.exception(
            "Selected-series refresh failed for export target %s",
            target.id,
        )
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
            logger.warning(
                "Selected-series lock for target %s was already released",
                target.id,
            )


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
        run.started_at = run.started_at or timezone.now()
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
        previous_summary = dict(run.summary or {})
        run.summary = {
            **summary,
            **(
                {"series_refresh": previous_summary["series_refresh"]}
                if "series_refresh" in previous_summary
                else {}
            ),
        }
        skipped_existing = (
            int(summary.get("movies_skipped_existing") or 0)
            + int(summary.get("episodes_skipped_existing") or 0)
        )
        run.message = (
            f'{summary["strm_files_written"]} STRM and '
            f'{summary["nfo_files_written"]} NFO files written.'
        )
        if skipped_existing:
            run.message += (
                f" {skipped_existing} item(s) already present in an imported "
                "media server were omitted."
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
