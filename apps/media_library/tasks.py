import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.media_library.metadata import METADATA_CACHE_TIMEOUT, sync_metadata
from apps.media_library.models import Library, LibraryScan, MediaItem
from apps.media_library.scanner import ScanCancelled, scan_library_files
from apps.media_library.vod import sync_vod_for_media_item
from core.models import CoreSettings

logger = logging.getLogger(__name__)

STAGE_DISCOVERY = "discovery"
STAGE_METADATA = "metadata"
STAGE_ARTWORK = "artwork"


def _update_stage(scan: LibraryScan, stage_key: str, *, status=None, processed=None, total=None):
    stages = scan.stages or {}
    stage = stages.get(stage_key, {"status": "pending", "processed": 0, "total": 0})
    if status is not None:
        stage["status"] = status
    if processed is not None:
        stage["processed"] = processed
    if total is not None:
        stage["total"] = total
    stages[stage_key] = stage
    scan.stages = stages
    scan.save(update_fields=["stages", "updated_at"])


def _filter_metadata_queryset(queryset, *, force: bool):
    if force or not METADATA_CACHE_TIMEOUT:
        return queryset
    cutoff = timezone.now() - timedelta(seconds=METADATA_CACHE_TIMEOUT)
    return queryset.filter(
        Q(metadata_last_synced_at__isnull=True)
        | Q(metadata_last_synced_at__lt=cutoff)
        | Q(poster_url__isnull=True)
        | Q(poster_url="")
        | Q(backdrop_url__isnull=True)
        | Q(backdrop_url="")
    )


