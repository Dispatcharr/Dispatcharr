import logging
from datetime import timedelta
from typing import Optional, Set
from collections import deque

from celery import shared_task, states
from celery.result import AsyncResult
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.media_library.metadata import sync_metadata
from apps.media_library.models import Library, LibraryScan, MediaFile, MediaItem
from apps.media_library import serializers
from apps.media_library.utils import (
    LibraryScanner,
    apply_probe_metadata,
    classify_media_file,
    probe_media_file,
    resolve_media_item,
)
from apps.media_library.transcode import ensure_browser_ready_source
from apps.media_library.vod_sync import (
    sync_library_to_vod,
    sync_media_item_to_vod,
    unsync_library_from_vod,
)

logger = logging.getLogger(__name__)

METADATA_TASK_QUEUE = getattr(settings, "CELERY_METADATA_QUEUE", None)
METADATA_TASK_PRIORITY = getattr(settings, "CELERY_METADATA_PRIORITY", None)
PROBE_TASK_QUEUE = getattr(settings, "CELERY_MEDIA_PROBE_QUEUE", None)
PROBE_TASK_PRIORITY = getattr(settings, "CELERY_MEDIA_PROBE_PRIORITY", None)
STALE_SCAN_THRESHOLD_SECONDS = getattr(settings, "MEDIA_LIBRARY_STALE_SCAN_THRESHOLD_SECONDS", 180)


def _start_next_scan(library: Library) -> None:
    if library.scans.filter(status=LibraryScan.STATUS_RUNNING).exists():
        return

    if library.scans.filter(status=LibraryScan.STATUS_PENDING, task_id__isnull=False).exists():
        return

    pending_scan = (
        library.scans.filter(
            status=LibraryScan.STATUS_PENDING,
            task_id__isnull=True,
        )
        .order_by("created_at")
        .first()
    )

    if not pending_scan:
        return

    extra = pending_scan.extra or {}
    force_full = bool(extra.get("force_full"))
    rescan_item_id = extra.get("rescan_item_id")

    async_result = scan_library_task.apply_async(
        kwargs={
            "scan_id": str(pending_scan.id),
            "library_id": pending_scan.library_id,
            "force_full": force_full,
            "rescan_item_id": rescan_item_id,
        }
    )
    pending_scan.task_id = async_result.id
    pending_scan.save(update_fields=["task_id", "updated_at"])


def resume_orphaned_scans(*, library_id: int | None = None) -> int:
    """
    Ensure scans that were marked as running but lost their worker (e.g. due to a restart)
    are re-queued so progress can continue.
    """
    qs = LibraryScan.objects.filter(status=LibraryScan.STATUS_RUNNING)
    if library_id is not None:
        qs = qs.filter(library_id=library_id)

    now = timezone.now()
    stale_before = now - timedelta(seconds=max(30, STALE_SCAN_THRESHOLD_SECONDS))
    resumed = 0

    for scan in qs.select_related("library"):
        should_resume = False
        task_state = None
        if scan.task_id:
            try:
                task_result = AsyncResult(scan.task_id)
                task_state = task_result.state
            except Exception as exc:  # noqa: BLE001
                logger.debug("Unable to inspect scan task %s: %s", scan.task_id, exc)
                task_state = None

        if not scan.task_id:
            should_resume = True
        elif task_state in states.READY_STATES or task_state in {states.RETRY, states.REVOKED}:
            should_resume = True
        elif scan.updated_at and scan.updated_at < stale_before:
            should_resume = True

        if scan.discovery_status == LibraryScan.STAGE_STATUS_COMPLETED:
            continue

        if not should_resume or not scan.library:
            continue

        logger.info(
            "Resuming interrupted library scan %s for library %s (task=%s state=%s)",
            scan.id,
            scan.library_id,
            scan.task_id,
            task_state,
        )

        summary_note = "Resuming after interruption."
        summary_text = scan.summary or ""
        if summary_note not in summary_text:
            if summary_text:
                summary_text = f"{summary_text.strip()}\n{summary_note}"
            else:
                summary_text = summary_note
        else:
            summary_text = summary_text.strip()

        scan.processed_files = 0
        scan.total_files = 0
        scan.new_files = 0
        scan.updated_files = 0
        scan.removed_files = 0
        scan.matched_items = 0
        scan.unmatched_files = 0
        scan.discovery_status = LibraryScan.STAGE_STATUS_PENDING
        scan.discovery_total = 0
        scan.discovery_processed = 0
        scan.metadata_status = LibraryScan.STAGE_STATUS_PENDING
        scan.metadata_total = 0
        scan.metadata_processed = 0
        scan.artwork_status = LibraryScan.STAGE_STATUS_PENDING
        scan.artwork_total = 0
        scan.artwork_processed = 0
        scan.status = LibraryScan.STATUS_PENDING
        scan.task_id = None
        scan.finished_at = None
        scan.summary = summary_text
        scan.updated_at = now
        scan.save(
            update_fields=[
                "processed_files",
                "total_files",
                "new_files",
                "updated_files",
                "removed_files",
                "matched_items",
                "unmatched_files",
                "discovery_status",
                "discovery_total",
                "discovery_processed",
                "metadata_status",
                "metadata_total",
                "metadata_processed",
                "artwork_status",
                "artwork_total",
                "artwork_processed",
                "status",
                "task_id",
                "finished_at",
                "summary",
                "updated_at",
            ]
        )

        _start_next_scan(scan.library)
        resumed += 1

    return resumed


