import logging
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import timedelta
from time import monotonic

from celery import shared_task
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from apps.media_library.metadata import METADATA_CACHE_TIMEOUT, sync_metadata
from apps.media_library.models import Library, LibraryScan, MediaItem
from apps.media_library.scanner import ScanCancelled, scan_library_files
from apps.media_library.serializers import LibraryScanSerializer, MediaItemSerializer
from apps.media_library.vod import sync_vod_for_media_item
from core.utils import send_websocket_update

logger = logging.getLogger(__name__)

STAGE_DISCOVERY = "discovery"
STAGE_METADATA = "metadata"
STAGE_ARTWORK = "artwork"

DEFAULT_METADATA_PARALLELISM = 3
MIN_METADATA_PARALLELISM = 1
MAX_METADATA_PARALLELISM = 6


def _resolve_metadata_parallelism() -> int:
    raw_value = (os.environ.get("MEDIA_LIBRARY_METADATA_PARALLELISM") or "").strip()
    if raw_value:
        try:
            parsed = int(raw_value)
            if MIN_METADATA_PARALLELISM <= parsed <= MAX_METADATA_PARALLELISM:
                return parsed
            logger.warning(
                "Ignoring MEDIA_LIBRARY_METADATA_PARALLELISM=%s (expected %s-%s)",
                raw_value,
                MIN_METADATA_PARALLELISM,
                MAX_METADATA_PARALLELISM,
            )
        except ValueError:
            logger.warning(
                "Ignoring invalid MEDIA_LIBRARY_METADATA_PARALLELISM=%s (expected integer)",
                raw_value,
            )

    cpu_count = os.cpu_count() or DEFAULT_METADATA_PARALLELISM
    if cpu_count <= 2:
        return 2
    if cpu_count <= 4:
        return 3
    if cpu_count <= 8:
        return 4
    return 5


METADATA_PARALLELISM = _resolve_metadata_parallelism()
METADATA_FILTER_BATCH_SIZE = 50
METADATA_PROGRESS_UPDATE_INTERVAL = 12
SCAN_WS_UPDATE_INTERVAL_SECONDS = 1.0


def _update_stage(
    scan: LibraryScan,
    stage_key: str,
    *,
    status=None,
    processed=None,
    total=None,
):
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


def _broadcast_scan_update(scan: LibraryScan, state: dict[str, float], *, force=False):
    now = monotonic()
    if not force and now - state.get("last_sent", 0.0) < SCAN_WS_UPDATE_INTERVAL_SECONDS:
        return
    state["last_sent"] = now
    send_websocket_update(
        "updates",
        "update",
        {
            "type": "media_library_scan_updated",
            "scan": LibraryScanSerializer(scan).data,
        },
    )


def _broadcast_item_update(payload: dict):
    send_websocket_update(
        "updates",
        "update",
        {
            "type": "media_library_item_updated",
            "item": payload,
        },
    )


def _sync_metadata_worker(item_id: int, *, force: bool, allow_remote: bool):
    close_old_connections()
    try:
        media_item = MediaItem.objects.select_related("library").filter(id=item_id).first()
        if not media_item:
            return {"has_artwork": False, "payload": None}

        before_synced_at = media_item.metadata_last_synced_at
        before_poster = media_item.poster_url or ""
        before_backdrop = media_item.backdrop_url or ""
        before_synopsis = media_item.synopsis or ""

        updated = sync_metadata(media_item, force=force, allow_remote=allow_remote)
        current = updated or media_item

        if current.library.add_to_vod:
            try:
                sync_vod_for_media_item(current)
            except Exception:
                logger.exception("Failed to sync VOD for media item %s", current.id)

        changed = (
            current.metadata_last_synced_at != before_synced_at
            or (current.poster_url or "") != before_poster
            or (current.backdrop_url or "") != before_backdrop
            or (current.synopsis or "") != before_synopsis
        )
        payload = MediaItemSerializer(current).data if changed else None
        has_artwork = bool((current.poster_url or "").strip() or (current.backdrop_url or "").strip())
        return {"has_artwork": has_artwork, "payload": payload}
    finally:
        close_old_connections()