@shared_task(bind=True)
def scan_library(self, library_id: int, *, full: bool = False, scan_id: int | None = None):
    library = Library.objects.get(id=library_id)
    scan_type = LibraryScan.SCAN_FULL if full else LibraryScan.SCAN_QUICK

    if scan_id:
        scan = LibraryScan.objects.get(id=scan_id, library=library)
    else:
        scan = LibraryScan.objects.create(
            library=library,
            scan_type=scan_type,
            status=LibraryScan.STATUS_QUEUED,
            summary="Full scan" if full else "Quick scan",
            stages={},
        )

    if scan.status == LibraryScan.STATUS_CANCELLED:
        scan.finished_at = scan.finished_at or timezone.now()
        scan.save(update_fields=["finished_at", "updated_at"])
        _update_stage(scan, STAGE_DISCOVERY, status="cancelled")
        _update_stage(scan, STAGE_METADATA, status="skipped")
        _update_stage(scan, STAGE_ARTWORK, status="skipped")
        return

    scan.task_id = self.request.id
    scan.status = LibraryScan.STATUS_RUNNING
    scan.started_at = timezone.now()
    scan.save(update_fields=["task_id", "status", "started_at", "updated_at"])

    library.last_scan_at = scan.started_at
    library.save(update_fields=["last_scan_at", "updated_at"])

    _update_stage(scan, STAGE_DISCOVERY, status="running", processed=0, total=0)
    _update_stage(scan, STAGE_METADATA, status="pending", processed=0, total=0)
    _update_stage(scan, STAGE_ARTWORK, status="pending", processed=0, total=0)

    def cancel_check():
        scan.refresh_from_db(fields=["status"])
        return scan.status == LibraryScan.STATUS_CANCELLED

    def progress_callback(processed: int, _total: int):
        scan.processed_files = processed
        scan.total_files = processed
        scan.save(update_fields=["processed_files", "total_files", "updated_at"])
        _update_stage(
            scan,
            STAGE_DISCOVERY,
            status="running",
            processed=processed,
        )

    try:
        result = scan_library_files(
            library,
            full=full,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
    except ScanCancelled:
        scan.status = LibraryScan.STATUS_CANCELLED
        scan.finished_at = timezone.now()
        scan.save(update_fields=["status", "finished_at", "updated_at"])
        _update_stage(scan, STAGE_DISCOVERY, status="cancelled")
        _update_stage(scan, STAGE_METADATA, status="skipped")
        _update_stage(scan, STAGE_ARTWORK, status="skipped")
        return
    except Exception:
        logger.exception("Library scan failed for %s", library.name)
        scan.status = LibraryScan.STATUS_FAILED
        scan.finished_at = timezone.now()
        scan.save(update_fields=["status", "finished_at", "updated_at"])
        _update_stage(scan, STAGE_DISCOVERY, status="failed")
        _update_stage(scan, STAGE_METADATA, status="skipped")
        _update_stage(scan, STAGE_ARTWORK, status="skipped")
        return

    scan.processed_files = result.processed_files
    scan.total_files = result.total_files
    scan.new_files = result.new_files
    scan.updated_files = result.updated_files
    scan.removed_files = result.removed_files
    scan.unmatched_files = result.unmatched_files
    scan.extra = {
        "errors": result.errors,
        "unmatched_paths": result.unmatched_paths,
    }
    scan.save(
        update_fields=[
            "processed_files",
            "total_files",
            "new_files",
            "updated_files",
            "removed_files",
            "unmatched_files",
            "extra",
            "updated_at",
        ]
    )

    _update_stage(
        scan,
        STAGE_DISCOVERY,
        status="completed",
        processed=result.processed_files,
        total=result.total_files,
    )

    metadata_ids = list(result.metadata_item_ids)
    if not metadata_ids:
        _update_stage(scan, STAGE_METADATA, status="completed", processed=0, total=0)
        _update_stage(scan, STAGE_ARTWORK, status="completed", processed=0, total=0)
        scan.status = LibraryScan.STATUS_COMPLETED
        scan.finished_at = timezone.now()
        scan.save(update_fields=["status", "finished_at", "updated_at"])
        library.last_successful_scan_at = scan.finished_at
        library.save(update_fields=["last_successful_scan_at", "updated_at"])
        return

    metadata_qs = MediaItem.objects.filter(id__in=metadata_ids)
    metadata_qs = _filter_metadata_queryset(metadata_qs, force=full)
    metadata_total = metadata_qs.count()
    artwork_total = metadata_qs.filter(
        item_type__in=[MediaItem.TYPE_MOVIE, MediaItem.TYPE_SHOW]
    ).count()
    if not metadata_total:
        _update_stage(scan, STAGE_METADATA, status="completed", processed=0, total=0)
        _update_stage(scan, STAGE_ARTWORK, status="completed", processed=0, total=0)
        scan.status = LibraryScan.STATUS_COMPLETED
        scan.finished_at = timezone.now()
        scan.save(update_fields=["status", "finished_at", "updated_at"])
        library.last_successful_scan_at = scan.finished_at
        library.save(update_fields=["last_successful_scan_at", "updated_at"])
        return

    _update_stage(scan, STAGE_METADATA, status="running", processed=0, total=metadata_total)
    _update_stage(scan, STAGE_ARTWORK, status="running", processed=0, total=artwork_total)

    processed = 0
    artwork_processed = 0
    allow_remote = not CoreSettings.get_prefer_local_metadata()

    for media_item in metadata_qs.iterator():
        if cancel_check():
            scan.status = LibraryScan.STATUS_CANCELLED
            scan.finished_at = timezone.now()
            scan.save(update_fields=["status", "finished_at", "updated_at"])
            _update_stage(scan, STAGE_METADATA, status="cancelled")
            _update_stage(scan, STAGE_ARTWORK, status="cancelled")
            return

        updated = sync_metadata(media_item, force=full, allow_remote=allow_remote)
        try:
            sync_vod_for_media_item(media_item)
        except Exception:
            logger.exception("Failed to sync VOD for media item %s", media_item.id)
        processed += 1
        if (
            media_item.item_type in {MediaItem.TYPE_MOVIE, MediaItem.TYPE_SHOW}
            and updated
            and (updated.poster_url or updated.backdrop_url)
        ):
            artwork_processed += 1

        if processed % 25 == 0 or processed == metadata_total:
            _update_stage(
                scan,
                STAGE_METADATA,
                status="running",
                processed=processed,
                total=metadata_total,
            )
            _update_stage(
                scan,
                STAGE_ARTWORK,
                status="running",
                processed=artwork_processed,
                total=artwork_total,
            )

    _update_stage(
        scan,
        STAGE_METADATA,
        status="completed",
        processed=processed,
        total=metadata_total,
    )
    _update_stage(
        scan,
        STAGE_ARTWORK,
        status="completed",
        processed=artwork_processed,
        total=artwork_total,
    )

    scan.status = LibraryScan.STATUS_COMPLETED
    scan.finished_at = timezone.now()
    scan.save(update_fields=["status", "finished_at", "updated_at"])
    library.last_successful_scan_at = scan.finished_at
    library.save(update_fields=["last_successful_scan_at", "updated_at"])


@shared_task
def refresh_media_item_metadata(item_id: int):
    try:
        media_item = MediaItem.objects.get(id=item_id)
    except MediaItem.DoesNotExist:
        return
    sync_metadata(media_item, force=True)
    try:
        sync_vod_for_media_item(media_item)
    except Exception:
        logger.exception("Failed to sync VOD for media item %s", media_item.id)


@shared_task
def refresh_library_metadata(library_id: int):
    items = MediaItem.objects.filter(library_id=library_id).iterator()
    for item in items:
        sync_metadata(item, force=True)
        try:
            sync_vod_for_media_item(item)
        except Exception:
            logger.exception("Failed to sync VOD for media item %s", item.id)