def enqueue_library_scan(
    *,
    library_id: int,
    user_id: int | None = None,
    force_full: bool = False,
    rescan_item_id: int | None = None,
) -> LibraryScan:
    library = Library.objects.get(pk=library_id)
    scan = LibraryScan.objects.create(
        library=library,
        created_by_id=user_id,
        status=LibraryScan.STATUS_PENDING,
        extra={
            "force_full": force_full,
            "rescan_item_id": rescan_item_id,
        },
    )

    _start_next_scan(library)
    return scan


def _revoke_scan_task(task_id: str | None, *, terminate: bool = False) -> None:
    if not task_id:
        return
    try:
        AsyncResult(task_id).revoke(terminate=terminate)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to revoke scan task %s: %s", task_id, exc)


def start_next_library_scan(library: Library) -> None:
    """Public helper for kicking off the next pending scan."""

    _start_next_scan(library)


def revoke_scan_task(task_id: str | None, *, terminate: bool = False) -> None:
    """Public helper to revoke a Celery scan task safely."""

    _revoke_scan_task(task_id, terminate=terminate)


def cancel_library_scan(scan: LibraryScan, *, summary: str | None = None) -> LibraryScan:
    """Cancel a running or pending library scan."""

    if scan.status not in {LibraryScan.STATUS_RUNNING, LibraryScan.STATUS_PENDING}:
        raise ValueError("Only running or pending scans can be cancelled")

    library = scan.library
    terminate = scan.status == LibraryScan.STATUS_RUNNING
    _revoke_scan_task(scan.task_id, terminate=terminate)

    now = timezone.now()
    scan.status = LibraryScan.STATUS_CANCELLED
    scan.finished_at = now
    update_fields = ["status", "finished_at", "updated_at"]

    if summary:
        scan.summary = summary
        update_fields.append("summary")
    elif not scan.summary:
        scan.summary = "Cancelled by user"
        update_fields.append("summary")

    if scan.task_id:
        scan.task_id = None
        update_fields.append("task_id")

    scan.save(update_fields=update_fields)

    _send_scan_event(
        {
            "status": "cancelled",
            "scan_id": str(scan.id),
            "library_id": scan.library_id,
            "library_name": library.name if library else "",
            "summary": scan.summary,
            "processed": scan.processed_files,
            "processed_files": scan.processed_files,
            "total": scan.total_files,
        }
    )

    _start_next_scan(library)
    scan.refresh_from_db()
    return scan


def _send_scan_event(event: dict) -> None:
    try:
        channel_layer = get_channel_layer()
    except Exception:  # noqa: BLE001
        return
    if not channel_layer:
        return
    payload = {"success": True, "type": "media_scan"}
    payload.update(event)
    async_to_sync(channel_layer.group_send)(
        "updates",
        {"type": "update", "data": payload},
    )


def _stage_snapshot(scan: LibraryScan) -> dict[str, dict[str, int | str]]:
    return scan.stage_snapshot(normalize=True)


def _emit_scan_update(scan: LibraryScan, *, status: str, extra: dict | None = None) -> None:
    library_name = ""
    if getattr(scan, "library", None):
        library_name = scan.library.name

    resolved_status = status
    if status != LibraryScan.STATUS_COMPLETED and scan.status == LibraryScan.STATUS_COMPLETED:
        resolved_status = LibraryScan.STATUS_COMPLETED

    payload = {
        "status": resolved_status,
        "scan_id": str(scan.id),
        "library_id": scan.library_id,
        "library_name": library_name,
        "processed": scan.processed_files,
        "processed_files": scan.processed_files,
        "total": scan.total_files,
        "matched": scan.matched_items,
        "unmatched": scan.unmatched_files,
        "new_files": scan.new_files,
        "updated_files": scan.updated_files,
        "removed_files": scan.removed_files,
        "stages": _stage_snapshot(scan),
    }
    if extra:
        payload.update(extra)
    logger.debug(
        "Scan %s update status=%s processed=%s/%s stages=%s",
        payload["scan_id"],
        status,
        payload.get("processed"),
        payload.get("total"),
        payload.get("stages"),
    )
    _send_scan_event(payload)