@shared_task(bind=True)
def scan_library(self, library_id: int, *, full: bool = False, scan_id: int | None = None):
    library = Library.objects.get(id=library_id)
    scan_type = LibraryScan.SCAN_FULL if full else LibraryScan.SCAN_QUICK
    ws_state = {"last_sent": 0.0}

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
        _broadcast_scan_update(scan, ws_state, force=True)
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
    _broadcast_scan_update(scan, ws_state, force=True)

    metadata_buffer: set[int] = set()
    metadata_scheduled: set[int] = set()
    metadata_futures: dict = {}
    metadata_total = 0
    metadata_processed = 0
    artwork_total = 0
    artwork_processed = 0
    metadata_running = False
    last_metadata_stage_flush = 0.0
    last_metadata_buffer_flush = 0.0
    # "Prefer local metadata" means local-first, not local-only.
    allow_remote = True

    def cancel_check():
        scan.refresh_from_db(fields=["status"])
        return scan.status == LibraryScan.STATUS_CANCELLED

    def flush_metadata_stages(*, force=False, status="running"):
        nonlocal last_metadata_stage_flush
        if status == "running" and not metadata_running:
            return
        now = monotonic()
        if not force and metadata_processed:
            if (
                metadata_processed % METADATA_PROGRESS_UPDATE_INTERVAL != 0
                and now - last_metadata_stage_flush < 1.5
            ):
                return
        _update_stage(
            scan,
            STAGE_METADATA,
            status=status,
            processed=metadata_processed,
            total=metadata_total,
        )
        _update_stage(
            scan,
            STAGE_ARTWORK,
            status=status,
            processed=artwork_processed,
            total=artwork_total,
        )
        last_metadata_stage_flush = now
        _broadcast_scan_update(scan, ws_state, force=force)

    def schedule_metadata_item(item_id: int, item_type: str):
        nonlocal metadata_total, artwork_total, metadata_running
        if item_id in metadata_scheduled:
            return
        metadata_scheduled.add(item_id)
        metadata_total += 1
        if item_type in {MediaItem.TYPE_MOVIE, MediaItem.TYPE_SHOW}:
            artwork_total += 1
        if not metadata_running:
            metadata_running = True
            _update_stage(
                scan,
                STAGE_METADATA,
                status="running",
                processed=metadata_processed,
                total=metadata_total,
            )
            _update_stage(
                scan,
                STAGE_ARTWORK,
                status="running",
                processed=artwork_processed,
                total=artwork_total,
            )
            _broadcast_scan_update(scan, ws_state, force=True)
        future = executor.submit(
            _sync_metadata_worker,
            item_id,
            force=full,
            allow_remote=allow_remote,
        )
        metadata_futures[future] = item_id

    def process_done_futures(done_futures):
        nonlocal metadata_processed, artwork_processed
        if not done_futures:
            return
        for future in done_futures:
            metadata_futures.pop(future, None)
            metadata_processed += 1
            try:
                outcome = future.result()
            except Exception:
                logger.exception("Metadata refresh worker failed")
                continue
            if outcome.get("has_artwork"):
                artwork_processed += 1
            payload = outcome.get("payload")
            if payload:
                _broadcast_item_update(payload)
        flush_metadata_stages(
            force=(metadata_processed == metadata_total),
            status="running",
        )

    def drain_finished_futures(*, limit=None):
        done = [future for future in list(metadata_futures.keys()) if future.done()]
        if not done:
            return
        if limit is not None:
            done = done[:limit]
        process_done_futures(done)

    def flush_metadata_buffer(*, force=False):
        nonlocal last_metadata_buffer_flush
        if not metadata_buffer:
            return
        now = monotonic()
        if (
            not force
            and len(metadata_buffer) < METADATA_FILTER_BATCH_SIZE
            and now - last_metadata_buffer_flush < 1.0
        ):
            return
        buffer_ids = list(metadata_buffer)
        metadata_buffer.clear()
        queryset = _filter_metadata_queryset(
            MediaItem.objects.filter(id__in=buffer_ids),
            force=full,
        )
        for item_id, item_type in queryset.values_list("id", "item_type"):
            schedule_metadata_item(item_id, item_type)
        last_metadata_buffer_flush = now

    def metadata_candidate_callback(item_id: int):
        if item_id in metadata_scheduled or item_id in metadata_buffer:
            return
        metadata_buffer.add(item_id)
        flush_metadata_buffer(force=False)

    def progress_callback(processed: int, _total: int):
        if processed < scan.processed_files:
            return
        scan.processed_files = processed
        scan.total_files = processed
        scan.save(update_fields=["processed_files", "total_files", "updated_at"])
        _update_stage(
            scan,
            STAGE_DISCOVERY,
            status="running",
            processed=processed,
        )
        flush_metadata_buffer(force=False)
        drain_finished_futures(limit=METADATA_PROGRESS_UPDATE_INTERVAL)
        _broadcast_scan_update(scan, ws_state, force=False)

    executor = ThreadPoolExecutor(max_workers=METADATA_PARALLELISM)
    try:
        try:
            result = scan_library_files(
                library,
                full=full,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                metadata_callback=metadata_candidate_callback,
            )
        except ScanCancelled:
            scan.status = LibraryScan.STATUS_CANCELLED
            scan.finished_at = timezone.now()
            scan.save(update_fields=["status", "finished_at", "updated_at"])
            _update_stage(scan, STAGE_DISCOVERY, status="cancelled")
            if metadata_running:
                _update_stage(scan, STAGE_METADATA, status="cancelled")
                _update_stage(scan, STAGE_ARTWORK, status="cancelled")
            else:
                _update_stage(scan, STAGE_METADATA, status="skipped")
                _update_stage(scan, STAGE_ARTWORK, status="skipped")
            _broadcast_scan_update(scan, ws_state, force=True)
            return
        except Exception:
            logger.exception("Library scan failed for %s", library.name)
            scan.status = LibraryScan.STATUS_FAILED
            scan.finished_at = timezone.now()
            scan.save(update_fields=["status", "finished_at", "updated_at"])
            _update_stage(scan, STAGE_DISCOVERY, status="failed")
            if metadata_running:
                _update_stage(scan, STAGE_METADATA, status="failed")
                _update_stage(scan, STAGE_ARTWORK, status="failed")
            else:
                _update_stage(scan, STAGE_METADATA, status="skipped")
                _update_stage(scan, STAGE_ARTWORK, status="skipped")
            _broadcast_scan_update(scan, ws_state, force=True)
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
        _broadcast_scan_update(scan, ws_state, force=True)

        for item_id in result.metadata_item_ids:
            if item_id not in metadata_scheduled:
                metadata_buffer.add(item_id)
        flush_metadata_buffer(force=True)
        drain_finished_futures(limit=None)

        if metadata_total == 0:
            _update_stage(scan, STAGE_METADATA, status="completed", processed=0, total=0)
            _update_stage(scan, STAGE_ARTWORK, status="completed", processed=0, total=0)
            scan.status = LibraryScan.STATUS_COMPLETED
            scan.finished_at = timezone.now()
            scan.save(update_fields=["status", "finished_at", "updated_at"])
            library.last_successful_scan_at = scan.finished_at
            library.save(update_fields=["last_successful_scan_at", "updated_at"])
            _broadcast_scan_update(scan, ws_state, force=True)
            return

        while metadata_futures:
            if cancel_check():
                scan.status = LibraryScan.STATUS_CANCELLED
                scan.finished_at = timezone.now()
                scan.save(update_fields=["status", "finished_at", "updated_at"])
                _update_stage(scan, STAGE_METADATA, status="cancelled")
                _update_stage(scan, STAGE_ARTWORK, status="cancelled")
                _broadcast_scan_update(scan, ws_state, force=True)
                return

            done, _ = wait(
                list(metadata_futures.keys()),
                timeout=0.5,
                return_when=FIRST_COMPLETED,
            )
            if done:
                process_done_futures(done)

        _update_stage(
            scan,
            STAGE_METADATA,
            status="completed",
            processed=metadata_processed,
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
        _broadcast_scan_update(scan, ws_state, force=True)
    finally:
        for future in list(metadata_futures.keys()):
            future.cancel()
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)


@shared_task
def refresh_media_item_metadata(item_id: int):
    try:
        media_item = MediaItem.objects.select_related("library").get(id=item_id)
    except MediaItem.DoesNotExist:
        return
    updated = sync_metadata(media_item, force=True, allow_remote=True)
    current = updated or media_item
    if current.library.add_to_vod:
        try:
            sync_vod_for_media_item(current)
        except Exception:
            logger.exception("Failed to sync VOD for media item %s", current.id)


@shared_task
def refresh_library_metadata(library_id: int):
    items = MediaItem.objects.filter(library_id=library_id).select_related("library").iterator()
    for item in items:
        updated = sync_metadata(item, force=True, allow_remote=True)
        current = updated or item
        if current.library.add_to_vod:
            try:
                sync_vod_for_media_item(current)
            except Exception:
                logger.exception("Failed to sync VOD for media item %s", current.id)