def _advance_metadata_stage(
    scan: LibraryScan,
    *,
    metadata_increment: int = 0,
    artwork_increment: int = 0,
) -> None:
    if not metadata_increment and not artwork_increment:
        return

    updated = False

    with transaction.atomic():
        locked = (
            LibraryScan.objects.select_for_update()
            .only(
                "metadata_status",
                "metadata_total",
                "metadata_processed",
                "artwork_status",
                "artwork_total",
                "artwork_processed",
            )
            .get(pk=scan.pk)
        )

        update_fields: list[str] = []
        now = timezone.now()

        if metadata_increment:
            current_processed = locked.metadata_processed or 0
            new_processed = current_processed + metadata_increment
            if locked.metadata_total:
                new_processed = min(new_processed, locked.metadata_total)

            if new_processed != current_processed:
                locked.metadata_processed = new_processed
                update_fields.append("metadata_processed")

            target_status = locked.metadata_status
            if target_status == LibraryScan.STAGE_STATUS_PENDING:
                target_status = LibraryScan.STAGE_STATUS_RUNNING
            if locked.metadata_total and new_processed >= locked.metadata_total:
                target_status = LibraryScan.STAGE_STATUS_COMPLETED

            if target_status != locked.metadata_status:
                locked.metadata_status = target_status
                update_fields.append("metadata_status")

        if artwork_increment:
            current_processed = locked.artwork_processed or 0
            new_processed = current_processed + artwork_increment
            if locked.artwork_total:
                new_processed = min(new_processed, locked.artwork_total)

            if new_processed != current_processed:
                locked.artwork_processed = new_processed
                update_fields.append("artwork_processed")

            target_status = locked.artwork_status
            if target_status == LibraryScan.STAGE_STATUS_PENDING:
                target_status = LibraryScan.STAGE_STATUS_RUNNING
            if locked.artwork_total and new_processed >= locked.artwork_total:
                target_status = LibraryScan.STAGE_STATUS_COMPLETED

            if target_status != locked.artwork_status:
                locked.artwork_status = target_status
                update_fields.append("artwork_status")

        if update_fields:
            locked.updated_at = now
            locked.save(update_fields=update_fields + ["updated_at"])
            updated = True

        # Sync original scan instance with locked values so future calls have fresh data.
        scan.metadata_status = locked.metadata_status
        scan.metadata_total = locked.metadata_total
        scan.metadata_processed = locked.metadata_processed or 0
        scan.artwork_status = locked.artwork_status
        scan.artwork_total = locked.artwork_total
        scan.artwork_processed = locked.artwork_processed or 0

    if updated:
        _emit_scan_update(scan, status="progress")
        _maybe_mark_scan_completed(scan)


def _maybe_mark_scan_completed(scan: LibraryScan) -> None:
    if scan.status == LibraryScan.STATUS_COMPLETED:
        return

    if (
        scan.metadata_total
        and scan.metadata_processed >= scan.metadata_total
        and scan.metadata_status not in (LibraryScan.STAGE_STATUS_COMPLETED, LibraryScan.STAGE_STATUS_SKIPPED)
    ):
        scan.record_stage_progress("metadata", status=LibraryScan.STAGE_STATUS_COMPLETED)
        scan.metadata_status = LibraryScan.STAGE_STATUS_COMPLETED

    if (
        scan.artwork_total
        and scan.artwork_processed >= scan.artwork_total
        and scan.artwork_status not in (LibraryScan.STAGE_STATUS_COMPLETED, LibraryScan.STAGE_STATUS_SKIPPED)
    ):
        scan.record_stage_progress("artwork", status=LibraryScan.STAGE_STATUS_COMPLETED)
        scan.artwork_status = LibraryScan.STAGE_STATUS_COMPLETED

    if scan._ensure_completed():
        _emit_scan_update(scan, status="completed")


def _send_media_item_update(media_item: MediaItem, *, status: str = "updated") -> None:
    try:
        channel_layer = get_channel_layer()
    except Exception:  # noqa: BLE001
        return
    if not channel_layer:
        return

    data = serializers.MediaItemListSerializer(media_item, context={"request": None}).data
    payload = {
        "type": "media_item_update",
        "status": status,
        "library_id": media_item.library_id,
        "media_item": data,
    }
    async_to_sync(channel_layer.group_send)(
        "updates",
        {"type": "update", "data": payload},
    )


@shared_task(bind=True, name="media_library.scan_library")
def scan_library_task(
    self,
    *,
    scan_id: str,
    library_id: int,
    force_full: bool = False,
    rescan_item_id: int | None = None,
):
    try:
        scan = LibraryScan.objects.select_related("library").get(pk=scan_id)
    except LibraryScan.DoesNotExist:
        logger.warning("LibraryScan %s not found", scan_id)
        return

    scan.mark_running(task_id=self.request.id if self.request else None)
    library = scan.library
    logger.info("Starting scan for library %s (id=%s)", library.name, library.id)
    processed = 0
    total_files = 0
    matched = 0
    unmatched = 0
    media_item_ids: Set[int] = set()
    metadata_queue_ids: Set[int] = set()
    metadata_accounted_ids: Set[int] = set()
    pending_probe_ids: set[int] = set()
    probes_scheduled = False
    metadata_total_count = scan.metadata_total or 0
    metadata_processed_count = scan.metadata_processed or 0
    artwork_total_count = scan.artwork_total or 0
    artwork_processed_count = scan.artwork_processed or 0
    last_progress_emit = timezone.now()
    progress_interval = 0.4  # seconds

    initial_total_estimate = (
        MediaFile.objects.filter(library=library).count()
    )
    discovery_total_estimate = initial_total_estimate or 0

    scan.record_progress(
        processed=0,
        matched=0,
        unmatched=0,
        total=discovery_total_estimate,
    )
    scan.record_stage_progress(
        "discovery",
        status=LibraryScan.STAGE_STATUS_RUNNING,
        total=discovery_total_estimate,
        processed=0,
    )
    scan.record_stage_progress(
        "metadata",
        status=LibraryScan.STAGE_STATUS_PENDING,
        total=0,
        processed=0,
    )
    scan.record_stage_progress(
        "artwork",
        status=LibraryScan.STAGE_STATUS_PENDING,
        total=0,
        processed=0,
    )
    scan.total_files = max(scan.total_files, discovery_total_estimate)
    _emit_scan_update(
        scan,
        status="started",
    )

    try:
        scanner = LibraryScanner(
            library=library,
            scan=scan,
            force_full=force_full,
            rescan_item_id=rescan_item_id,
        )

        discovery_buffer: deque = deque()
        discovery_total_known = 0
        discovery_processed = 0
        discovery_finished = False
        total_files = discovery_total_estimate
        backlog_target = 25

        def maybe_emit_progress(force: bool = False, status: str = "progress") -> None:
            nonlocal last_progress_emit
            now = timezone.now()
            if (
                force
                or discovery_processed == 0
                or (now - last_progress_emit).total_seconds() >= progress_interval
            ):
                last_progress_emit = now
                _emit_scan_update(scan, status=status)

        def queue_metadata(item: MediaItem) -> bool:
            if item.id in metadata_queue_ids:
                return False
            metadata_queue_ids.add(item.id)
            args = (item.id,)
            kwargs = {"scan_id": str(scan.id)}
            options = {}
            if METADATA_TASK_QUEUE:
                options["queue"] = METADATA_TASK_QUEUE
            if METADATA_TASK_PRIORITY is not None:
                options["priority"] = METADATA_TASK_PRIORITY
            sync_metadata_task.apply_async(args=args, kwargs=kwargs, **options)
            return True

        def enqueue_probe_tasks() -> None:
            nonlocal probes_scheduled
            if probes_scheduled:
                return
            if not pending_probe_ids:
                probes_scheduled = True
                return
            options = {}
            if PROBE_TASK_QUEUE:
                options["queue"] = PROBE_TASK_QUEUE
            if PROBE_TASK_PRIORITY is not None:
                options["priority"] = PROBE_TASK_PRIORITY
            for file_id in sorted(pending_probe_ids):
                probe_media_task.apply_async(args=(file_id,), **options)
            probes_scheduled = True
            pending_probe_ids.clear()

        def refresh_stage_counters() -> None:
            nonlocal metadata_total_count, metadata_processed_count, artwork_total_count, artwork_processed_count, total_files
            progress_cap = max(scan.total_files, discovery_total_estimate, total_files)
            snapshot = (
                LibraryScan.objects.filter(pk=scan.pk)
                .values(
                    "metadata_total",
                    "metadata_processed",
                    "artwork_total",
                    "artwork_processed",
                    "metadata_status",
                    "artwork_status",
                )
                .first()
            )
            if not snapshot:
                return

            metadata_snapshot_total = snapshot.get("metadata_total") or 0
            artwork_snapshot_total = snapshot.get("artwork_total") or 0

            metadata_total_count = min(
                progress_cap, max(metadata_total_count, metadata_snapshot_total)
            )
            metadata_processed_count = max(
                metadata_processed_count,
                min(progress_cap, snapshot.get("metadata_processed") or 0),
            )
            artwork_total_count = min(
                progress_cap, max(artwork_total_count, artwork_snapshot_total)
            )
            artwork_processed_count = max(
                artwork_processed_count,
                min(progress_cap, snapshot.get("artwork_processed") or 0),
            )

            scan.metadata_total = metadata_total_count
            scan.metadata_processed = metadata_processed_count
            scan.artwork_total = artwork_total_count
            scan.artwork_processed = artwork_processed_count
            metadata_status = snapshot.get("metadata_status")
            artwork_status = snapshot.get("artwork_status")
            if metadata_status:
                scan.metadata_status = metadata_status
            if artwork_status:
                scan.artwork_status = artwork_status

        def register_metadata_item(item: MediaItem | None, needs_metadata: bool) -> None:
            nonlocal metadata_total_count, metadata_processed_count, artwork_total_count, artwork_processed_count
            if not item or not item.id or item.id in metadata_accounted_ids:
                return
            metadata_accounted_ids.add(item.id)

            refresh_stage_counters()

            progress_cap = max(scan.total_files, discovery_total_estimate, total_files)

            metadata_total_count = min(
                progress_cap, max(metadata_total_count, scan.metadata_total or 0) + 1
            )
            metadata_processed_count = min(
                progress_cap, max(metadata_processed_count, scan.metadata_processed or 0)
            )
            artwork_total_count = min(
                progress_cap, max(artwork_total_count, scan.artwork_total or 0) + 1
            )
            artwork_processed_count = min(
                progress_cap, max(artwork_processed_count, scan.artwork_processed or 0)
            )

            if scan.metadata_status != LibraryScan.STAGE_STATUS_RUNNING:
                scan.record_stage_progress("metadata", status=LibraryScan.STAGE_STATUS_RUNNING)

            if needs_metadata:
                scan.record_stage_progress("metadata", total=metadata_total_count)
                queued = queue_metadata(item)
                if queued:
                    maybe_emit_progress(force=True)
            else:
                metadata_processed_count += 1
                scan.record_stage_progress(
                    "metadata",
                    total=metadata_total_count,
                    processed=metadata_processed_count,
                )

            if scan.artwork_status != LibraryScan.STAGE_STATUS_RUNNING:
                scan.record_stage_progress("artwork", status=LibraryScan.STAGE_STATUS_RUNNING)

            if needs_metadata or not item.poster_url:
                scan.record_stage_progress("artwork", total=artwork_total_count)
            else:
                artwork_processed_count += 1
                scan.record_stage_progress(
                    "artwork",
                    total=artwork_total_count,
                    processed=artwork_processed_count,
                )

            maybe_emit_progress()

        discovery_iter = scanner.discover_files_iter()

        def fill_discovery_buffer() -> None:
            nonlocal discovery_total_known, discovery_finished, total_files
            while not discovery_finished and len(discovery_buffer) < backlog_target:
                try:
                    result = next(discovery_iter)
                except StopIteration:
                    discovery_finished = True
                    break
                discovery_buffer.append(result)
                discovery_total_known += 1
                current_total = max(discovery_total_estimate, discovery_total_known)
                scan.total_files = max(scan.total_files, current_total)
                scan.record_stage_progress(
                    "discovery",
                    status=LibraryScan.STAGE_STATUS_RUNNING,
                    total=current_total,
                )
                total_files = max(total_files, current_total)
                scan.record_progress(total=current_total)
                maybe_emit_progress()

        def process_discovery_result(result) -> None:
            nonlocal discovery_processed, matched, unmatched, processed, total_files
            discovery_processed += 1
            identify_result = _identify_media_file(
                library=library,
                file_id=result.file_id,
                target_item_id=scanner.target_item.id if scanner.target_item else None,
            )
            matched += identify_result.get("matched", 0)
            unmatched += identify_result.get("unmatched", 0)
            media_id = identify_result.get("media_item_id")
            parent_media_id = identify_result.get("parent_media_item_id")
            candidate_ids = {
                candidate_id
                for candidate_id in (media_id, parent_media_id)
                if candidate_id
            }
            for candidate_id in candidate_ids:
                is_new_media = candidate_id not in media_item_ids
                media_item_ids.add(candidate_id)
                try:
                    media_obj = MediaItem.objects.select_related("library").get(pk=candidate_id)
                except MediaItem.DoesNotExist:
                    continue
                else:
                    if is_new_media:
                        _send_media_item_update(media_obj, status="progress")
                    needs_metadata = (
                        force_full
                        or media_obj.metadata_last_synced_at is None
                        or not media_obj.poster_url
                    )
                    register_metadata_item(media_obj, needs_metadata)

            if result.requires_probe:
                pending_probe_ids.add(result.file_id)

            processed = discovery_processed
            scan.record_stage_progress("discovery", processed=discovery_processed)
            current_total = max(discovery_total_estimate, discovery_total_known)
            total_files = max(total_files, current_total)
            scan.record_progress(
                processed=processed,
                matched=matched,
                unmatched=unmatched,
                total=current_total,
            )
            maybe_emit_progress()

        fill_discovery_buffer()
        while discovery_buffer:
            result = discovery_buffer.popleft()
            process_discovery_result(result)
            if len(discovery_buffer) < max(1, backlog_target // 2):
                fill_discovery_buffer()

        while not discovery_finished:
            fill_discovery_buffer()
            while discovery_buffer:
                process_discovery_result(discovery_buffer.popleft())

        scanner.mark_missing_files()

        if media_item_ids:
            metadata_qs = (
                MediaItem.objects.filter(pk__in=media_item_ids)
                .filter(
                    Q(metadata_last_synced_at__isnull=True)
                    | Q(poster_url__isnull=True)
                    | Q(poster_url="")
                )
            )
            for item in metadata_qs:
                queue_metadata(item)

        enqueue_probe_tasks()

        scan.total_files = max(scan.total_files, discovery_processed)
        scan.record_stage_progress(
            "discovery",
            status=LibraryScan.STAGE_STATUS_COMPLETED,
            processed=discovery_processed,
            total=max(discovery_total_estimate, discovery_total_known),
        )
        _emit_scan_update(
            scan,
            status="discovered",
            extra={"files": max(discovery_total_estimate, discovery_total_known)},
        )

        summary = (
            f"Processed {scan.total_files} files; "
            f"new={scan.new_files}, updated={scan.updated_files}, "
            f"removed={scan.removed_files}, matched={matched}, "
            f"unmatched={unmatched}"
        )

        if not metadata_queue_ids:
            if metadata_total_count == 0:
                scan.record_stage_progress(
                    "metadata",
                    status=LibraryScan.STAGE_STATUS_SKIPPED,
                    total=0,
                    processed=0,
                )
                scan.record_stage_progress(
                    "artwork",
                    status=LibraryScan.STAGE_STATUS_SKIPPED,
                    total=0,
                    processed=0,
                )
            else:
                scan.record_stage_progress("metadata", status=LibraryScan.STAGE_STATUS_COMPLETED)
                scan.record_stage_progress("artwork", status=LibraryScan.STAGE_STATUS_COMPLETED)
        else:
            if scan.metadata_status == LibraryScan.STAGE_STATUS_PENDING:
                scan.record_stage_progress(
                    "metadata",
                    status=LibraryScan.STAGE_STATUS_RUNNING,
                )
            if scan.artwork_status == LibraryScan.STAGE_STATUS_PENDING:
                scan.record_stage_progress(
                    "artwork",
                    status=LibraryScan.STAGE_STATUS_RUNNING,
                )

        scanner.finalize(matched=matched, unmatched=unmatched, summary=summary)
        logger.info("Completed scan stage for library %s", library.name)

        metadata_done = scan.metadata_status in (
            LibraryScan.STAGE_STATUS_COMPLETED,
            LibraryScan.STAGE_STATUS_SKIPPED,
        )
        artwork_done = scan.artwork_status in (
            LibraryScan.STAGE_STATUS_COMPLETED,
            LibraryScan.STAGE_STATUS_SKIPPED,
        )

        if metadata_done and artwork_done:
            _maybe_mark_scan_completed(scan)
        else:
            scan.status = LibraryScan.STATUS_RUNNING
            scan.finished_at = None
            scan.save(update_fields=["status", "finished_at", "updated_at"])
            _emit_scan_update(
                scan,
                status="progress",
                extra={
                    "summary": summary,
                    "matched": matched,
                    "unmatched": unmatched,
                    "new_files": scan.new_files,
                    "updated_files": scan.updated_files,
                    "removed_files": scan.removed_files,
                },
            )
        _start_next_scan(library)
    except Exception as exc:  # noqa: BLE001
        enqueue_probe_tasks()
        logger.exception("Library scan failed for %s", library.name)
        scan.record_progress(
            processed=processed,
            matched=matched,
            unmatched=unmatched,
            total=max(total_files, discovery_total_estimate, discovery_total_known, processed),
            summary=str(exc),
        )
        scan.mark_failed(summary=str(exc))
        _emit_scan_update(
            scan,
            status="failed",
            extra={
                "success": False,
                "message": str(exc),
                "processed": processed,
                "processed_files": processed,
                "total": max(
                    total_files,
                    discovery_total_estimate,
                    discovery_total_known,
                    processed,
                ),
            },
        )
        _start_next_scan(library)
        raise


def _discover_media(scan: LibraryScan, scanner: LibraryScanner):
    return list(scanner.discover_files_iter())


@shared_task(name="media_library.discover_media")
def discover_media_task(scan_id: str) -> list[dict]:
    scan = LibraryScan.objects.select_related("library").get(pk=scan_id)
    scanner = LibraryScanner(scan.library, scan, force_full=False)
    discoveries = _discover_media(scan, scanner)
    return [{"file_id": d.file_id, "requires_probe": d.requires_probe} for d in discoveries]


def _identify_media_file(
    *,
    library: Library,
    file_id: int,
    target_item_id: Optional[int] = None,
) -> dict:
    try:
        file_record = MediaFile.objects.select_related("library", "media_item").get(
            pk=file_id, library=library
        )
    except MediaFile.DoesNotExist:
        return {"matched": 0, "unmatched": 0}

    classification = classify_media_file(file_record.file_name)
    if library.library_type == Library.LIBRARY_TYPE_MOVIES:
        classification.detected_type = MediaItem.TYPE_MOVIE
    elif library.library_type == Library.LIBRARY_TYPE_SHOWS:
        if classification.detected_type == MediaItem.TYPE_MOVIE:
            classification.detected_type = MediaItem.TYPE_SHOW
    # mixed/other retain detected type
    target_item = None
    if target_item_id:
        target_item = MediaItem.objects.filter(pk=target_item_id, library=library).first()

    media_item = resolve_media_item(library, classification, target_item=target_item)
    matched = 0
    unmatched = 0
    if media_item:
        if file_record.media_item_id != media_item.id:
            file_record.media_item = media_item
            file_record.save(update_fields=["media_item", "updated_at"])
        if classification.detected_type == MediaItem.TYPE_OTHER:
            if media_item.status != MediaItem.STATUS_FAILED:
                media_item.status = MediaItem.STATUS_FAILED
                media_item.save(update_fields=["status", "updated_at"])
            unmatched = 1
        else:
            if media_item.status != MediaItem.STATUS_MATCHED:
                media_item.status = MediaItem.STATUS_MATCHED
                media_item.save(update_fields=["status", "updated_at"])
            if (
                classification.detected_type == MediaItem.TYPE_EPISODE
                and media_item.parent_id
            ):
                parent = MediaItem.objects.filter(pk=media_item.parent_id).first()
                if parent:
                    if parent.status != MediaItem.STATUS_MATCHED:
                        parent.status = MediaItem.STATUS_MATCHED
                        parent.save(update_fields=["status", "updated_at"])
                    if not parent.metadata_last_synced_at or not parent.poster_url:
                        sync_metadata_task.delay(parent.id)
            matched = 1

        # Synchronize to VOD catalog when configured.
        sync_media_item_to_vod(media_item)
    else:
        unmatched = 1

    return {
        "file_id": file_id,
        "media_item_id": media_item.id if media_item else None,
        "parent_media_item_id": media_item.parent_id if media_item else None,
        "matched": matched,
        "unmatched": unmatched,
    }


@shared_task(name="media_library.identify_media")
def identify_media_task(library_id: int, file_id: int, target_item_id: Optional[int] = None):
    library = Library.objects.get(pk=library_id)
    return _identify_media_file(
        library=library, file_id=file_id, target_item_id=target_item_id
    )


def _probe_media_file(*, file_id: int) -> None:
    try:
        file_record = MediaFile.objects.get(pk=file_id)
    except MediaFile.DoesNotExist:
        return

    probe_data = probe_media_file(file_record.absolute_path)
    apply_probe_metadata(file_record, probe_data)

    checksum = file_record.calculate_checksum()
    if checksum and checksum != file_record.checksum:
        file_record.checksum = checksum
        file_record.save(update_fields=["checksum", "updated_at"])

    if file_record.requires_transcode and (
        file_record.transcode_status
        in (
            MediaFile.TRANSCODE_STATUS_PENDING,
            MediaFile.TRANSCODE_STATUS_FAILED,
        )
        or not file_record.transcoded_path
    ):
        transcode_media_file_task.delay(file_record.id)


@shared_task(name="media_library.probe_media")
def probe_media_task(file_id: int):
    _probe_media_file(file_id=file_id)


def _sync_metadata(media_item_id: int, scan_id: str | None = None) -> None:
    try:
        media_item = MediaItem.objects.get(pk=media_item_id)
    except MediaItem.DoesNotExist:
        return
    scan: LibraryScan | None = None
    if scan_id:
        try:
            scan = LibraryScan.objects.select_related("library").get(pk=scan_id)
        except LibraryScan.DoesNotExist:
            scan = None

    result = sync_metadata(media_item)
    if result:
        _send_media_item_update(result, status="metadata")

    if not scan:
        return

    metadata_increment = 1 if scan.metadata_total else 0
    artwork_increment = 1 if scan.artwork_total else 0

    if scan.metadata_status == LibraryScan.STAGE_STATUS_PENDING and scan.metadata_total:
        scan.record_stage_progress("metadata", status=LibraryScan.STAGE_STATUS_RUNNING)
    if scan.artwork_status == LibraryScan.STAGE_STATUS_PENDING and scan.artwork_total:
        scan.record_stage_progress("artwork", status=LibraryScan.STAGE_STATUS_RUNNING)

    progressed = False
    if metadata_increment or artwork_increment:
        _advance_metadata_stage(
            scan,
            metadata_increment=metadata_increment,
            artwork_increment=artwork_increment,
        )
        progressed = True

    if scan:
        if progressed:
            try:
                scan.refresh_from_db(
                    fields=[
                        "metadata_status",
                        "metadata_total",
                        "metadata_processed",
                        "artwork_status",
                        "artwork_total",
                        "artwork_processed",
                        "status",
                        "finished_at",
                        "updated_at",
                    ]
                )
            except LibraryScan.DoesNotExist:
                scan = None
        if scan:
            _maybe_mark_scan_completed(scan)


@shared_task(name="media_library.sync_metadata")
def sync_metadata_task(media_item_id: int, scan_id: str | None = None):
    _sync_metadata(media_item_id, scan_id=scan_id)


@shared_task(name="media_library.cleanup_missing")
def cleanup_missing_task(library_id: int):
    library = Library.objects.get(pk=library_id)
    dummy_scan = LibraryScan(
        library=library,
        status=LibraryScan.STATUS_RUNNING,
    )
    scanner = LibraryScanner(library=library, scan=dummy_scan)
    return scanner.mark_missing_files()


@shared_task(name="media_library.prune_stale_scans")
def prune_stale_scans(max_age_hours: int = 72):
    threshold = timezone.now() - timedelta(hours=max_age_hours)
    deleted, _ = LibraryScan.objects.filter(
        status__in=[LibraryScan.STATUS_COMPLETED, LibraryScan.STATUS_FAILED],
        created_at__lt=threshold,
    ).delete()
    if deleted:
        logger.info("Pruned %s stale library scan records", deleted)


@shared_task(name="media_library.transcode_media_file")
def transcode_media_file_task(file_id: int, force: bool = False):
    try:
        media_file = MediaFile.objects.get(pk=file_id)
    except MediaFile.DoesNotExist:
        logger.warning("Media file %s not found for transcoding", file_id)
        return

    try:
        ensure_browser_ready_source(media_file, force=force)
    except FileNotFoundError:
        logger.warning("Source file missing for media file %s", file_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Transcode failed for media file %s: %s", file_id, exc)
        raise


@shared_task(name="media_library.schedule_auto_scans")
def schedule_auto_scans():
    now = timezone.now()
    for library in Library.objects.filter(auto_scan_enabled=True):
        if not library.last_scan_at:
            enqueue_library_scan(library_id=library.id, user_id=None)
            continue
        next_scan_due = library.last_scan_at + timedelta(minutes=library.scan_interval_minutes)
        if next_scan_due <= now:
            enqueue_library_scan(library_id=library.id, user_id=None)


@shared_task(name="media_library.sync_library_vod")
def sync_library_to_vod_task(library_id: int):
    try:
        library = Library.objects.get(pk=library_id)
    except Library.DoesNotExist:
        return
    sync_library_to_vod(library)


@shared_task(name="media_library.unsync_library_vod")
def unsync_library_from_vod_task(library_id: int):
    try:
        library = Library.objects.get(pk=library_id)
    except Library.DoesNotExist:
        return
    unsync_library_from_vod(library)


def refresh_metadata_for_item(media_item_id: int, user_id: int | None = None):
    logger.debug("Metadata refresh requested for media_item=%s by user=%s", media_item_id, user_id)
    sync_metadata_task.delay(media_item_id)
