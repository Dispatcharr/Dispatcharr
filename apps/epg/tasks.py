# apps/epg/tasks.py

import logging
import gzip
import html.entities
import os
import uuid
import requests
import time  # Add import for tracking download progress
from datetime import datetime, timedelta, timezone as dt_timezone
import gc  # Add garbage collection module
import json
import re
from lxml import etree  # Using lxml exclusively
import psutil  # Add import for memory tracking
import zipfile

from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from apps.channels.models import Channel
from core.models import UserAgent, CoreSettings

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import EPGSource, EPGSourceIndex, EPGData, ProgramData, SDScheduleMD5, SDProgramMD5
from core.utils import (
    acquire_task_lock,
    is_task_lock_held,
    release_task_lock,
    TaskLockRenewer,
    send_websocket_update,
    cleanup_memory,
    log_system_event,
)

logger = logging.getLogger(__name__)

_NON_TERMINAL_REFRESH_STATUSES = frozenset({
    EPGSource.STATUS_FETCHING,
    EPGSource.STATUS_PARSING,
})


def _release_task_db_connection():
    """Return the Celery worker's DB connection to a clean state after ORM errors."""
    from django.db import close_old_connections
    close_old_connections()


def _db_query_with_retry(fn, *, label="DB query", max_retries=2):
    """
    Run an ORM read with one connection reset + retry on transient failures.

    Poisoned Celery worker connections often surface as OperationalError or as
    ``IndexError: list index out of range`` inside Django's row converters.
    """
    from django.db import InterfaceError, OperationalError

    transient_errors = (OperationalError, InterfaceError, IndexError)
    for attempt in range(max_retries):
        try:
            return fn()
        except transient_errors as exc:
            if attempt + 1 >= max_retries:
                raise
            logger.warning(
                "%s failed (%s), resetting DB connection (%s/%s)",
                label,
                exc,
                attempt + 1,
                max_retries,
            )
            _release_task_db_connection()


def _get_epg_source(source_id):
    return _db_query_with_retry(
        lambda: EPGSource.objects.get(id=source_id),
        label=f"load EPG source {source_id}",
    )


def _set_epg_source_status(
    source_id,
    status,
    last_message=None,
    *,
    notify_error=False,
    ws_action="refresh",
    ws_error=None,
):
    """Update source status using a fresh connection (safe after DB failures)."""
    _release_task_db_connection()
    update = {"status": status}
    if last_message is not None:
        update["last_message"] = last_message
    try:
        EPGSource.objects.filter(id=source_id).update(**update)
        if notify_error:
            send_epg_update(
                source_id,
                ws_action,
                100,
                status="error",
                error=ws_error or last_message,
            )
    except Exception as e:
        logger.error(
            f"Failed to set EPG source {source_id} status to {status}: {e}"
        )


def _ensure_epg_refresh_terminal_status(source_id):
    """Mark refresh as failed when the task exits while still in progress."""
    _release_task_db_connection()
    try:
        current_status = (
            EPGSource.objects.filter(id=source_id)
            .values_list("status", flat=True)
            .first()
        )
        if current_status in _NON_TERMINAL_REFRESH_STATUSES:
            message = "Refresh did not complete successfully"
            EPGSource.objects.filter(id=source_id).update(
                status=EPGSource.STATUS_ERROR,
                last_message=message,
            )
            send_epg_update(
                source_id, "refresh", 100, status="error", error=message
            )
    except Exception as e:
        logger.debug(
            f"Could not verify terminal refresh status for EPG source {source_id}: {e}"
        )


SD_BASE_URL = 'https://json.schedulesdirect.org/20141201'
SD_DAYS_TO_FETCH = 20
SD_PROGRAM_BATCH_SIZE = 5000
SD_BULK_GUIDE_FETCH_THRESHOLD = 3
SD_MAPPED_GUIDE_BATCH_DEFER_SECONDS = 90
SD_MAPPED_GUIDE_FETCH_DEFER_MAX_RETRIES = 2

def _sd_compute_schedule_changes_from_md5(server_md5s, cached_md5s, date_list):
    """Return station_id -> [date_str] for dates whose schedule MD5 differs from cache."""
    changed_by_station = {}
    for (sid, date_str), server_info in server_md5s.items():
        if date_str not in date_list:
            continue
        cached = cached_md5s.get((sid, date_str))
        if cached != server_info['md5']:
            changed_by_station.setdefault(sid, []).append(date_str)
    return changed_by_station


def _sd_backfill_schedule_dates_without_data(
    changed_by_station,
    server_md5s,
    date_list,
    mapped_station_ids,
    epg_id_map,
    dates_with_data,
    cached_md5s,
    stations_without_any_data,
):
    """
    Add fetch-window dates that lack ProgramData to changed_by_station.

    Dates with a cached schedule MD5 are treated as already fetched (e.g. legitimately
    empty airings). Stations with zero ProgramData still backfill all missing dates
    so stale cache from unmapped lineup refreshes cannot block guide population.
    """
    from datetime import date as date_type

    stations_without_any_data = set(stations_without_any_data)
    backfilled_count = 0
    for sid in mapped_station_ids:
        epg_db_id = epg_id_map.get(sid)
        if not epg_db_id:
            continue
        force_despite_cache = sid in stations_without_any_data
        already_changing = set(changed_by_station.get(sid, []))
        for ds in date_list:
            if ds in already_changing or (sid, ds) not in server_md5s:
                continue
            if (epg_db_id, date_type.fromisoformat(ds)) in dates_with_data:
                continue
            if (sid, ds) in cached_md5s and not force_despite_cache:
                continue
            changed_by_station.setdefault(sid, []).append(ds)
            backfilled_count += 1
    return backfilled_count


def _sd_programs_needing_metadata(
    program_ids_needed,
    schedule_program_md5s,
    cached_prog_md5s,
    programs_with_data,
):
    """Return programIDs that need metadata download from Schedules Direct."""
    programs_with_data = set(programs_with_data)
    return {
        pid for pid in program_ids_needed
        if schedule_program_md5s.get(pid) != cached_prog_md5s.get(pid)
        or pid not in programs_with_data
    }


SD_POSTER_CATEGORIES = (
    'Iconic', 'Banner-L1', 'Banner-L2', 'Banner-L3', 'Banner',
    'Staple', 'Poster Art', 'Box Art',
)

SD_POSTER_STYLE_CONFIG = {
    'portrait_iconic': {
        'aspect_groups': (('2x3', '3x4'),),
        'categories': ('Iconic',),
    },
    'portrait_banner': {
        'aspect_groups': (('2x3', '3x4'),),
        'categories': ('Banner-L1', 'Banner-L2', 'Banner-L3', 'Banner'),
    },
    'landscape_iconic': {
        'aspect_groups': (('16x9', '4x3'),),
        'categories': ('Iconic',),
    },
    'landscape_banner': {
        'aspect_groups': (('16x9', '4x3'),),
        'categories': ('Banner-L1', 'Banner-L2', 'Banner-L3', 'Banner'),
    },
    'square_iconic': {
        'aspect_groups': (('1x1',),),
        'categories': ('Iconic',),
    },
}


def _sd_image_width(img):
    try:
        return int(img.get('width') or 0)
    except (TypeError, ValueError):
        return 0


def _sd_is_primary(img):
    val = img.get('primary')
    if val is True:
        return True
    if isinstance(val, str):
        return val.lower() in ('true', '1', 'yes')
    return False


def _sd_matching_images(images, *, categories=None, aspects=None, min_width=0, primary_only=False):
    matches = []
    for img in images:
        if not isinstance(img, dict):
            continue
        if primary_only and not _sd_is_primary(img):
            continue
        if categories is not None and img.get('category') not in categories:
            continue
        if aspects is not None and img.get('aspect') not in aspects:
            continue
        if _sd_image_width(img) < min_width:
            continue
        if img.get('uri'):
            matches.append(img)
    return matches


def _sd_best_image(matches):
    if not matches:
        return None
    best = max(matches, key=lambda img: (_sd_is_primary(img), _sd_image_width(img)))
    return best.get('uri')


def _sd_find_image(images, *, categories=None, aspects=None, min_width=0, primary_only=False):
    return _sd_best_image(_sd_matching_images(
        images,
        categories=categories,
        aspects=aspects,
        min_width=min_width,
        primary_only=primary_only,
    ))


SD_POSTER_STYLE_DEFAULT = 'sd_recommended'
SD_POSTER_PORTRAIT_FALLBACK = 'portrait_iconic'


def _sd_pick_recommended_poster_url(images):
    """Use Gracenote's primary flag, then fall back to portrait iconic."""
    min_widths = (240, 135, 120, 0)
    for min_w in min_widths:
        uri = _sd_find_image(
            images,
            categories=SD_POSTER_CATEGORIES,
            aspects=None,
            min_width=min_w,
            primary_only=True,
        )
        if uri:
            return uri
    for min_w in min_widths:
        uri = _sd_find_image(
            images,
            categories=None,
            aspects=None,
            min_width=min_w,
            primary_only=True,
        )
        if uri:
            return uri
    return _sd_pick_poster_url(images, SD_POSTER_PORTRAIT_FALLBACK)


def _sd_pick_poster_url(images, poster_style=SD_POSTER_STYLE_DEFAULT):
    """Pick the best SD poster URI for the user's style preference, with fallbacks."""
    if poster_style == 'sd_recommended':
        return _sd_pick_recommended_poster_url(images)

    config = SD_POSTER_STYLE_CONFIG.get(poster_style)
    if not config:
        return _sd_pick_recommended_poster_url(images)
    min_widths = (240, 135, 120, 0)

    for min_w in min_widths:
        for cat in config['categories']:
            for aspects in config['aspect_groups']:
                uri = _sd_find_image(images, categories=(cat,), aspects=aspects, min_width=min_w)
                if uri:
                    return uri

    for min_w in min_widths:
        for aspects in config['aspect_groups']:
            uri = _sd_find_image(images, categories=SD_POSTER_CATEGORIES, aspects=aspects, min_width=min_w)
            if uri:
                return uri

    for aspects in config['aspect_groups']:
        uri = _sd_find_image(images, categories=None, aspects=aspects, min_width=0)
        if uri:
            return uri

    # Fallback: SD primary among poster categories (any aspect)
    for min_w in min_widths:
        uri = _sd_find_image(
            images,
            categories=SD_POSTER_CATEGORIES,
            aspects=None,
            min_width=min_w,
            primary_only=True,
        )
        if uri:
            return uri

    if poster_style != SD_POSTER_PORTRAIT_FALLBACK:
        return _sd_pick_poster_url(images, SD_POSTER_PORTRAIT_FALLBACK)

    return None

# DOCTYPE internal subset for XMLTV files.  Declares all 252 HTML 4 named
# entities so lxml/libxml2 can resolve references like &eacute; correctly
# instead of silently dropping them in recovery mode.
# The 5 XML-predefined entities (amp, lt, gt, quot, apos) are always
# recognised by the XML spec and must not be redeclared.
_XML_ENTITIES = frozenset({'amp', 'lt', 'gt', 'quot', 'apos'})


def _build_html_entity_doctype() -> bytes:
    """Build a DOCTYPE internal subset declaring all HTML 4 named entities."""
    lines = [b'<!DOCTYPE tv [\n']
    for name, codepoint in sorted(html.entities.name2codepoint.items()):
        if name not in _XML_ENTITIES:
            # Numeric character references are always valid XML regardless of codepoint.
            lines.append(f'<!ENTITY {name} "&#x{codepoint:X};">\n'.encode('ascii'))
    lines.append(b']>\n')
    return b''.join(lines)


_HTML_ENTITY_DOCTYPE = _build_html_entity_doctype()


def _parse_programme_element(element_bytes):
    """Parse a single <programme> element, prepending the HTML-entity DOCTYPE
    so references like &eacute; in the text resolve instead of failing."""
    parser = etree.XMLParser(resolve_entities=True, load_dtd=True, no_network=True)
    return etree.fromstring(_HTML_ENTITY_DOCTYPE + element_bytes, parser)


class _PrependStream:
    """Wraps an open binary file and prepends a bytes prefix to its content.

    Used by _open_xmltv_file to inject a DOCTYPE entity block before the
    file content reaches lxml's iterparse, with zero disk I/O.
    """

    __slots__ = ('_prefix', '_prefix_pos', '_file')

    def __init__(self, prefix: bytes, file_obj):
        self._prefix = prefix
        self._prefix_pos = 0
        self._file = file_obj

    def read(self, size=-1):
        prefix_len = len(self._prefix)
        if self._prefix_pos >= prefix_len:
            return self._file.read(size)
        remaining = prefix_len - self._prefix_pos
        if size < 0:
            chunk = self._prefix[self._prefix_pos:] + self._file.read()
            self._prefix_pos = prefix_len
            return chunk
        if size <= remaining:
            chunk = self._prefix[self._prefix_pos:self._prefix_pos + size]
            self._prefix_pos += size
            return chunk
        chunk = self._prefix[self._prefix_pos:]
        self._prefix_pos = prefix_len
        return chunk + self._file.read(size - remaining)

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _open_xmltv_file(file_path: str):
    """Open an XMLTV file for lxml iterparse, injecting an HTML entity DOCTYPE.

    Prepends a <!DOCTYPE tv [...]> block that declares all 252 HTML 4 named
    entities so lxml/libxml2 resolves references like &eacute; correctly
    instead of silently dropping them in recovery mode.  This involves zero
    disk I/O (the DOCTYPE is streamed in-memory before the file content).

    If the file already contains a <!DOCTYPE> declaration the file is returned
    unchanged; a second DOCTYPE would be invalid XML.

    The caller is responsible for closing the returned object.
    """
    f = open(file_path, 'rb')
    start = f.read(512)

    # Do not inject if the file already declares a DOCTYPE.
    if b'<!DOCTYPE' in start or b'<!doctype' in start.lower():
        f.seek(0)
        return f

    # Insert the DOCTYPE after the XML declaration if one is present.
    xml_pos = start.find(b'<?xml')
    if xml_pos >= 0:
        decl_end = start.find(b'?>', xml_pos)
        if decl_end >= 0:
            xml_decl = start[:decl_end + 2]
            f.seek(decl_end + 2)
            return _PrependStream(xml_decl + b'\n' + _HTML_ENTITY_DOCTYPE, f)

    # No XML declaration found; insert DOCTYPE at the very start of the file.
    f.seek(0)
    return _PrependStream(_HTML_ENTITY_DOCTYPE, f)


def validate_icon_url_fast(icon_url, max_length=None):
    """
    Fast validation for icon URLs during parsing.
    Returns None if URL is too long, original URL otherwise.
    If max_length is None, gets it dynamically from the EPGData model field.
    """
    if max_length is None:
        # Get max_length dynamically from the model field
        max_length = EPGData._meta.get_field('icon_url').max_length

    if icon_url and len(icon_url) > max_length:
        logger.warning(f"Icon URL too long ({len(icon_url)} > {max_length}), skipping: {icon_url[:100]}...")
        return None
    return icon_url


MAX_EXTRACT_CHUNK_SIZE = 65536 # 64kb (base2)


def send_epg_update(source_id, action, progress, **kwargs):
    """Send WebSocket update about EPG download/parsing progress"""
    # Start with the base data dictionary
    data = {
        "progress": progress,
        "type": "epg_refresh",
        "source": source_id,
        "action": action,
    }

    # Add the additional key-value pairs from kwargs
    data.update(kwargs)

    # Use the standardized update function with garbage collection for program parsing
    # This is a high-frequency operation that needs more aggressive memory management
    collect_garbage = action == "parsing_programs" and progress % 10 == 0
    send_websocket_update('updates', 'update', data, collect_garbage=collect_garbage)

    # Explicitly clear references
    data = None

    # For high-frequency parsing, occasionally force additional garbage collection
    # to prevent memory buildup
    if action == "parsing_programs" and progress % 50 == 0:
        gc.collect()


def delete_epg_refresh_task_by_id(epg_id):
    """
    Delete the periodic task associated with an EPG source ID.
    Can be called directly or from the post_delete signal.
    Returns True if a task was found and deleted, False otherwise.
    """
    try:
        task = None
        task_name = f"epg_source-refresh-{epg_id}"

        # Look for task by name
        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule
            task = PeriodicTask.objects.get(name=task_name)
            logger.info(f"Found task by name: {task.id} for EPGSource {epg_id}")
        except PeriodicTask.DoesNotExist:
            logger.warning(f"No PeriodicTask found with name {task_name}")
            return False

        # Now delete the task and its interval
        if task:
            # Store interval info before deleting the task
            interval_id = None
            if hasattr(task, 'interval') and task.interval:
                interval_id = task.interval.id

                # Count how many TOTAL tasks use this interval (including this one)
                tasks_with_same_interval = PeriodicTask.objects.filter(interval_id=interval_id).count()
                logger.info(f"Interval {interval_id} is used by {tasks_with_same_interval} tasks total")

            # Delete the task first
            task_id = task.id
            task.delete()
            logger.info(f"Successfully deleted periodic task {task_id}")

            # Now check if we should delete the interval
            # We only delete if it was the ONLY task using this interval
            if interval_id and tasks_with_same_interval == 1:
                try:
                    interval = IntervalSchedule.objects.get(id=interval_id)
                    logger.info(f"Deleting interval schedule {interval_id} (not shared with other tasks)")
                    interval.delete()
                    logger.info(f"Successfully deleted interval {interval_id}")
                except IntervalSchedule.DoesNotExist:
                    logger.warning(f"Interval {interval_id} no longer exists")
            elif interval_id:
                logger.info(f"Not deleting interval {interval_id} as it's shared with {tasks_with_same_interval-1} other tasks")

            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting periodic task for EPGSource {epg_id}: {str(e)}", exc_info=True)
        return False


@shared_task
def refresh_all_epg_data():
    logger.info("Starting refresh_epg_data task.")
    # Exclude dummy EPG sources from refresh - they don't need refreshing
    active_sources = EPGSource.objects.filter(is_active=True).exclude(source_type='dummy')
    logger.debug(f"Found {active_sources.count()} active EPGSource(s) (excluding dummy EPGs).")

    for source in active_sources:
        refresh_epg_data(source.id)
        # Force garbage collection between sources
        gc.collect()

    logger.info("Finished refresh_epg_data task.")
    return "EPG data refreshed."


@shared_task(time_limit=14400)
def refresh_epg_data(source_id, force=False):
    if not acquire_task_lock('refresh_epg_data', source_id):
        logger.debug(f"EPG refresh for {source_id} already running")
        return

    lock_renewer = TaskLockRenewer('refresh_epg_data', source_id)
    lock_renewer.start()

    _release_task_db_connection()

    try:
        return _refresh_epg_data_impl(source_id, force=force)
    except Exception as e:
        logger.error(
            f"Error in refresh_epg_data for source {source_id}: {e}",
            exc_info=True,
        )
        _set_epg_source_status(
            source_id,
            EPGSource.STATUS_ERROR,
            f"Error refreshing EPG data: {str(e)[:500]}",
            notify_error=True,
            ws_error=str(e)[:500],
        )
    finally:
        _ensure_epg_refresh_terminal_status(source_id)
        _release_task_db_connection()
        gc.collect()
        lock_renewer.stop()
        release_task_lock('refresh_epg_data', source_id)


def _refresh_epg_data_impl(source_id, force=False):
    try:
        source = _get_epg_source(source_id)
    except EPGSource.DoesNotExist:
        logger.warning(
            f"EPG source with ID {source_id} not found, but task was triggered. "
            "Cleaning up orphaned task."
        )

        if delete_epg_refresh_task_by_id(source_id):
            logger.info(
                f"Successfully cleaned up orphaned task for EPG source {source_id}"
            )
        else:
            logger.info(f"No orphaned task found for EPG source {source_id}")

        return f"EPG source {source_id} does not exist, task cleaned up"

    if not source.is_active:
        logger.info(f"EPG source {source_id} is not active. Skipping.")
        return

    if source.source_type == 'dummy':
        logger.info(
            f"Skipping refresh for dummy EPG source {source.name} (ID: {source_id})"
        )
        return

    logger.info(f"Processing EPGSource: {source.name} (type: {source.source_type})")
    if source.source_type == 'xmltv':
        # Invalidate the byte-offset index before downloading the new file
        # so stale offsets are never used during the refresh window.
        EPGSourceIndex.objects.update_or_create(
            source_id=source.id, defaults={'data': None}
        )
        if not fetch_xmltv(source):
            logger.error(f"Failed to fetch XMLTV for source {source.name}")
            return

        if not parse_channels_only(source):
            logger.error(f"Failed to parse channels for source {source.name}")
            return

        # Build byte-offset index after programme data is committed so refresh
        # does not compete for memory/IO during the programme swap.
        if not parse_programs_for_source(source):
            logger.error(f"Failed to parse programs for source {source.name}")
            return

        build_programme_index_task.delay(source.id)

    elif source.source_type == 'schedules_direct':
        fetch_schedules_direct(source, force=force)

    EPGSource.objects.filter(id=source.id).update(updated_at=timezone.now())
    try:
        from apps.channels.tasks import evaluate_series_rules
        evaluate_series_rules.delay()
    except Exception:
        pass


def fetch_xmltv(source):
    # Handle cases with local file but no URL
    if not source.url and source.file_path and os.path.exists(source.file_path):
        logger.info(f"Using existing local file for EPG source: {source.name} at {source.file_path}")

        # Check if the existing file is compressed and we need to extract it
        if source.file_path.endswith(('.gz', '.zip')) and not source.file_path.endswith('.xml'):
            try:
                # Define the path for the extracted file in the cache directory
                cache_dir = os.path.join(settings.MEDIA_ROOT, "cached_epg")
                os.makedirs(cache_dir, exist_ok=True)
                xml_path = os.path.join(cache_dir, f"{source.id}.xml")

                # Extract to the cache location keeping the original
                extracted_path = extract_compressed_file(source.file_path, xml_path, delete_original=False)

                if extracted_path:
                    logger.info(f"Extracted mapped compressed file to: {extracted_path}")
                    # Update to use extracted_file_path instead of changing file_path
                    source.extracted_file_path = extracted_path
                    source.save(update_fields=['extracted_file_path'])
                else:
                    logger.error(f"Failed to extract mapped compressed file. Using original file: {source.file_path}")
            except Exception as e:
                logger.error(f"Failed to extract existing compressed file: {e}")
                # Continue with the original file if extraction fails

        # Set the status to success in the database
        source.status = 'success'
        source.save(update_fields=['status'])

        # Send a download complete notification
        send_epg_update(source.id, "downloading", 100, status="success")

        # Return True to indicate successful fetch, processing will continue with parse_channels_only
        return True

    # Handle cases where no URL is provided and no valid file path exists
    if not source.url:
        # Update source status for missing URL
        source.status = 'error'
        source.last_message = "No URL provided and no valid local file exists"
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "downloading", 100, status="error", error="No URL provided and no valid local file exists")
        return False

    logger.info(f"Fetching XMLTV data from source: {source.name}")
    try:
        # Get default user agent from settings
        stream_settings = CoreSettings.get_stream_settings()
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0"  # Fallback default
        default_user_agent_id = stream_settings.get('default_user_agent')
        if default_user_agent_id:
            try:
                user_agent_obj = UserAgent.objects.filter(id=int(default_user_agent_id)).first()
                if user_agent_obj and user_agent_obj.user_agent:
                    user_agent = user_agent_obj.user_agent
                    logger.debug(f"Using default user agent: {user_agent}")
            except (ValueError, Exception) as e:
                logger.warning(f"Error retrieving default user agent, using fallback: {e}")

        headers = {
            'User-Agent': user_agent
        }

        # Update status to fetching before starting download
        source.status = 'fetching'
        source.save(update_fields=['status'])

        # Send initial download notification
        send_epg_update(source.id, "downloading", 0)

        # Use streaming response to track download progress
        with requests.get(source.url, headers=headers, stream=True, timeout=60) as response:
            # Handle 404 specifically
            if response.status_code == 404:
                logger.error(f"EPG URL not found (404): {source.url}")
                # Update status to error in the database
                source.status = 'error'
                source.last_message = f"EPG source '{source.name}' returned 404 error - will retry on next scheduled run"
                source.save(update_fields=['status', 'last_message'])

                # Notify users through the WebSocket about the EPG fetch failure
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    'updates',
                    {
                        'type': 'update',
                        'data': {
                            "success": False,
                            "type": "epg_fetch_error",
                            "source_id": source.id,
                            "source_name": source.name,
                            "error_code": 404,
                            "message": f"EPG source '{source.name}' returned 404 error - will retry on next scheduled run"
                        }
                    }
                )
                # Ensure we update the download progress to 100 with error status
                send_epg_update(source.id, "downloading", 100, status="error", error="URL not found (404)")
                return False

            # For all other error status codes
            if response.status_code >= 400:
                error_message = f"HTTP error {response.status_code}"
                user_message = f"EPG source '{source.name}' encountered HTTP error {response.status_code}"

                # Update status to error in the database
                source.status = 'error'
                source.last_message = user_message
                source.save(update_fields=['status', 'last_message'])

                # Notify users through the WebSocket
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    'updates',
                    {
                        'type': 'update',
                        'data': {
                            "success": False,
                            "type": "epg_fetch_error",
                            "source_id": source.id,
                            "source_name": source.name,
                            "error_code": response.status_code,
                            "message": user_message
                        }
                    }
                )
                # Update download progress
                send_epg_update(source.id, "downloading", 100, status="error", error=user_message)
                return False

            response.raise_for_status()
            logger.debug("XMLTV data fetched successfully.")

            # Define base paths for consistent file naming
            cache_dir = os.path.join(settings.MEDIA_ROOT, "cached_epg")
            os.makedirs(cache_dir, exist_ok=True)

            # Create temporary download file with .tmp extension
            temp_download_path = os.path.join(cache_dir, f"{source.id}.tmp")

            # Check if we have content length for progress tracking
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_update_time = start_time
            update_interval = 0.5  # Only update every 0.5 seconds

            # Download to temporary file
            with open(temp_download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=16384):
                    f.write(chunk)

                    downloaded += len(chunk)
                    elapsed_time = time.time() - start_time

                    # Calculate download speed in KB/s
                    speed = downloaded / elapsed_time / 1024 if elapsed_time > 0 else 0

                    # Calculate progress percentage
                    if total_size and total_size > 0:
                        progress = min(100, int((downloaded / total_size) * 100))
                    else:
                        # If no content length header, estimate progress
                        progress = min(95, int((downloaded / (10 * 1024 * 1024)) * 100))  # Assume 10MB if unknown

                    # Time remaining (in seconds)
                    time_remaining = (total_size - downloaded) / (speed * 1024) if speed > 0 and total_size > 0 else 0

                    # Only send updates at specified intervals to avoid flooding
                    current_time = time.time()
                    if current_time - last_update_time >= update_interval and progress > 0:
                        last_update_time = current_time
                        send_epg_update(
                            source.id,
                            "downloading",
                            progress,
                            speed=round(speed, 2),
                            elapsed_time=round(elapsed_time, 1),
                            time_remaining=round(time_remaining, 1),
                            downloaded=f"{downloaded / (1024 * 1024):.2f} MB"
                        )

                    # Explicitly delete the chunk to free memory immediately
                    del chunk

            # Send completion notification
            send_epg_update(source.id, "downloading", 100)

            # Determine the appropriate file extension based on content detection
            with open(temp_download_path, 'rb') as f:
                content_sample = f.read(1024)  # Just need the first 1KB to detect format

            # Use our helper function to detect the format
            format_type, is_compressed, file_extension = detect_file_format(
                file_path=source.url,  # Original URL as a hint
                content=content_sample  # Actual file content for detection
            )

            logger.debug(f"File format detection results: type={format_type}, compressed={is_compressed}, extension={file_extension}")

            # Ensure consistent final paths
            compressed_path = os.path.join(cache_dir, f"{source.id}{file_extension}" if is_compressed else f"{source.id}.compressed")
            xml_path = os.path.join(cache_dir, f"{source.id}.xml")

            # Clean up old files before saving new ones
            if os.path.exists(compressed_path):
                try:
                    os.remove(compressed_path)
                    logger.debug(f"Removed old compressed file: {compressed_path}")
                except OSError as e:
                    logger.warning(f"Failed to remove old compressed file: {e}")

            if os.path.exists(xml_path):
                try:
                    os.remove(xml_path)
                    logger.debug(f"Removed old XML file: {xml_path}")
                except OSError as e:
                    logger.warning(f"Failed to remove old XML file: {e}")

            # Rename the temp file to appropriate final path
            if is_compressed:
                try:
                    os.rename(temp_download_path, compressed_path)
                    logger.debug(f"Renamed temp file to compressed file: {compressed_path}")
                    current_file_path = compressed_path
                except OSError as e:
                    logger.error(f"Failed to rename temp file to compressed file: {e}")
                    current_file_path = temp_download_path  # Fall back to using temp file
            else:
                try:
                    os.rename(temp_download_path, xml_path)
                    logger.debug(f"Renamed temp file to XML file: {xml_path}")
                    current_file_path = xml_path
                except OSError as e:
                    logger.error(f"Failed to rename temp file to XML file: {e}")
                    current_file_path = temp_download_path  # Fall back to using temp file

            # Now extract the file if it's compressed
            if is_compressed:
                try:
                    logger.info(f"Extracting compressed file {current_file_path}")
                    send_epg_update(source.id, "extracting", 0, message="Extracting downloaded file")

                    # Always extract to the standard XML path - set delete_original to True to clean up
                    extracted = extract_compressed_file(current_file_path, xml_path, delete_original=True)

                    if extracted:
                        logger.info(f"Successfully extracted to {xml_path}, compressed file deleted")
                        send_epg_update(source.id, "extracting", 100, message=f"File extracted successfully, temporary file removed")
                        # Update to store only the extracted file path since the compressed file is now gone
                        source.file_path = xml_path
                        source.extracted_file_path = None
                    else:
                        logger.error("Extraction failed, using compressed file")
                        send_epg_update(source.id, "extracting", 100, status="error", message="Extraction failed, using compressed file")
                        # Use the compressed file
                        source.file_path = current_file_path
                        source.extracted_file_path = None
                except Exception as e:
                    logger.error(f"Error extracting file: {str(e)}", exc_info=True)
                    send_epg_update(source.id, "extracting", 100, status="error", message=f"Error during extraction: {str(e)}")
                    # Use the compressed file if extraction fails
                    source.file_path = current_file_path
                    source.extracted_file_path = None
            else:
                # It's already an XML file
                source.file_path = current_file_path
                source.extracted_file_path = None

            # Update the source's file paths
            source.save(update_fields=['file_path', 'status', 'extracted_file_path'])

            # Update status to parsing
            source.status = 'parsing'
            source.save(update_fields=['status'])

            logger.info(f"Cached EPG file saved to {source.file_path}")

            return True

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error fetching XMLTV from {source.name}: {e}", exc_info=True)

        # Get error details
        status_code = e.response.status_code if hasattr(e, 'response') and e.response else 'unknown'
        error_message = str(e)

        # Create a user-friendly message
        user_message = f"EPG source '{source.name}' encountered HTTP error {status_code}"

        # Add specific handling for common HTTP errors
        if status_code == 404:
            user_message = f"EPG source '{source.name}' URL not found (404) - will retry on next scheduled run"
        elif status_code == 401 or status_code == 403:
            user_message = f"EPG source '{source.name}' access denied (HTTP {status_code}) - check credentials"
        elif status_code == 429:
            user_message = f"EPG source '{source.name}' rate limited (429) - try again later"
        elif status_code >= 500:
            user_message = f"EPG source '{source.name}' server error (HTTP {status_code}) - will retry later"

        # Update source status to error with the error message
        source.status = 'error'
        source.last_message = user_message
        source.save(update_fields=['status', 'last_message'])

        # Notify users through the WebSocket about the EPG fetch failure
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'updates',
            {
                'type': 'update',
                'data': {
                    "success": False,
                    "type": "epg_fetch_error",
                    "source_id": source.id,
                    "source_name": source.name,
                    "error_code": status_code,
                    "message": user_message,
                    "details": error_message
                }
            }
        )

        # Ensure we update the download progress to 100 with error status
        send_epg_update(source.id, "downloading", 100, status="error", error=user_message)
        return False
    except requests.exceptions.ConnectionError as e:
        # Handle connection errors separately
        error_message = str(e)
        user_message = f"Connection error: Unable to connect to EPG source '{source.name}'"
        logger.error(f"Connection error fetching XMLTV from {source.name}: {e}", exc_info=True)

        # Update source status
        source.status = 'error'
        source.last_message = user_message
        source.save(update_fields=['status', 'last_message'])

        # Send notifications
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'updates',
            {
                'type': 'update',
                'data': {
                    "success": False,
                    "type": "epg_fetch_error",
                    "source_id": source.id,
                    "source_name": source.name,
                    "error_code": "connection_error",
                    "message": user_message
                }
            }
        )
        send_epg_update(source.id, "downloading", 100, status="error", error=user_message)
        return False
    except requests.exceptions.Timeout as e:
        # Handle timeout errors specifically
        error_message = str(e)
        user_message = f"Timeout error: EPG source '{source.name}' took too long to respond"
        logger.error(f"Timeout error fetching XMLTV from {source.name}: {e}", exc_info=True)

        # Update source status
        source.status = 'error'
        source.last_message = user_message
        source.save(update_fields=['status', 'last_message'])

        # Send notifications
        send_epg_update(source.id, "downloading", 100, status="error", error=user_message)
        return False
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error fetching XMLTV from {source.name}: {e}", exc_info=True)

        # Update source status for general exceptions too
        source.status = 'error'
        source.last_message = f"Error: {error_message}"
        source.save(update_fields=['status', 'last_message'])

        # Ensure we update the download progress to 100 with error status
        send_epg_update(source.id, "downloading", 100, status="error", error=f"Error: {error_message}")
        return False


def extract_compressed_file(file_path, output_path=None, delete_original=False):
    """
    Extracts a compressed file (.gz or .zip) to an XML file.

    Args:
        file_path: Path to the compressed file
        output_path: Specific path where the file should be extracted (optional)
        delete_original: Whether to delete the original compressed file after successful extraction

    Returns:
        Path to the extracted XML file, or None if extraction failed
    """
    try:
        if output_path is None:
            base_path = os.path.splitext(file_path)[0]
            extracted_path = f"{base_path}.xml"
        else:
            extracted_path = output_path

        # Make sure the output path doesn't already exist
        if os.path.exists(extracted_path):
            try:
                os.remove(extracted_path)
                logger.info(f"Removed existing extracted file: {extracted_path}")
            except Exception as e:
                logger.warning(f"Failed to remove existing extracted file: {e}")
                # If we can't delete the existing file and no specific output was requested,
                # create a unique filename instead
                if output_path is None:
                    base_path = os.path.splitext(file_path)[0]
                    extracted_path = f"{base_path}_{uuid.uuid4().hex[:8]}.xml"

        # Use our detection helper to determine the file format instead of relying on extension
        with open(file_path, 'rb') as f:
            content_sample = f.read(4096)  # Read a larger sample to ensure accurate detection

        format_type, is_compressed, _ = detect_file_format(file_path=file_path, content=content_sample)

        if format_type == 'gzip':
            logger.debug(f"Extracting gzip file: {file_path}")
            try:
                # First check if the content is XML by reading a sample
                with gzip.open(file_path, 'rb') as gz_file:
                    content_sample = gz_file.read(4096)  # Read first 4KB for detection
                    detected_format, _, _ = detect_file_format(content=content_sample)

                    if detected_format != 'xml':
                        logger.warning(f"GZIP file does not appear to contain XML content: {file_path} (detected as: {detected_format})")
                        # Continue anyway since GZIP only contains one file

                    # Reset file pointer and extract the content
                    gz_file.seek(0)
                    with open(extracted_path, 'wb') as out_file:
                        while True:
                            chunk = gz_file.read(MAX_EXTRACT_CHUNK_SIZE)
                            if not chunk or len(chunk) == 0:
                                break
                            out_file.write(chunk)
            except Exception as e:
                logger.error(f"Error extracting GZIP file: {e}", exc_info=True)
                return None

            logger.info(f"Successfully extracted gzip file to: {extracted_path}")

            # Delete original compressed file if requested
            if delete_original:
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted original compressed file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete original compressed file {file_path}: {e}")

            return extracted_path

        elif format_type == 'zip':
            logger.debug(f"Extracting zip file: {file_path}")
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                # Find the first XML file in the ZIP archive
                xml_files = [f for f in zip_file.namelist() if f.lower().endswith('.xml')]

                if not xml_files:
                    logger.info("No files with .xml extension found in ZIP archive, checking content of all files")
                    # Check content of each file to see if any are XML without proper extension
                    for filename in zip_file.namelist():
                        if not filename.endswith('/'):  # Skip directories
                            try:
                                # Read a sample of the file content
                                content_sample = zip_file.read(filename, 4096)  # Read up to 4KB for detection
                                format_type, _, _ = detect_file_format(content=content_sample)
                                if format_type == 'xml':
                                    logger.info(f"Found XML content in file without .xml extension: {filename}")
                                    xml_files = [filename]
                                    break
                            except Exception as e:
                                logger.warning(f"Error reading file {filename} from ZIP: {e}")

                if not xml_files:
                    logger.error("No XML file found in ZIP archive")
                    return None

                # Extract the first XML file
                with open(extracted_path, 'wb') as out_file:
                    with zip_file.open(xml_files[0], "r") as xml_file:
                        while True:
                            chunk = xml_file.read(MAX_EXTRACT_CHUNK_SIZE)
                            if not chunk or len(chunk) == 0:
                                break
                            out_file.write(chunk)

            logger.info(f"Successfully extracted zip file to: {extracted_path}")

            # Delete original compressed file if requested
            if delete_original:
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted original compressed file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete original compressed file {file_path}: {e}")

            return extracted_path

        else:
            logger.error(f"Unsupported or unrecognized compressed file format: {file_path} (detected as: {format_type})")
            return None

    except Exception as e:
        logger.error(f"Error extracting {file_path}: {str(e)}", exc_info=True)
        return None


def parse_channels_only(source):
    # Use extracted file if available, otherwise use the original file path
    file_path = source.extracted_file_path if source.extracted_file_path else source.file_path
    if not file_path:
        file_path = source.get_cache_file()

    # Send initial parsing notification
    send_epg_update(source.id, "parsing_channels", 0)

    process = None
    should_log_memory = False

    try:
        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(f"EPG file does not exist at path: {file_path}")

            # Update the source's file_path to the default cache location
            new_path = source.get_cache_file()
            logger.info(f"Updating file_path from '{file_path}' to '{new_path}'")
            source.file_path = new_path
            source.save(update_fields=['file_path'])

            # If the source has a URL, fetch the data before continuing
            if source.url:
                logger.info(f"Fetching new EPG data from URL: {source.url}")
                fetch_success = fetch_xmltv(source)  # Store the result

                # Only proceed if fetch was successful AND file exists
                if not fetch_success:
                    logger.error(f"Failed to fetch EPG data from URL: {source.url}")
                    # Update status to error
                    source.status = 'error'
                    source.last_message = f"Failed to fetch EPG data from URL"
                    source.save(update_fields=['status', 'last_message'])
                    # Send error notification
                    send_epg_update(source.id, "parsing_channels", 100, status="error", error="Failed to fetch EPG data")
                    return False

                # Verify the file was downloaded successfully
                if not os.path.exists(source.file_path):
                    logger.error(f"Failed to fetch EPG data, file still missing at: {source.file_path}")
                    # Update status to error
                    source.status = 'error'
                    source.last_message = f"Failed to fetch EPG data, file missing after download"
                    source.save(update_fields=['status', 'last_message'])
                    send_epg_update(source.id, "parsing_channels", 100, status="error", error="File not found after download")
                    return False

                # Update file_path with the new location
                file_path = source.file_path
            else:
                logger.error(f"No URL provided for EPG source {source.name}, cannot fetch new data")
                # Update status to error
                source.status = 'error'
                source.last_message = f"No URL provided, cannot fetch EPG data"
                source.save(update_fields=['status', 'last_message'])
                send_epg_update(
                    source.id,
                    "parsing_channels",
                    100,
                    status="error",
                    error="No URL provided",
                )
                return False

        # Initialize process variable for memory tracking only in debug mode
        try:
            process = None
            # Get current log level as a number
            current_log_level = logger.getEffectiveLevel()

            # Only track memory usage when log level is DEBUG (10) or more verbose
            # This is more future-proof than string comparisons
            should_log_memory = current_log_level <= logging.DEBUG or settings.DEBUG

            if should_log_memory:
                process = psutil.Process()
                initial_memory = process.memory_info().rss / 1024 / 1024
                logger.debug(f"[parse_channels_only] Initial memory usage: {initial_memory:.2f} MB")
        except (ImportError, NameError):
            process = None
            should_log_memory = False
            logger.warning("psutil not available for memory tracking")

        # Replace full dictionary load with more efficient lookup set
        existing_tvg_ids = set()
        existing_epgs = {}
        scanned_tvg_ids = set()  # Track tvg_ids seen in the current scan for stale cleanup
        last_id = 0
        chunk_size = 5000

        while True:
            tvg_id_chunk = set(EPGData.objects.filter(
                epg_source=source,
                id__gt=last_id
            ).order_by('id').values_list('tvg_id', flat=True)[:chunk_size])

            if not tvg_id_chunk:
                break

            existing_tvg_ids.update(tvg_id_chunk)
            last_id = EPGData.objects.filter(tvg_id__in=tvg_id_chunk).order_by('-id')[0].id
        # Update progress to show file read starting
        send_epg_update(source.id, "parsing_channels", 10)

        # Stream parsing instead of loading entire file at once
        # This can be simplified since we now always have XML files
        epgs_to_create = []
        epgs_to_update = []
        total_channels = 0
        processed_channels = 0
        batch_size = 500  # Process in batches to limit memory usage
        progress = 0  # Initialize progress variable here
        icon_url_max_length = EPGData._meta.get_field('icon_url').max_length  # Get max length for icon_url field
        name_max_length = EPGData._meta.get_field('name').max_length  # Get max length for name field

        # Track memory at key points
        if process:
            logger.debug(f"[parse_channels_only] Memory before opening file: {process.memory_info().rss / 1024 / 1024:.2f} MB")

        try:
            # Attempt to count existing channels in the database
            try:
                total_channels = EPGData.objects.filter(epg_source=source).count()
                logger.info(f"Found {total_channels} existing channels for this source")
            except Exception as e:
                logger.error(f"Error counting channels: {e}")
                total_channels = 500  # Default estimate
            if process:
                logger.debug(f"[parse_channels_only] Memory after closing initial file: {process.memory_info().rss / 1024 / 1024:.2f} MB")

            # Update progress after counting
            send_epg_update(source.id, "parsing_channels", 25, total_channels=total_channels)

            # Open the file - no need to check file type since it's always XML now
            logger.debug(f"Opening file for channel parsing: {file_path}")
            source_file = _open_xmltv_file(file_path)

            if process:
                logger.debug(f"[parse_channels_only] Memory after opening file: {process.memory_info().rss / 1024 / 1024:.2f} MB")

            # Change iterparse to look for both channel and programme elements
            logger.debug(f"Creating iterparse context for channels and programmes")
            channel_parser = etree.iterparse(source_file, events=('end',), tag=('channel', 'programme'), remove_blank_text=True, recover=True)
            if process:
                logger.debug(f"[parse_channels_only] Memory after creating iterparse: {process.memory_info().rss / 1024 / 1024:.2f} MB")

            channel_count = 0
            total_elements_processed = 0  # Track total elements processed, not just channels
            for _, elem in channel_parser:
                total_elements_processed += 1
                # Only process channel elements
                if elem.tag == 'channel':
                    channel_count += 1
                    tvg_id = elem.get('id', '').strip()
                    if tvg_id:
                        scanned_tvg_ids.add(tvg_id)
                        display_name = None
                        icon_url = None
                        for child in elem:
                            if display_name is None and child.tag == 'display-name' and child.text:
                                display_name = child.text.strip()
                            elif child.tag == 'icon':
                                raw_icon_url = child.get('src', '').strip()
                                icon_url = validate_icon_url_fast(raw_icon_url, icon_url_max_length)
                            if display_name and icon_url:
                                break  # No need to continue if we have both

                        if not display_name:
                            display_name = tvg_id

                        if display_name and len(display_name) > name_max_length:
                            logger.warning(f"EPG display name too long ({len(display_name)} > {name_max_length}), truncating: {display_name[:80]}...")
                            display_name = display_name[:name_max_length]

                        # Use lazy loading approach to reduce memory usage
                        if tvg_id in existing_tvg_ids:
                            # Only fetch the object if we need to update it and it hasn't been loaded yet
                            if tvg_id not in existing_epgs:
                                try:
                                    # This loads the full EPG object from the database and caches it
                                    existing_epgs[tvg_id] = EPGData.objects.get(tvg_id=tvg_id, epg_source=source)
                                except EPGData.DoesNotExist:
                                    # Handle race condition where record was deleted
                                    existing_tvg_ids.remove(tvg_id)
                                    epgs_to_create.append(EPGData(
                                        tvg_id=tvg_id,
                                        name=display_name,
                                        icon_url=icon_url,
                                        epg_source=source,
                                    ))
                                    logger.debug(f"[parse_channels_only] Added new channel to epgs_to_create 1: {tvg_id} - {display_name}")
                                    processed_channels += 1
                                    continue

                            # We use the cached object to check if the name or icon_url has changed
                            epg_obj = existing_epgs[tvg_id]
                            needs_update = False
                            if epg_obj.name != display_name:
                                epg_obj.name = display_name
                                needs_update = True
                            if epg_obj.icon_url != icon_url:
                                epg_obj.icon_url = icon_url
                                needs_update = True

                            if needs_update:
                                epgs_to_update.append(epg_obj)
                                logger.debug(f"[parse_channels_only] Added channel to update to epgs_to_update: {tvg_id} - {display_name}")
                            else:
                                # No changes needed, just clear the element
                                logger.debug(f"[parse_channels_only] No changes needed for channel {tvg_id} - {display_name}")
                        else:
                            # This is a new channel that doesn't exist in our database
                            epgs_to_create.append(EPGData(
                                tvg_id=tvg_id,
                                name=display_name,
                                icon_url=icon_url,
                                epg_source=source,
                            ))
                            logger.debug(f"[parse_channels_only] Added new channel to epgs_to_create 2: {tvg_id} - {display_name}")

                    processed_channels += 1

                    # Batch processing
                    if len(epgs_to_create) >= batch_size:
                        logger.info(f"[parse_channels_only] Bulk creating {len(epgs_to_create)} EPG entries")
                        EPGData.objects.bulk_create(epgs_to_create, ignore_conflicts=True)
                        if process:
                            logger.info(f"[parse_channels_only] Memory after bulk_create: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                        del epgs_to_create  # Explicit deletion
                        epgs_to_create = []
                        cleanup_memory(log_usage=should_log_memory, force_collection=True)
                        if process:
                            logger.info(f"[parse_channels_only] Memory after gc.collect(): {process.memory_info().rss / 1024 / 1024:.2f} MB")

                    if len(epgs_to_update) >= batch_size:
                        logger.info(f"[parse_channels_only] Bulk updating {len(epgs_to_update)} EPG entries")
                        if process:
                            logger.info(f"[parse_channels_only] Memory before bulk_update: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                        EPGData.objects.bulk_update(epgs_to_update, ["name", "icon_url"])
                        if process:
                            logger.info(f"[parse_channels_only] Memory after bulk_update: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                        epgs_to_update = []
                        # Force garbage collection
                        cleanup_memory(log_usage=should_log_memory, force_collection=True)

                    # Periodically clear the existing_epgs cache to prevent memory buildup
                    if processed_channels % 1000 == 0:
                        logger.info(f"[parse_channels_only] Clearing existing_epgs cache at {processed_channels} channels")
                        existing_epgs.clear()
                        cleanup_memory(log_usage=should_log_memory, force_collection=True)
                        if process:
                            logger.info(f"[parse_channels_only] Memory after clearing cache: {process.memory_info().rss / 1024 / 1024:.2f} MB")

                    # Send progress updates
                    if processed_channels % 100 == 0 or processed_channels == total_channels:
                        progress = 25 + int((processed_channels / total_channels) * 65) if total_channels > 0 else 90
                        send_epg_update(
                            source.id,
                            "parsing_channels",
                            progress,
                            processed=processed_channels,
                            total=total_channels
                        )
                    if processed_channels > total_channels:
                        logger.debug(f"[parse_channels_only] Processed channel {tvg_id} - processed {processed_channels - total_channels} additional channels")
                    else:
                        logger.debug(f"[parse_channels_only] Processed channel {tvg_id} - processed {processed_channels}/{total_channels}")
                    if process:
                        logger.debug(f"[parse_channels_only] Memory before elem cleanup: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                    # Clear memory
                    try:
                        # First clear the element's content
                        clear_element(elem)

                    except Exception as e:
                        # Just log the error and continue - don't let cleanup errors stop processing
                        logger.debug(f"[parse_channels_only] Non-critical error during XML element cleanup: {e}")
                    if process:
                        logger.debug(f"[parse_channels_only] Memory after elem cleanup: {process.memory_info().rss / 1024 / 1024:.2f} MB")

                    logger.debug(f"[parse_channels_only] Total elements processed: {total_elements_processed}")

                else:
                    logger.trace(f"[parse_channels_only] Skipping non-channel element: {elem.get('channel', 'unknown')} - {elem.get('start', 'unknown')} {elem.tag}")
                    clear_element(elem)
                    continue

        except (etree.XMLSyntaxError, Exception) as xml_error:
            logger.error(f"[parse_channels_only] XML parsing failed: {xml_error}")
            # Update status to error
            source.status = 'error'
            source.last_message = f"Error parsing XML file: {str(xml_error)}"
            source.save(update_fields=['status', 'last_message'])
            send_epg_update(source.id, "parsing_channels", 100, status="error", error=str(xml_error))
            return False
        if process:
            logger.info(f"[parse_channels_only] Processed {processed_channels} channels current memory: {process.memory_info().rss / 1024 / 1024:.2f} MB")
        else:
            logger.info(f"[parse_channels_only] Processed {processed_channels} channels")
        # Process any remaining items
        if epgs_to_create:
            EPGData.objects.bulk_create(epgs_to_create, ignore_conflicts=True)
            logger.debug(f"[parse_channels_only] Created final batch of {len(epgs_to_create)} EPG entries")

        if epgs_to_update:
            EPGData.objects.bulk_update(epgs_to_update, ["name", "icon_url"])
            logger.debug(f"[parse_channels_only] Updated final batch of {len(epgs_to_update)} EPG entries")

        # Clean up stale EPGData: entries that existed before the scan but weren't seen, and aren't mapped to any channel.
        # Use existing_tvg_ids - scanned_tvg_ids to avoid a full-table scan with a large EXCLUDE list.
        potentially_stale = existing_tvg_ids - scanned_tvg_ids
        if potentially_stale:
            stale_qs = EPGData.objects.filter(epg_source=source, tvg_id__in=potentially_stale, channels__isnull=True)
            deleted_count, _ = stale_qs.delete()
            if deleted_count:
                logger.info(f"[parse_channels_only] Cleaned up {deleted_count} stale EPG entries not in current scan and unmapped to any channel")

        if process:
            logger.debug(f"[parse_channels_only] Memory after final batch creation: {process.memory_info().rss / 1024 / 1024:.2f} MB")

        # Update source status with channel count
        source.status = 'success'
        source.last_message = f"Successfully parsed {processed_channels} channels"
        source.save(update_fields=['status', 'last_message'])

        # Send completion notification
        send_epg_update(
            source.id,
            "parsing_channels",
            100,
            status="success",
            channels_count=processed_channels
        )

        logger.info(f"Finished parsing channel info. Found {processed_channels} channels.")

        from apps.channels.utils import maybe_auto_apply_epg_logos
        maybe_auto_apply_epg_logos(source)

        return True

    except FileNotFoundError:
        logger.error(f"EPG file not found at: {file_path}")
        # Update status to error
        source.status = 'error'
        source.last_message = f"EPG file not found: {file_path}"
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "parsing_channels", 100, status="error", error="File not found")
        return False
    except Exception as e:
        logger.error(f"Error reading EPG file {file_path}: {e}", exc_info=True)
        # Update status to error
        source.status = 'error'
        source.last_message = f"Error parsing EPG file: {str(e)}"
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "parsing_channels", 100, status="error", error=str(e))
        return False
    finally:
        # Cleanup memory and close file
        if process:
            logger.debug(f"[parse_channels_only] Memory before cleanup: {process.memory_info().rss / 1024 / 1024:.2f} MB")
        try:
            # Output any errors in the channel_parser error log
            if 'channel_parser' in locals() and hasattr(channel_parser, 'error_log') and len(channel_parser.error_log) > 0:
                logger.debug(f"XML parser errors found ({len(channel_parser.error_log)} total):")
                for i, error in enumerate(channel_parser.error_log):
                    logger.debug(f"  Error {i+1}: {error}")
            if 'channel_parser' in locals():
                del channel_parser
            if 'elem' in locals():
                del elem
            if 'parent' in locals():
                del parent

            if 'source_file' in locals():
                source_file.close()
                del source_file
            # Clear remaining large data structures
            existing_epgs.clear()
            epgs_to_create.clear()
            epgs_to_update.clear()
            existing_epgs = None
            epgs_to_create = None
            epgs_to_update = None
            if 'scanned_tvg_ids' in locals() and scanned_tvg_ids is not None:
                scanned_tvg_ids.clear()
                scanned_tvg_ids = None
            cleanup_memory(log_usage=should_log_memory, force_collection=True)
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")

        try:
            if process:
                final_memory = process.memory_info().rss / 1024 / 1024
                logger.debug(f"[parse_channels_only] Final memory usage: {final_memory:.2f} MB")
                process = None
        except:
            pass



@shared_task(time_limit=3600, soft_time_limit=3500)
def parse_programs_for_tvg_id(epg_id, force=False):
    try:
        from apps.epg.models import EPGData
        epg_obj = EPGData.objects.select_related('epg_source').filter(id=epg_id).first()
        if epg_obj and epg_obj.epg_source and epg_obj.epg_source.source_type == 'schedules_direct':
            return fetch_sd_guide_for_epg(epg_id, force=force)
    except Exception as e:
        logger.warning(f"Could not check EPG source type for id={epg_id}: {e}")

    if not acquire_task_lock('parse_epg_programs', epg_id):
        logger.info(f"Program parse for {epg_id} already in progress, skipping duplicate task")
        return "Task already running"

    lock_renewer = TaskLockRenewer('parse_epg_programs', epg_id)
    lock_renewer.start()

    source_file = None
    program_parser = None
    programs_to_create = []
    programs_processed = 0
    try:
        # Add memory tracking only in trace mode or higher
        try:
            process = None
            # Get current log level as a number
            current_log_level = logger.getEffectiveLevel()

            # Only track memory usage when log level is TRACE or more verbose or if running in DEBUG mode
            should_log_memory = current_log_level <= 5 or settings.DEBUG

            if should_log_memory:
                process = psutil.Process()
                initial_memory = process.memory_info().rss / 1024 / 1024
                logger.info(f"[parse_programs_for_tvg_id] Initial memory usage: {initial_memory:.2f} MB")
                mem_before = initial_memory
        except ImportError:
            process = None
            should_log_memory = False

        epg = EPGData.objects.get(id=epg_id)
        epg_source = epg.epg_source

        # Skip program parsing for dummy EPG sources - they don't have program data files
        if epg_source.source_type == 'dummy':
            logger.info(f"Skipping program parsing for dummy EPG source {epg_source.name} (ID: {epg_id})")
            lock_renewer.stop()
            release_task_lock('parse_epg_programs', epg_id)
            return

        if not force and not Channel.objects.filter(epg_data=epg).exists():
            logger.info(f"No channels matched to EPG {epg.tvg_id}")
            lock_renewer.stop()
            release_task_lock('parse_epg_programs', epg_id)
            return

        logger.info(f"Refreshing program data for tvg_id: {epg.tvg_id}")

        # Optimize deletion with a single delete query instead of chunking
        # This is faster for most database engines
        ProgramData.objects.filter(epg=epg).delete()

        file_path = epg_source.extracted_file_path if epg_source.extracted_file_path else epg_source.file_path
        if not file_path:
            file_path = epg_source.get_cache_file()

        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(f"EPG file not found at: {file_path}")

            if epg_source.url:
                # Update the file path in the database
                new_path = epg_source.get_cache_file()
                logger.info(f"Updating file_path from '{file_path}' to '{new_path}'")
                epg_source.file_path = new_path
                epg_source.save(update_fields=['file_path'])
                logger.info(f"Fetching new EPG data from URL: {epg_source.url}")
            else:
                logger.info(f"EPG source does not have a URL, using existing file path: {file_path} to rebuild cache")

            # Fetch new data before continuing
            if epg_source:

                # Properly check the return value from fetch_xmltv
                fetch_success = fetch_xmltv(epg_source)

                # If fetch was not successful or the file still doesn't exist, abort
                if not fetch_success:
                    logger.error(f"Failed to fetch EPG data, cannot parse programs for tvg_id: {epg.tvg_id}")
                    # Update status to error if not already set
                    epg_source.status = 'error'
                    epg_source.last_message = f"Failed to download EPG data, cannot parse programs"
                    epg_source.save(update_fields=['status', 'last_message'])
                    send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="Failed to download EPG file")
                    lock_renewer.stop()
                    release_task_lock('parse_epg_programs', epg_id)
                    return

                # Also check if the file exists after download
                if not os.path.exists(epg_source.file_path):
                    logger.error(f"Failed to fetch EPG data, file still missing at: {epg_source.file_path}")
                    epg_source.status = 'error'
                    epg_source.last_message = f"Failed to download EPG data, file missing after download"
                    epg_source.save(update_fields=['status', 'last_message'])
                    send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="File not found after download")
                    lock_renewer.stop()
                    release_task_lock('parse_epg_programs', epg_id)
                    return

                # Update file_path with the new location
                if epg_source.extracted_file_path:
                    file_path = epg_source.extracted_file_path
                else:
                    file_path = epg_source.file_path
            else:
                logger.error(f"No URL provided for EPG source {epg_source.name}, cannot fetch new data")
                # Update status to error
                epg_source.status = 'error'
                epg_source.last_message = f"No URL provided, cannot fetch EPG data"
                epg_source.save(update_fields=['status', 'last_message'])
                send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="No URL provided")
                lock_renewer.stop()
                release_task_lock('parse_epg_programs', epg_id)
                return

        # Use streaming parsing to reduce memory usage
        # No need to check file type anymore since it's always XML
        logger.debug(f"Parsing programs for tvg_id={epg.tvg_id} from {file_path}")

        # Memory usage tracking
        if process:
            try:
                mem_before = process.memory_info().rss / 1024 / 1024
                logger.debug(f"[parse_programs_for_tvg_id] Memory before parsing {epg.tvg_id} -  {mem_before:.2f} MB")
            except Exception as e:
                logger.warning(f"Error tracking memory: {e}")
                mem_before = 0

        programs_to_create = []
        batch_size = 1000  # Process in batches to limit memory usage

        try:
            # Open the file directly - no need to check compression
            logger.debug(f"Opening file for parsing: {file_path}")
            source_file = _open_xmltv_file(file_path)

            # Stream parse the file using lxml's iterparse
            program_parser = etree.iterparse(source_file, events=('end',), tag='programme',  remove_blank_text=True, recover=True)

            for _, elem in program_parser:
                if elem.get('channel') == epg.tvg_id:
                    try:
                        start_time = parse_xmltv_time(elem.get('start'))
                        end_time = parse_xmltv_time(elem.get('stop'))
                        title = None
                        desc = None
                        sub_title = None

                        # Efficiently process child elements
                        for child in elem:
                            if child.tag == 'title':
                                title = child.text or 'No Title'
                            elif child.tag == 'desc':
                                desc = child.text or ''
                            elif child.tag == 'sub-title':
                                sub_title = child.text or ''

                        if not title:
                            title = 'No Title'

                        # Extract custom properties
                        custom_props = extract_custom_properties(elem)
                        custom_properties_json = None

                        if custom_props:
                            logger.trace(f"Number of custom properties: {len(custom_props)}")
                            custom_properties_json = custom_props

                        # Fallback: extract S/E from description when episode-num
                        # elements didn't provide them
                        if desc:
                            has_season = (custom_properties_json or {}).get('season') is not None
                            has_episode = (custom_properties_json or {}).get('episode') is not None
                            if not has_season or not has_episode:
                                d_season, d_episode, cleaned_desc = extract_season_episode_from_description(desc)
                                if d_season is not None and d_episode is not None:
                                    if custom_properties_json is None:
                                        custom_properties_json = {}
                                    if not has_season:
                                        custom_properties_json['season'] = d_season
                                    if not has_episode:
                                        custom_properties_json['episode'] = d_episode
                                    custom_properties_json['season_episode_source'] = 'description'
                                    desc = cleaned_desc

                        programs_to_create.append(ProgramData(
                            epg=epg,
                            start_time=start_time,
                            end_time=end_time,
                            title=title[:255],
                            description=desc,
                            sub_title=sub_title,
                            tvg_id=epg.tvg_id,
                            custom_properties=custom_properties_json
                        ))
                        programs_processed += 1
                        # Clear the element to free memory
                        clear_element(elem)
                        # Batch processing
                        if len(programs_to_create) >= batch_size:
                            ProgramData.objects.bulk_create(programs_to_create)
                            logger.debug(f"Saved batch of {len(programs_to_create)} programs for {epg.tvg_id}")
                            programs_to_create = []
                            # Only call gc.collect() every few batches
                            if programs_processed % (batch_size * 5) == 0:
                                gc.collect()

                    except Exception as e:
                        logger.error(f"Error processing program for {epg.tvg_id}: {e}", exc_info=True)
                else:
                    # Immediately clean up non-matching elements to reduce memory pressure
                    if elem is not None:
                        clear_element(elem)
                    continue

            # Make sure to close the file and release parser resources
            if source_file:
                source_file.close()
                source_file = None

            if program_parser:
                program_parser = None

            gc.collect()

        except zipfile.BadZipFile as zip_error:
            logger.error(f"Bad ZIP file: {zip_error}")
            raise
        except etree.XMLSyntaxError as xml_error:
            logger.error(f"XML syntax error parsing program data: {xml_error}")
            raise
        except Exception as e:
            logger.error(f"Error parsing XML for programs: {e}", exc_info=True)
            raise
        finally:
            # Ensure file is closed even if an exception occurs
            if source_file:
                source_file.close()
                source_file = None
             # Memory tracking after processing
            if process:
                try:
                    mem_after = process.memory_info().rss / 1024 / 1024
                    logger.info(f"[parse_programs_for_tvg_id] Memory after parsing 1 {epg.tvg_id} - {programs_processed} programs: {mem_after:.2f} MB (change: {mem_after-mem_before:.2f} MB)")
                except Exception as e:
                    logger.warning(f"Error tracking memory: {e}")

        # Process any remaining items
        if programs_to_create:
            ProgramData.objects.bulk_create(programs_to_create)
            logger.debug(f"Saved final batch of {len(programs_to_create)} programs for {epg.tvg_id}")
            programs_to_create = None
            custom_props = None
            custom_properties_json = None


        logger.info(f"Completed program parsing for tvg_id={epg.tvg_id}.")
    finally:
        # Reset internal caches and pools that lxml might be keeping
        try:
            etree.clear_error_log()
        except:
            pass
        # Explicit cleanup of all potentially large objects
        if source_file:
            try:
                source_file.close()
            except:
                pass
        source_file = None
        program_parser = None
        programs_to_create = None

        epg_source = None
        # Add comprehensive cleanup before releasing lock
        cleanup_memory(log_usage=should_log_memory, force_collection=True)
        # Memory tracking after processing
        if process:
            try:
                mem_after = process.memory_info().rss / 1024 / 1024
                logger.info(f"[parse_programs_for_tvg_id] Final memory usage {epg.tvg_id} - {programs_processed} programs: {mem_after:.2f} MB (change: {mem_after-mem_before:.2f} MB)")
            except Exception as e:
                logger.warning(f"Error tracking memory: {e}")
            process = None
        epg = None
        programs_processed = None
        lock_renewer.stop()
        release_task_lock('parse_epg_programs', epg_id)


_EPG_PROGRAM_STAGING_TABLE = 'epg_program_staging'
# Parse batches bound Python memory during XML iterparse; swap batches bound each
# DELETE/INSERT statement inside the single atomic swap transaction.
_EPG_PARSE_BATCH_SIZE = 2500
_EPG_SWAP_BATCH_SIZE = 5000


def _epg_program_staging_supported():
    return connection.vendor == 'postgresql'


def _prepare_epg_program_staging_table():
    """Create/truncate a session-scoped temp table for streaming EPG programme inserts."""
    if not _epg_program_staging_supported():
        return False

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TEMP TABLE IF NOT EXISTS {_EPG_PROGRAM_STAGING_TABLE} (
                epg_id bigint NOT NULL,
                start_time timestamptz NOT NULL,
                end_time timestamptz NOT NULL,
                title varchar(255) NOT NULL,
                sub_title text,
                description text,
                tvg_id varchar(255),
                custom_properties jsonb
            ) ON COMMIT PRESERVE ROWS
            """
        )
        cursor.execute(f"TRUNCATE {_EPG_PROGRAM_STAGING_TABLE}")
    return True


def _clear_epg_program_staging_table():
    if not _epg_program_staging_supported():
        return
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {_EPG_PROGRAM_STAGING_TABLE}")


def _flush_epg_program_staging_batch(programs_batch):
    """Insert a batch of unsaved ProgramData rows into the session staging table."""
    if not programs_batch or not _epg_program_staging_supported():
        return

    values_sql = []
    params = []
    for program in programs_batch:
        values_sql.append("(%s, %s, %s, %s, %s, %s, %s, %s)")
        custom_properties = program.custom_properties
        if custom_properties is not None and not isinstance(custom_properties, str):
            custom_properties = json.dumps(custom_properties)
        params.extend([
            program.epg_id,
            program.start_time,
            program.end_time,
            program.title,
            program.sub_title,
            program.description,
            program.tvg_id,
            custom_properties,
        ])

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {_EPG_PROGRAM_STAGING_TABLE} (
                epg_id, start_time, end_time, title, sub_title, description, tvg_id, custom_properties
            ) VALUES {', '.join(values_sql)}
            """,
            params,
        )


def _swap_staged_epg_programs(mapped_epg_ids, epg_source, batch_size=_EPG_SWAP_BATCH_SIZE):
    """
    Atomically replace mapped programme rows with staged data.
    Must be called inside transaction.atomic().

    Staged rows are moved in batches (DELETE ... RETURNING + INSERT) so Postgres
    does not need to materialize the entire catalogue in one statement.
    """
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = '10min'")

    deleted_count = ProgramData.objects.filter(epg_id__in=mapped_epg_ids).delete()[0]
    logger.debug(f"Deleted {deleted_count} existing programs")

    unmapped_epg_ids = list(
        EPGData.objects.filter(epg_source=epg_source)
        .exclude(id__in=mapped_epg_ids)
        .values_list('id', flat=True)
    )
    if unmapped_epg_ids:
        orphaned_count = ProgramData.objects.filter(epg_id__in=unmapped_epg_ids).delete()[0]
        if orphaned_count > 0:
            logger.info(
                f"Cleaned up {orphaned_count} orphaned programs for "
                f"{len(unmapped_epg_ids)} unmapped EPG entries"
            )

    if not _epg_program_staging_supported():
        raise RuntimeError('_swap_staged_epg_programs requires PostgreSQL staging support')

    program_table = ProgramData._meta.db_table
    total_inserted = 0
    while True:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                WITH moved AS (
                    DELETE FROM {_EPG_PROGRAM_STAGING_TABLE}
                    WHERE ctid IN (
                        SELECT ctid FROM {_EPG_PROGRAM_STAGING_TABLE} LIMIT %s
                    )
                    RETURNING
                        epg_id, start_time, end_time, title, sub_title,
                        description, tvg_id, custom_properties
                )
                INSERT INTO {program_table} (
                    epg_id, start_time, end_time, title, sub_title,
                    description, tvg_id, custom_properties
                )
                SELECT
                    epg_id, start_time, end_time, title, sub_title,
                    description, tvg_id, custom_properties
                FROM moved
                """,
                [batch_size],
            )
            moved_count = cursor.rowcount
        if moved_count == 0:
            break
        total_inserted += moved_count

    logger.debug(f"Inserted {total_inserted} staged programs in batches of {batch_size}")

    return deleted_count


def _swap_parsed_epg_programs(mapped_epg_ids, epg_source, programs_to_create, batch_size=_EPG_SWAP_BATCH_SIZE):
    """SQLite/dev fallback: atomic delete + bulk insert from an in-memory batch list."""
    with transaction.atomic():
        deleted_count = ProgramData.objects.filter(epg_id__in=mapped_epg_ids).delete()[0]
        unmapped_epg_ids = list(
            EPGData.objects.filter(epg_source=epg_source)
            .exclude(id__in=mapped_epg_ids)
            .values_list('id', flat=True)
        )
        if unmapped_epg_ids:
            ProgramData.objects.filter(epg_id__in=unmapped_epg_ids).delete()
        for i in range(0, len(programs_to_create), batch_size):
            ProgramData.objects.bulk_create(programs_to_create[i:i + batch_size])
    return deleted_count


def parse_programs_for_source(epg_source, tvg_id=None):
    """
    Parse programs for all MAPPED channels from an EPG source in a single pass.

    This is an optimized version that:
    1. Only processes EPG entries that are actually mapped to channels
    2. Parses the XML file ONCE instead of once per channel
    3. Skips programmes for unmapped channels entirely during parsing

    This dramatically improves performance when an EPG source has many channels
    but only a fraction are mapped.
    """
    # Send initial programs parsing notification
    send_epg_update(epg_source.id, "parsing_programs", 0)
    should_log_memory = False
    process = None
    initial_memory = 0
    source_file = None

    # Add memory tracking only in trace mode or higher
    try:
        # Get current log level as a number
        current_log_level = logger.getEffectiveLevel()

        # Only track memory usage when log level is TRACE or more verbose
        should_log_memory = current_log_level <= 5 or settings.DEBUG  # Assuming TRACE is level 5 or lower

        if should_log_memory:
            process = psutil.Process()
            initial_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"[parse_programs_for_source] Initial memory usage: {initial_memory:.2f} MB")
    except ImportError:
        logger.warning("psutil not available for memory tracking")
        process = None
        should_log_memory = False

    try:
        # Only get EPG entries that are actually mapped to channels
        mapped_epg_ids = set(
            Channel.objects.filter(
                epg_data__epg_source=epg_source,
                epg_data__isnull=False
            ).values_list('epg_data_id', flat=True)
        )

        if not mapped_epg_ids:
            total_epg_count = EPGData.objects.filter(epg_source=epg_source).count()
            logger.info(f"No channels mapped to any EPG entries from source: {epg_source.name} "
                       f"(source has {total_epg_count} EPG entries, 0 mapped)")
            # Update status - this is not an error, just no mapped entries
            epg_source.status = 'success'
            epg_source.last_message = f"No channels mapped to this EPG source ({total_epg_count} entries available)"
            epg_source.save(update_fields=['status', 'last_message'])
            send_epg_update(epg_source.id, "parsing_programs", 100, status="success")
            return True

        # Get the mapped EPG entries with their tvg_ids
        mapped_epgs = EPGData.objects.filter(id__in=mapped_epg_ids).values('id', 'tvg_id')
        tvg_id_to_epg_id = {epg['tvg_id']: epg['id'] for epg in mapped_epgs if epg['tvg_id']}
        mapped_tvg_ids = set(tvg_id_to_epg_id.keys())

        total_epg_count = EPGData.objects.filter(epg_source=epg_source).count()
        mapped_count = len(mapped_tvg_ids)

        logger.info(f"Parsing programs for {mapped_count} MAPPED channels from source: {epg_source.name} "
                   f"(skipping {total_epg_count - mapped_count} unmapped EPG entries)")

        # Get the file path
        file_path = epg_source.extracted_file_path if epg_source.extracted_file_path else epg_source.file_path
        if not file_path:
            file_path = epg_source.get_cache_file()

        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(f"EPG file not found at: {file_path}")

            if epg_source.url:
                # Update the file path in the database
                new_path = epg_source.get_cache_file()
                logger.info(f"Updating file_path from '{file_path}' to '{new_path}'")
                epg_source.file_path = new_path
                epg_source.save(update_fields=['file_path'])
                logger.info(f"Fetching new EPG data from URL: {epg_source.url}")

                # Fetch new data before continuing
                fetch_success = fetch_xmltv(epg_source)

                if not fetch_success:
                    logger.error(f"Failed to fetch EPG data for source: {epg_source.name}")
                    epg_source.status = 'error'
                    epg_source.last_message = f"Failed to download EPG data"
                    epg_source.save(update_fields=['status', 'last_message'])
                    send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="Failed to download EPG file")
                    return False

                # Update file_path with the new location
                file_path = epg_source.extracted_file_path if epg_source.extracted_file_path else epg_source.file_path
            else:
                logger.error(f"No URL provided for EPG source {epg_source.name}, cannot fetch new data")
                epg_source.status = 'error'
                epg_source.last_message = f"No URL provided, cannot fetch EPG data"
                epg_source.save(update_fields=['status', 'last_message'])
                send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="No URL provided")
                return False

        # Stream parsed rows into a session temp table, then swap in a short transaction.
        # This bounds Python memory (batched staging inserts) and Postgres memory (no
        # long-lived transaction spanning the entire XML parse).
        programs_by_channel = {tvg_id: 0 for tvg_id in mapped_tvg_ids}
        total_programs = 0
        skipped_programs = 0
        last_progress_update = 0
        parse_batch_size = _EPG_PARSE_BATCH_SIZE
        swap_batch_size = _EPG_SWAP_BATCH_SIZE
        programs_batch = []
        deleted_count = 0
        staging_prepared = False
        use_staging = False
        programs_accumulator = []

        send_epg_update(epg_source.id, "parsing_programs", 10, message="Parsing programs...")

        try:
            staging_prepared = _prepare_epg_program_staging_table()
            use_staging = staging_prepared

            logger.debug(f"Opening file for streaming parse: {file_path}")
            source_file = _open_xmltv_file(file_path)
            try:
                program_parser = etree.iterparse(
                    source_file,
                    events=('end',),
                    tag='programme',
                    remove_blank_text=True,
                    recover=True,
                )

                for _, elem in program_parser:
                    channel_id = elem.get('channel')

                    if channel_id not in mapped_tvg_ids:
                        skipped_programs += 1
                        clear_element(elem)
                        continue

                    try:
                        start_time = parse_xmltv_time(elem.get('start'))
                        end_time = parse_xmltv_time(elem.get('stop'))
                        title = None
                        desc = None
                        sub_title = None

                        for child in elem:
                            if child.tag == 'title':
                                title = child.text or 'No Title'
                            elif child.tag == 'desc':
                                desc = child.text or ''
                            elif child.tag == 'sub-title':
                                sub_title = child.text or ''

                        if not title:
                            title = 'No Title'

                        custom_props = extract_custom_properties(elem)
                        custom_properties_json = custom_props if custom_props else None

                        if desc:
                            has_season = (custom_properties_json or {}).get('season') is not None
                            has_episode = (custom_properties_json or {}).get('episode') is not None
                            if not has_season or not has_episode:
                                d_season, d_episode, cleaned_desc = extract_season_episode_from_description(desc)
                                if d_season is not None and d_episode is not None:
                                    if custom_properties_json is None:
                                        custom_properties_json = {}
                                    if not has_season:
                                        custom_properties_json['season'] = d_season
                                    if not has_episode:
                                        custom_properties_json['episode'] = d_episode
                                    custom_properties_json['season_episode_source'] = 'description'
                                    desc = cleaned_desc

                        epg_id = tvg_id_to_epg_id[channel_id]
                        programs_batch.append(ProgramData(
                            epg_id=epg_id,
                            start_time=start_time,
                            end_time=end_time,
                            title=title[:255],
                            description=desc,
                            sub_title=sub_title,
                            tvg_id=channel_id,
                            custom_properties=custom_properties_json,
                        ))
                        total_programs += 1
                        programs_by_channel[channel_id] += 1
                        clear_element(elem)

                        if len(programs_batch) >= parse_batch_size:
                            if use_staging:
                                _flush_epg_program_staging_batch(programs_batch)
                                programs_batch = []
                            else:
                                programs_accumulator.extend(programs_batch)
                                programs_batch = []

                        if total_programs - last_progress_update >= 5000:
                            last_progress_update = total_programs
                            progress = min(
                                85,
                                10 + int((total_programs / max(total_programs + 10000, 1)) * 75),
                            )
                            send_epg_update(
                                epg_source.id,
                                "parsing_programs",
                                progress,
                                processed=total_programs,
                                channels=mapped_count,
                                message=f"Staging programs... {total_programs:,}",
                            )

                        if total_programs % 5000 == 0:
                            gc.collect()

                    except Exception as e:
                        logger.error(f"Error processing program for {channel_id}: {e}", exc_info=True)
                        clear_element(elem)
                        continue

                if programs_batch:
                    if use_staging:
                        _flush_epg_program_staging_batch(programs_batch)
                    else:
                        programs_accumulator.extend(programs_batch)
                    programs_batch = []
            finally:
                if source_file:
                    source_file.close()
                    source_file = None

            try:
                send_epg_update(epg_source.id, "parsing_programs", 90, message="Updating database...")
                if use_staging:
                    with transaction.atomic():
                        deleted_count = _swap_staged_epg_programs(
                            mapped_epg_ids, epg_source, batch_size=swap_batch_size
                        )
                else:
                    deleted_count = _swap_parsed_epg_programs(
                        mapped_epg_ids, epg_source, programs_accumulator, batch_size=swap_batch_size
                    )
                    programs_accumulator = []

                logger.info(
                    f"Atomic update complete: deleted {deleted_count}, inserted {total_programs} programs"
                )
            except Exception as db_error:
                logger.error(f"Database error during atomic update: {db_error}", exc_info=True)
                epg_source.status = EPGSource.STATUS_ERROR
                epg_source.last_message = f"Database error: {str(db_error)}"
                epg_source.save(update_fields=['status', 'last_message'])
                send_epg_update(
                    epg_source.id, "parsing_programs", 100, status="error", message=str(db_error)
                )
                return False

        except etree.XMLSyntaxError as xml_error:
            logger.error(f"XML syntax error parsing program data: {xml_error}")
            epg_source.status = EPGSource.STATUS_ERROR
            epg_source.last_message = f"XML parsing error: {str(xml_error)}"
            epg_source.save(update_fields=['status', 'last_message'])
            send_epg_update(epg_source.id, "parsing_programs", 100, status="error", message=str(xml_error))
            return False
        except Exception as parse_error:
            logger.error(f"Error parsing programs from XML: {parse_error}", exc_info=True)
            epg_source.status = EPGSource.STATUS_ERROR
            epg_source.last_message = f"Error parsing programs: {str(parse_error)}"
            epg_source.save(update_fields=['status', 'last_message'])
            send_epg_update(
                epg_source.id, "parsing_programs", 100, status="error", message=str(parse_error)
            )
            return False
        finally:
            programs_batch = None
            programs_accumulator = None
            if staging_prepared:
                try:
                    _clear_epg_program_staging_table()
                except Exception:
                    pass
            gc.collect()

        # Count channels that actually got programs
        channels_with_programs = sum(1 for count in programs_by_channel.values() if count > 0)

        # Success message
        epg_source.status = EPGSource.STATUS_SUCCESS
        epg_source.last_message = (
            f"Parsed {total_programs:,} programs for {channels_with_programs} channels "
            f"(skipped {skipped_programs:,} programs for {total_epg_count - mapped_count} unmapped channels)"
        )
        epg_source.updated_at = timezone.now()
        epg_source.save(update_fields=['status', 'last_message', 'updated_at'])

        # Log system event for EPG refresh
        log_system_event(
            event_type='epg_refresh',
            source_name=epg_source.name,
            programs=total_programs,
            channels=channels_with_programs,
            skipped_programs=skipped_programs,
            unmapped_channels=total_epg_count - mapped_count,
        )

        # Send completion notification with status
        send_epg_update(epg_source.id, "parsing_programs", 100,
                      status="success",
                      message=epg_source.last_message,
                      updated_at=epg_source.updated_at.isoformat())

        logger.info(f"Completed parsing programs for source: {epg_source.name} - "
               f"{total_programs:,} programs for {channels_with_programs} channels, "
               f"skipped {skipped_programs:,} programs for unmapped channels")
        return True

    except Exception as e:
        logger.error(f"Error in parse_programs_for_source: {e}", exc_info=True)
        # Update status to error
        epg_source.status = EPGSource.STATUS_ERROR
        epg_source.last_message = f"Error parsing programs: {str(e)}"
        epg_source.save(update_fields=['status', 'last_message'])
        send_epg_update(epg_source.id, "parsing_programs", 100,
                      status="error",
                      message=epg_source.last_message)
        return False
    finally:
        # Final memory cleanup and tracking
        if source_file:
            try:
                source_file.close()
            except:
                pass
            source_file = None

        # Explicitly release any remaining large data structures
        programs_batch = None
        programs_by_channel = None
        mapped_epg_ids = None
        mapped_tvg_ids = None
        tvg_id_to_epg_id = None
        gc.collect()

        # Add comprehensive memory cleanup at the end
        cleanup_memory(log_usage=should_log_memory, force_collection=True)
        if process:
            final_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"[parse_programs_for_source] Final memory usage: {final_memory:.2f} MB difference: {final_memory - initial_memory:.2f} MB")
            # Explicitly clear the process object to prevent potential memory leaks
            process = None


def _sd_fetch_lineup_country(token, sd_headers_fn):
    """Return country code prefix from the first subscribed lineup (poster metadata)."""
    try:
        lineups_response = requests.get(
            f"{SD_BASE_URL}/lineups",
            headers=sd_headers_fn(token),
            timeout=30,
        )
        if lineups_response.ok:
            for lineup in lineups_response.json().get('lineups', []):
                lid = lineup.get('lineupID') or lineup.get('lineup') or ''
                if '-' in lid:
                    return lid.split('-')[0]
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not fetch lineups for country code: {e}")
    return None


def _sd_setup_single_epg_fetch(source, epg_id, token, sd_headers_fn):
    """Build station_map / epg_id_map for a single mapped EPG entry."""
    epg = EPGData.objects.filter(id=epg_id, epg_source=source).first()
    if not epg or not epg.tvg_id:
        msg = f"Schedules Direct EPG entry {epg_id} not found or missing station ID."
        logger.error(msg)
        source.last_message = msg
        source.save(update_fields=['last_message'])
        send_epg_update(source.id, "parsing_programs", 100, status="error", error=msg)
        return None

    sd_lineup_country = _sd_fetch_lineup_country(token, sd_headers_fn)

    send_epg_update(
        source.id, "parsing_programs", 15,
        message=f"Fetching guide data for {epg.name or epg.tvg_id}...",
    )
    station_map = {epg.tvg_id: {'name': epg.name or epg.tvg_id, 'logo_url': epg.icon_url}}
    epg_id_map = {epg.tvg_id: epg.id}
    return station_map, epg_id_map, sd_lineup_country, epg


def _sd_setup_mapped_guide_fetch(source, token, sd_headers_fn):
    """Build station_map / epg_id_map for all channels mapped to this SD source."""
    from apps.channels.models import Channel

    mapped_epg_ids = set(
        Channel.objects.filter(
            epg_data__epg_source=source,
            epg_data__isnull=False,
        ).values_list('epg_data_id', flat=True)
    )
    if not mapped_epg_ids:
        msg = "No channels mapped to this Schedules Direct source."
        logger.info(msg)
        source.last_message = msg
        source.save(update_fields=['last_message'])
        send_epg_update(source.id, "parsing_programs", 100, status="idle", message=msg)
        return None

    station_map = {}
    epg_id_map = {}
    for epg in EPGData.objects.filter(id__in=mapped_epg_ids, epg_source=source):
        if not epg.tvg_id:
            continue
        station_map[epg.tvg_id] = {
            'name': epg.name or epg.tvg_id,
            'logo_url': epg.icon_url,
        }
        epg_id_map[epg.tvg_id] = epg.id

    if not station_map:
        msg = "Mapped channels have no valid Schedules Direct station IDs."
        logger.warning(msg)
        source.last_message = msg
        source.save(update_fields=['last_message'])
        send_epg_update(source.id, "parsing_programs", 100, status="error", error=msg)
        return None

    sd_lineup_country = _sd_fetch_lineup_country(token, sd_headers_fn)
    send_epg_update(
        source.id, "parsing_programs", 15,
        message=f"Fetching guide data for {len(station_map)} mapped stations...",
    )
    return station_map, epg_id_map, sd_lineup_country


def dispatch_program_refresh_for_epg_ids(epg_ids):
    """
    Queue guide/program refresh for newly assigned EPGData rows.

    XMLTV and other non-SD sources use parse_programs_for_tvg_id per id.
    Schedules Direct uses per-EPG fetches for small batches and one batched
    mapped-station fetch per source when the threshold is exceeded.
    """
    if not epg_ids:
        return 0

    epg_ids = {eid for eid in epg_ids if eid}
    if not epg_ids:
        return 0

    epgs = list(
        EPGData.objects.filter(id__in=epg_ids).select_related('epg_source')
    )
    epgs_with_program_data = set(
        ProgramData.objects.filter(epg_id__in=epg_ids)
        .values_list('epg_id', flat=True)
        .distinct()
    )

    non_sd_epg_ids = []
    sd_by_source = {}
    for epg in epgs:
        if not epg.epg_source:
            non_sd_epg_ids.append(epg.id)
            continue
        source_type = epg.epg_source.source_type
        if source_type == 'dummy':
            continue
        if source_type == 'schedules_direct':
            sd_by_source.setdefault(epg.epg_source_id, []).append(epg)
        else:
            non_sd_epg_ids.append(epg.id)

    dispatched = 0
    for epg_id in non_sd_epg_ids:
        parse_programs_for_tvg_id.delay(epg_id)
        dispatched += 1

    for source_id, source_epgs in sd_by_source.items():
        needs_fetch = [
            epg for epg in source_epgs
            if epg.id not in epgs_with_program_data
        ]
        if not needs_fetch:
            continue
        if len(needs_fetch) >= SD_BULK_GUIDE_FETCH_THRESHOLD:
            logger.info(
                f"SD source {source_id}: {len(needs_fetch)} new mapping(s) exceed "
                f"threshold ({SD_BULK_GUIDE_FETCH_THRESHOLD}); "
                "queueing batched mapped guide fetch"
            )
            fetch_sd_mapped_guide_batch.delay(source_id)
            dispatched += 1
        else:
            for epg in needs_fetch:
                parse_programs_for_tvg_id.delay(epg.id)
                dispatched += 1

    return dispatched


@shared_task(time_limit=3600, soft_time_limit=3500)
def fetch_sd_mapped_guide_batch(source_id, force=False, _defer_retry=0):
    """
    Fetch Schedules Direct guide data for all mapped stations on one source.

    Used when bulk EPG assignment would otherwise queue many per-EPG tasks.
    """
    try:
        source = EPGSource.objects.get(id=source_id)
    except EPGSource.DoesNotExist:
        logger.error(f"EPGSource {source_id} not found for SD mapped guide batch")
        return

    if source.source_type != 'schedules_direct':
        return "Not a Schedules Direct source"

    if not acquire_task_lock('sd_mapped_guide_fetch', source_id):
        if _defer_retry < SD_MAPPED_GUIDE_FETCH_DEFER_MAX_RETRIES:
            logger.info(
                f"SD mapped guide batch for source {source_id} already in progress, "
                f"deferring retry {_defer_retry + 1}/"
                f"{SD_MAPPED_GUIDE_FETCH_DEFER_MAX_RETRIES}"
            )
            fetch_sd_mapped_guide_batch.apply_async(
                args=[source_id],
                kwargs={
                    'force': force,
                    '_defer_retry': _defer_retry + 1,
                },
                countdown=SD_MAPPED_GUIDE_BATCH_DEFER_SECONDS,
            )
            return "Deferred - batch already in progress"
        logger.warning(
            f"SD mapped guide batch for source {source_id} still locked after "
            f"{_defer_retry} deferrals; giving up"
        )
        return "Task already running"

    lock_renewer = TaskLockRenewer('sd_mapped_guide_fetch', source_id)
    lock_renewer.start()
    try:
        logger.info(f"Fetching Schedules Direct guide for mapped stations (source: {source.name})")
        fetch_schedules_direct(source, mapped_guide_batch=True, force=force)
        return "SD mapped guide batch complete"
    finally:
        lock_renewer.stop()
        release_task_lock('sd_mapped_guide_fetch', source_id)


@shared_task(time_limit=3600, soft_time_limit=3500)
def fetch_sd_guide_for_epg(epg_id, force=False, _defer_retry=0):
    """
    Fetch Schedules Direct guide data for one mapped EPG entry (channel map flow).

    Skips when ProgramData already exists so additional channels sharing the
    same EPGData / tvg_id do not trigger redundant API calls.
    """
    epg = EPGData.objects.select_related('epg_source').filter(id=epg_id).first()
    if not epg or not epg.epg_source or epg.epg_source.source_type != 'schedules_direct':
        return "Not a Schedules Direct EPG entry"

    if not force and ProgramData.objects.filter(epg_id=epg_id).exists():
        logger.info(f"SD guide fetch skipped for EPG {epg_id}: ProgramData already present")
        return "Guide data already present"

    source_id = epg.epg_source_id
    if is_task_lock_held('sd_mapped_guide_fetch', source_id):
        if _defer_retry < SD_MAPPED_GUIDE_FETCH_DEFER_MAX_RETRIES:
            logger.info(
                f"SD mapped batch in progress for source {source_id}; "
                f"deferring single-EPG fetch for {epg_id} "
                f"(retry {_defer_retry + 1}/{SD_MAPPED_GUIDE_FETCH_DEFER_MAX_RETRIES})"
            )
            fetch_sd_guide_for_epg.apply_async(
                args=[epg_id],
                kwargs={
                    'force': force,
                    '_defer_retry': _defer_retry + 1,
                },
                countdown=SD_MAPPED_GUIDE_BATCH_DEFER_SECONDS,
            )
            return "Deferred - mapped batch in progress"
        logger.warning(
            f"SD mapped batch still running for source {source_id} after "
            f"{_defer_retry} deferrals; proceeding with single-EPG fetch for {epg_id}"
        )

    if not acquire_task_lock('parse_epg_programs', epg_id):
        logger.info(f"SD guide fetch for EPG {epg_id} already in progress, skipping duplicate task")
        return "Task already running"

    lock_renewer = TaskLockRenewer('parse_epg_programs', epg_id)
    lock_renewer.start()
    try:
        logger.info(f"Fetching Schedules Direct guide for EPG {epg_id} ({epg.tvg_id})")
        fetch_schedules_direct(epg.epg_source, epg_id_only=epg_id, force=force)
        return "SD guide fetch complete"
    finally:
        lock_renewer.stop()
        release_task_lock('parse_epg_programs', epg_id)


@shared_task(bind=True)
def fetch_schedules_direct_stations(self, source_id):
    """
    Lightweight Celery task that runs a stations-only Schedules Direct fetch.
    Called on initial source creation so EPGData entries exist for auto-matching
    before the user commits to a full schedule/program fetch.
    """
    try:
        source = EPGSource.objects.get(id=source_id)
    except EPGSource.DoesNotExist:
        logger.error(f"EPGSource {source_id} not found for SD stations fetch")
        return
    fetch_schedules_direct(source, stations_only=True)


def fetch_schedules_direct(
    source,
    stations_only=False,
    force=False,
    epg_id_only=None,
    mapped_guide_batch=False,
):
    """
    Fetch EPG data from the Schedules Direct JSON API and persist it to the
    EPGData / ProgramData models.

    Authentication flow (as required by the SD API specification):
      1. POST credentials to the token endpoint (password must be SHA1-hashed
         as required by the Schedules Direct API specification.
      2. Use the returned token for all subsequent requests via the 'token' header.
      3. Tokens are valid for 24 hours; SD returns the current valid token if one
         already exists for the account.

    Data flow:
      1. Fetch subscribed lineups for the account.
      2. Fetch station metadata for each lineup.
      3. Persist station metadata to EPGData.
      4. If stations_only=True, stop here. Used on initial source creation so
         the user can run Auto-match EPG before the full program fetch.
      5. Fetch schedule grids in 14-day date-batched requests per station.
      6. Fetch program metadata in batched requests (up to 5000 programIDs per request).
      7. Persist channels to EPGData and programs to ProgramData.

    Args:
        source: EPGSource instance
        stations_only: If True, only fetch and persist station metadata (no schedules/programs).
                      Used on initial source creation to populate EPGData for auto-matching
                      before channels are assigned.
    """
    import hashlib
    from datetime import date

    single_epg_fetch = epg_id_only is not None
    lightweight_sd_fetch = single_epg_fetch or mapped_guide_batch

    if single_epg_fetch:
        logger.info(
            f"Fetching Schedules Direct guide for EPG {epg_id_only} "
            f"(source: {source.name})"
        )
    elif mapped_guide_batch:
        logger.info(
            f"Fetching Schedules Direct guide for mapped stations "
            f"(source: {source.name})"
        )
    else:
        logger.info(f"Fetching Schedules Direct data for source: {source.name}")

    # -------------------------------------------------------------------------
    # Validate credentials
    # -------------------------------------------------------------------------
    username = (source.username or '').strip()
    password = (source.password or '').strip()

    if not username or not password:
        msg = "Schedules Direct source requires both a username and password."
        logger.error(msg)
        source.status = EPGSource.STATUS_ERROR
        source.last_message = msg
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "refresh", 100, status="error", error=msg)
        return

    # -------------------------------------------------------------------------
    # Enforce 2-hour minimum interval between full fetches (not stations-only).
    # Schedules Direct enforces rate limits of ~200 requests per 2-hour window.
    # This prevents automated abuse regardless of how the refresh was triggered.
    #
    # Exception: if no SDScheduleMD5 records exist yet, this is the first full
    # refresh after initial source creation (stations-only runs first and updates
    # updated_at, which would otherwise incorrectly trigger this guard). Always
    # allow the first full refresh through so guide data is immediately available.
    # -------------------------------------------------------------------------
    if not stations_only and not force and not lightweight_sd_fetch and source.updated_at:
        from apps.epg.models import SDScheduleMD5 as _SDScheduleMD5
        has_prior_full_refresh = _SDScheduleMD5.objects.filter(epg_source=source).exists()
        if has_prior_full_refresh:
            elapsed = (timezone.now() - source.updated_at).total_seconds()
            min_interval_seconds = 2 * 3600  # 2 hours
            if elapsed < min_interval_seconds:
                remaining_minutes = int((min_interval_seconds - elapsed) / 60)
                msg = (
                    f"Schedules Direct refresh skipped. Minimum 2-hour interval not reached. "
                    f"Last refreshed {int(elapsed / 60)} minutes ago. "
                    f"Please wait {remaining_minutes} more minute(s)."
                )
                logger.warning(f"SD source {source.id}: {msg}")
                source.status = EPGSource.STATUS_IDLE
                source.last_message = msg
                source.save(update_fields=['status', 'last_message'])
                send_epg_update(source.id, "refresh", 100, status="idle", message=msg)
                return
        else:
            logger.info(f"SD source {source.id}: No prior full refresh detected, skipping 2-hour guard for first full fetch.")
    elif force and not stations_only and not lightweight_sd_fetch:
        logger.info(f"SD source {source.id}: Force flag set, bypassing 2-hour refresh guard.")

    # -------------------------------------------------------------------------
    # Build SD-specific headers
    # SD API spec requires the User-Agent to identify the application and version.
    # SergeantPanda confirmed Dispatcharr should identify itself properly.
    # -------------------------------------------------------------------------
    from core.utils import dispatcharr_http_headers

    def _sd_headers(token=None):
        return dispatcharr_http_headers(token=token)

    def _sd_post_refresh_tasks(mapped_epg_ids, program_metadata, today):
        """Poster fetch, logo auto-apply, and pruning — runs even when schedules are unchanged."""
        from apps.epg.models import SDProgramMD5

        fetch_posters = (source.custom_properties or {}).get('fetch_posters', False)
        poster_style = (source.custom_properties or {}).get('poster_style', SD_POSTER_STYLE_DEFAULT)
        poster_program_ids = set()
        if fetch_posters:
            needs_poster_q = (
                Q(custom_properties__isnull=True)
                | ~Q(custom_properties__has_key='sd_icon')
                | ~Q(custom_properties__sd_poster_style=poster_style)
            )
            poster_program_ids = set(
                ProgramData.objects.filter(
                    epg_id__in=mapped_epg_ids,
                    program_id__isnull=False,
                ).filter(needs_poster_q).values_list('program_id', flat=True)
            )
            if poster_program_ids:
                logger.info(
                    f"Poster fetch: {len(poster_program_ids)} programs need artwork "
                    f"(missing, style change, or first fetch; style={poster_style})."
                )

        if fetch_posters and poster_program_ids:
            logger.info("Poster fetch enabled, retrieving program artwork from Schedules Direct.")
            send_epg_update(source.id, "parsing_programs", 98,
                            message="Fetching program artwork...")
            try:
                artwork_lookup_ids = set()
                pid_to_artwork_key = {}
                for pid in poster_program_ids:
                    if pid.startswith('EP'):
                        sh_root = 'SH' + pid[2:10] + '0000'
                        artwork_lookup_ids.add(sh_root)
                        pid_to_artwork_key[pid] = sh_root
                    else:
                        artwork_lookup_ids.add(pid)
                        pid_to_artwork_key[pid] = pid

                artwork_map = {}
                artwork_list = list(artwork_lookup_ids)
                SD_ARTWORK_BATCH_SIZE = 500
                total_art_batches = max(1, (len(artwork_list) + SD_ARTWORK_BATCH_SIZE - 1) // SD_ARTWORK_BATCH_SIZE)
                logger.info(f"Fetching artwork index for {len(artwork_list)} unique program/series IDs "
                            f"in {total_art_batches} batch(es).")

                for batch_idx in range(total_art_batches):
                    batch = artwork_list[batch_idx * SD_ARTWORK_BATCH_SIZE:(batch_idx + 1) * SD_ARTWORK_BATCH_SIZE]
                    try:
                        art_response = requests.post(
                            f"{SD_BASE_URL}/metadata/programs/",
                            json=batch,
                            headers=_sd_headers(token),
                            timeout=120,
                        )
                        art_response.raise_for_status()
                        art_data = art_response.json()

                        for entry in art_data:
                            if not isinstance(entry, dict):
                                continue
                            entry_pid = entry.get('programID')
                            images = entry.get('data') or []
                            if not entry_pid or not images:
                                continue
                            images = [img for img in images if isinstance(img, dict)]
                            if not images:
                                continue

                            poster_url = _sd_pick_poster_url(images, poster_style)
                            if poster_url:
                                if not poster_url.startswith('http'):
                                    poster_url = f"{SD_BASE_URL}/image/{poster_url}"
                                artwork_map[entry_pid] = poster_url

                        logger.info(f"Artwork batch {batch_idx + 1}/{total_art_batches}: "
                                    f"{len(artwork_map)} posters found so far.")
                    except requests.exceptions.RequestException as e:
                        logger.warning(f"Failed to fetch artwork batch {batch_idx + 1}: {e}")

                if artwork_map:
                    programs_to_update = []
                    for prog in ProgramData.objects.filter(
                        epg_id__in=mapped_epg_ids,
                        program_id__in=poster_program_ids,
                        program_id__isnull=False,
                    ).only('id', 'program_id', 'custom_properties'):
                        art_key = pid_to_artwork_key.get(prog.program_id)
                        poster = artwork_map.get(art_key) if art_key else None
                        if poster:
                            cp = prog.custom_properties or {}
                            cp['sd_icon'] = poster
                            cp['sd_poster_style'] = poster_style
                            prog.custom_properties = cp
                            programs_to_update.append(prog)
                    if programs_to_update:
                        ProgramData.objects.bulk_update(
                            programs_to_update, ['custom_properties'], batch_size=1000
                        )
                        logger.info(f"Updated {len(programs_to_update)} programs with poster artwork.")
                    else:
                        logger.info("No poster artwork matched committed programs.")
                else:
                    logger.info("No poster artwork found from Schedules Direct.")
            except Exception as art_error:
                logger.warning(f"Poster artwork fetch failed (non-fatal): {art_error}", exc_info=True)
        elif fetch_posters:
            logger.info("Poster fetch enabled but all mapped programs already have artwork.")

        from apps.channels.utils import maybe_auto_apply_epg_logos
        maybe_auto_apply_epg_logos(source)

        try:
            unmapped_epg_ids = list(
                EPGData.objects.filter(epg_source=source).exclude(
                    id__in=mapped_epg_ids,
                ).values_list('id', flat=True)
            )
            if unmapped_epg_ids:
                orphaned_count = ProgramData.objects.filter(
                    epg_id__in=unmapped_epg_ids,
                ).delete()[0]
                if orphaned_count:
                    logger.info(
                        f"Cleaned up {orphaned_count} orphaned ProgramData records "
                        f"for {len(unmapped_epg_ids)} unmapped EPG entries."
                    )
        except Exception as prune_err:
            logger.warning(f"Failed to clean up orphaned SD ProgramData: {prune_err}")

        today_utc = datetime(today.year, today.month, today.day, tzinfo=dt_timezone.utc)
        try:
            expired_count = ProgramData.objects.filter(epg_id__in=mapped_epg_ids, end_time__lt=today_utc).delete()[0]
            if expired_count:
                logger.info(f"Pruned {expired_count} expired SD ProgramData records (end_time before {today}).")
        except Exception as prune_err:
            logger.warning(f"Failed to prune expired SD ProgramData: {prune_err}")

        try:
            live_program_ids = set(
                ProgramData.objects.filter(epg_id__in=mapped_epg_ids, program_id__isnull=False)
                .values_list('program_id', flat=True)
            )
            pruned_prog_md5_count = SDProgramMD5.objects.filter(epg_source=source).exclude(
                program_id__in=live_program_ids
            ).delete()[0]
            if pruned_prog_md5_count:
                logger.info(f"Pruned {pruned_prog_md5_count} stale SDProgramMD5 records no longer referenced by live ProgramData.")
        except Exception as prune_err:
            logger.warning(f"Failed to prune stale SDProgramMD5 records: {prune_err}")

    # -------------------------------------------------------------------------
    # Step 1: Authenticate and obtain session token
    # The SD API requires the password to be SHA1-hashed before transmission.
    # This is a requirement of the Schedules Direct API specification, not an
    # architectural choice.
    # -------------------------------------------------------------------------
    if not lightweight_sd_fetch:
        source.status = EPGSource.STATUS_FETCHING
        source.last_message = "Authenticating with Schedules Direct..."
        source.save(update_fields=['status', 'last_message'])
    send_epg_update(source.id, "parsing_programs", 2, message="Authenticating with Schedules Direct...")

    try:
        sha1_password = hashlib.sha1(password.encode('utf-8')).hexdigest()
        token_response = requests.post(
            f"{SD_BASE_URL}/token",
            json={'username': username, 'password': sha1_password},
            headers=_sd_headers(),
            timeout=30,
        )
        # Parse the response body first so we can surface SD's own error message
        # regardless of HTTP status code (SD sometimes returns 400 for app-level
        # errors like SERVICE_OFFLINE that carry a meaningful JSON body).
        try:
            token_data = token_response.json()
        except Exception:
            token_response.raise_for_status()
            raise

        auth_code = token_data.get('code', 0)
        if not token_response.ok or auth_code != 0:
            if auth_code == 3000:
                msg = "Schedules Direct is offline for maintenance. Try again later."
            elif auth_code == 4007:
                msg = "Schedules Direct: this application is not authorized. Please contact the Dispatcharr maintainers."
            elif auth_code == 4004:
                msg = "Schedules Direct: account locked due to too many failed login attempts. Try again in 15 minutes."
            elif auth_code == 4009:
                msg = "Schedules Direct: too many login attempts in 24 hours. Token is valid for 24 hours. Check for misconfiguration."
            elif auth_code == 4001:
                msg = "Schedules Direct: account has expired. Please renew your subscription at schedulesdirect.org."
            elif auth_code == 4008:
                msg = "Schedules Direct: account is inactive. Please log in to schedulesdirect.org to reactivate."
            elif auth_code == 4003:
                msg = "Schedules Direct: invalid username or password."
            elif auth_code != 0:
                msg = f"Schedules Direct authentication failed (code {auth_code}): {token_data.get('message', 'Unknown error')}"
            else:
                token_response.raise_for_status()
                raise RuntimeError(f"Unexpected SD token response: {token_response.text}")
            logger.error(msg)
            source.status = EPGSource.STATUS_ERROR
            source.last_message = msg
            source.save(update_fields=['status', 'last_message'])
            send_epg_update(source.id, "refresh", 100, status="error", error=msg)
            return

        token = token_data.get('token')
        if not token:
            msg = "Schedules Direct returned no token."
            logger.error(msg)
            source.status = EPGSource.STATUS_ERROR
            source.last_message = msg
            source.save(update_fields=['status', 'last_message'])
            send_epg_update(source.id, "refresh", 100, status="error", error=msg)
            return

        logger.info("Schedules Direct authentication successful.")

    except requests.exceptions.RequestException as e:
        msg = f"Network error authenticating with Schedules Direct: {e}"
        logger.error(msg, exc_info=True)
        source.status = EPGSource.STATUS_ERROR
        source.last_message = msg
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "refresh", 100, status="error", error=msg)
        return

    # -------------------------------------------------------------------------
    # Step 2: Check account status (respect OFFLINE system status)
    # -------------------------------------------------------------------------
    try:
        status_response = requests.get(
            f"{SD_BASE_URL}/status",
            headers=_sd_headers(token),
            timeout=30,
        )
        status_response.raise_for_status()
        status_data = status_response.json()
        system_status = status_data.get('systemStatus', [{}])[0].get('status', 'Online')
        if system_status == 'Offline':
            # Per SD API spec: if system is offline, disconnect and do not
            # retry for 1 hour. We set idle status rather than error since
            # this is a temporary SD-side condition.
            msg = "Schedules Direct system is currently offline. Per SD guidelines, retrying in 1 hour."
            logger.warning(msg)
            source.status = EPGSource.STATUS_IDLE
            source.last_message = msg
            source.save(update_fields=['status', 'last_message'])
            send_epg_update(source.id, "refresh", 100, status="idle", message=msg)
            return
        logger.debug(f"Schedules Direct system status: {system_status}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not fetch SD system status, proceeding anyway: {e}")

    station_map = None
    epg_id_map = None
    sd_lineup_country = None

    if epg_id_only is not None:
        setup = _sd_setup_single_epg_fetch(source, epg_id_only, token, _sd_headers)
        if setup is None:
            return
        station_map, epg_id_map, sd_lineup_country, _single_epg = setup
    elif mapped_guide_batch:
        setup = _sd_setup_mapped_guide_fetch(source, token, _sd_headers)
        if setup is None:
            return
        station_map, epg_id_map, sd_lineup_country = setup
    else:
        # -------------------------------------------------------------------------
        # Step 3: Fetch subscribed lineups and build station map
        # -------------------------------------------------------------------------
        send_epg_update(source.id, "parsing_programs", 10, message="Fetching subscribed lineups...")
        try:
            lineups_response = requests.get(
                f"{SD_BASE_URL}/lineups",
                headers=_sd_headers(token),
                timeout=30,
            )
            # SD returns 400 with code 4102 when no lineups are configured.
            # This is a valid account state. The user needs to add lineups via
            # the Manage Lineups UI. Treat as idle rather than error.
            if lineups_response.status_code == 400:
                sd_data = lineups_response.json()
                if sd_data.get('code') == 4102:
                    msg = "No lineups configured. Use the Manage Lineups option in the EPG source settings to add a lineup."
                    logger.warning(f"SD source {source.id}: no lineups configured on account (4102).")
                    source.status = EPGSource.STATUS_IDLE
                    source.last_message = msg
                    source.save(update_fields=['status', 'last_message'])
                    send_epg_update(source.id, "refresh", 100, status="idle", message=msg)
                    return
            lineups_response.raise_for_status()
            lineups_data = lineups_response.json()
            lineups = [l for l in lineups_data.get('lineups', []) if not l.get('isDeleted', False)]
            if not lineups:
                msg = "No lineups configured. Use the Manage Lineups option in the EPG source settings to add a lineup."
                logger.warning(f"SD source {source.id}: no active lineups found.")
                source.status = EPGSource.STATUS_IDLE
                source.last_message = msg
                source.save(update_fields=['status', 'last_message'])
                send_epg_update(source.id, "refresh", 100, status="idle", message=msg)
                return
            logger.info(f"Found {len(lineups)} lineup(s) in SD account.")

            # Extract country from lineup IDs (format: "USA-NJ29486-X", "GBR-...", etc.)
            sd_lineup_country = None
            for l in lineups:
                lid = l.get('lineupID') or l.get('lineup') or ''
                if '-' in lid:
                    sd_lineup_country = lid.split('-')[0]
                    break
            logger.debug(f"SD lineup country: {sd_lineup_country}")
        except requests.exceptions.RequestException as e:
            msg = f"Failed to fetch Schedules Direct lineups: {e}"
            logger.error(msg, exc_info=True)
            source.status = EPGSource.STATUS_ERROR
            source.last_message = msg
            source.save(update_fields=['status', 'last_message'])
            send_epg_update(source.id, "refresh", 100, status="error", error=msg)
            return

        # Build station metadata map: stationID -> {name, callsign, logo_url}
        station_map = {}
        send_epg_update(source.id, "parsing_programs", 18, message=f"Fetching station metadata for {len(lineups)} lineup(s)...")
        for lineup in lineups:
            lineup_id = lineup.get('lineupID') or lineup.get('lineup')
            if not lineup_id:
                continue
            lineup_name = lineup.get('name') or lineup_id
            try:
                detail_response = requests.get(
                    f"{SD_BASE_URL}/lineups/{lineup_id}",
                    headers=_sd_headers(token),
                    timeout=30,
                )
                detail_response.raise_for_status()
                detail_data = detail_response.json()
                for station in detail_data.get('stations', []):
                    sid = station.get('stationID')
                    if not sid:
                        continue
                    logo_url = None
                    logos = station.get('stationLogo') or station.get('logo') or []
                    if isinstance(logos, list) and logos:
                        # Read preferred logo style from source settings; default to 'dark'
                        logo_style = (source.custom_properties or {}).get('logo_style', 'dark')
                        preferred = next((l for l in logos if l.get('category') == logo_style), logos[0])
                        logo_url = preferred.get('URL') or preferred.get('url')
                    elif isinstance(logos, dict):
                        logo_url = logos.get('URL') or logos.get('url')
                    station_map[sid] = {
                        'name': station.get('name', sid),
                        'callsign': station.get('callsign', ''),
                        'logo_url': logo_url,
                        # Preserve lineup from first encounter if station appears in multiple lineups
                        'lineup': station_map.get(sid, {}).get('lineup') or lineup_name,
                    }
                logger.debug(f"Fetched {len(detail_data.get('stations', []))} stations from lineup {lineup_id}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to fetch lineup details for {lineup_id}: {e}")

        if not station_map:
            msg = "No stations found across all Schedules Direct lineups."
            logger.warning(msg)
            source.status = EPGSource.STATUS_ERROR
            source.last_message = msg
            source.save(update_fields=['status', 'last_message'])
            send_epg_update(source.id, "refresh", 100, status="error", error=msg)
            return

        logger.info(f"Built station map with {len(station_map)} stations.")

        # -------------------------------------------------------------------------
        # Step 4: Persist station metadata to EPGData
        # -------------------------------------------------------------------------
        source.status = EPGSource.STATUS_PARSING
        source.last_message = f"Syncing {len(station_map)} stations..."
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "parsing_programs", 28, message=f"Syncing {len(station_map)} stations to database...")

        existing_epg_map = {
            epg.tvg_id: epg
            for epg in EPGData.objects.filter(epg_source=source)
        }

        epgs_to_create = []
        epgs_to_update = []
        icon_max_length = EPGData._meta.get_field('icon_url').max_length
        name_max_length = EPGData._meta.get_field('name').max_length

        for sid, info in station_map.items():
            display_name = (info['name'] or sid)[:name_max_length]
            logo = info['logo_url']
            if logo and len(logo) > icon_max_length:
                logo = None
            lineup_val = info.get('lineup')

            if sid in existing_epg_map:
                epg_obj = existing_epg_map[sid]
                needs_update = False
                if epg_obj.name != display_name:
                    epg_obj.name = display_name
                    needs_update = True
                if epg_obj.icon_url != logo:
                    epg_obj.icon_url = logo
                    needs_update = True
                if epg_obj.lineup != lineup_val:
                    epg_obj.lineup = lineup_val
                    needs_update = True
                if needs_update:
                    epgs_to_update.append(epg_obj)
            else:
                epgs_to_create.append(EPGData(
                    tvg_id=sid,
                    name=display_name,
                    icon_url=logo,
                    lineup=lineup_val,
                    epg_source=source,
                ))

        if epgs_to_create:
            EPGData.objects.bulk_create(epgs_to_create, ignore_conflicts=True)
            logger.info(f"Created {len(epgs_to_create)} new EPGData entries.")
        if epgs_to_update:
            EPGData.objects.bulk_update(epgs_to_update, ['name', 'icon_url', 'lineup'])
            logger.info(f"Updated {len(epgs_to_update)} existing EPGData entries.")

        gc.collect()

        # Rebuild map with fresh DB ids for all stations
        epg_id_map = {
            epg.tvg_id: epg.id
            for epg in EPGData.objects.filter(epg_source=source, tvg_id__in=list(station_map.keys()))
        }

        # Station sync complete. Send progress update before continuing into programs phase.
        # We deliberately do NOT send parsing_channels at 100 with status=success here
        # because that would cause the frontend to mark the source as complete and
        # stop rendering progress updates for the subsequent program fetch phases.
        send_epg_update(source.id, "parsing_programs", 30,
                        message=f"Stations synced ({len(station_map)} stations). Preparing schedule fetch...")

        # -------------------------------------------------------------------------
        # Stations-only mode. Used on initial source creation.
        # Stop here so the user can run Auto-match EPG before the full program fetch.
        # -------------------------------------------------------------------------
        if stations_only:
            success_msg = (
                f"{len(station_map)} stations loaded from Schedules Direct. "
                f"Run Auto-match EPG to map your channels, then use the Refresh "
                f"button to populate guide data."
            )
            source.status = EPGSource.STATUS_SUCCESS
            source.last_message = success_msg
            source.updated_at = timezone.now()
            source.save(update_fields=['status', 'last_message', 'updated_at'])
            send_epg_update(source.id, "parsing_channels", 100, status="success",
                            message=success_msg, channels_count=len(station_map))
            logger.info(f"Stations-only fetch complete for source: {source.name} ({len(station_map)} stations)")
            return

    # -------------------------------------------------------------------------
    # Step 5: MD5-delta schedule fetch
    # Only mapped channels need guide data. Fetch MD5 hashes and schedules for
    # mapped stations only; never cache schedule MD5s for unmapped lineup entries.
    # -------------------------------------------------------------------------
    from django.utils.dateparse import parse_datetime

    station_ids = list(station_map.keys())
    today = date.today()
    date_list = [(today + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(SD_DAYS_TO_FETCH)]

    mapped_epg_ids = set(
        Channel.objects.filter(
            epg_data__epg_source=source,
            epg_data__isnull=False,
        ).values_list('epg_data_id', flat=True)
    )
    mapped_tvg_ids = set(
        EPGData.objects.filter(
            id__in=mapped_epg_ids,
            epg_source=source,
        ).values_list('tvg_id', flat=True)
    )
    mapped_station_ids = [sid for sid in station_ids if sid in mapped_tvg_ids]

    # Prune expired schedule MD5s and drop cache for unmapped stations.
    pruned_sched_md5_count = SDScheduleMD5.objects.filter(
        epg_source=source, date__lt=today,
    ).delete()[0]
    if pruned_sched_md5_count:
        logger.info(f"Pruned {pruned_sched_md5_count} expired SDScheduleMD5 records (before {today}).")

    if mapped_tvg_ids:
        unmapped_cache_pruned = SDScheduleMD5.objects.filter(
            epg_source=source,
        ).exclude(station_id__in=mapped_tvg_ids).delete()[0]
    else:
        unmapped_cache_pruned = SDScheduleMD5.objects.filter(epg_source=source).delete()[0]
    if unmapped_cache_pruned:
        logger.info(f"Pruned {unmapped_cache_pruned} SDScheduleMD5 records for unmapped lineup stations.")

    if not mapped_station_ids:
        logger.info("No channels mapped to this SD source; skipping schedule MD5 check and downloads.")
        _sd_post_refresh_tasks(mapped_epg_ids, {}, today)
        if single_epg_fetch:
            msg = "No mapped channel found for this EPG entry; guide fetch skipped."
            source.last_message = msg
            source.save(update_fields=['last_message'])
            send_epg_update(source.id, "parsing_programs", 100, status="idle", message=msg)
            return
        if mapped_guide_batch:
            msg = "No mapped channels with guide data to fetch."
            source.last_message = msg
            source.save(update_fields=['last_message'])
            send_epg_update(source.id, "parsing_programs", 100, status="idle", message=msg)
            return
        success_msg = (
            f"{len(station_map)} lineup stations synced. "
            "Map channels to EPG entries, then refresh to populate guide data."
        )
        source.status = EPGSource.STATUS_SUCCESS
        source.last_message = success_msg
        source.updated_at = timezone.now()
        source.save(update_fields=['status', 'last_message', 'updated_at'])
        send_epg_update(source.id, "parsing_programs", 100, status="success", message=success_msg)
        return

    send_epg_update(
        source.id, "parsing_programs", 33,
        message=f"Checking schedule MD5s for {len(mapped_station_ids)} mapped stations over {SD_DAYS_TO_FETCH} days...",
    )

    # Fetch MD5 hashes for mapped stations in batches of 5000
    STATION_BATCH_SIZE = 5000
    server_md5s = {}  # (station_id, date) -> {md5, last_modified}

    logger.info(
        f"Fetching schedule MD5s for {len(mapped_station_ids)} mapped stations "
        f"(of {len(station_ids)} lineup stations) over {SD_DAYS_TO_FETCH} days."
    )

    station_batches = [
        mapped_station_ids[i:i + STATION_BATCH_SIZE]
        for i in range(0, len(mapped_station_ids), STATION_BATCH_SIZE)
    ]
    for batch in station_batches:
        try:
            md5_response = requests.post(
                f"{SD_BASE_URL}/schedules/md5",
                json=[{'stationID': sid, 'date': date_list} for sid in batch],
                headers=_sd_headers(token),
                timeout=120,
            )
            md5_response.raise_for_status()
            md5_data = md5_response.json()
            for sid, dates in md5_data.items():
                for date_str, info in dates.items():
                    if info.get('code', 0) == 0:
                        server_md5s[(sid, date_str)] = {
                            'md5': info.get('md5', ''),
                            'last_modified': info.get('lastModified', ''),
                        }
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch schedule MD5s: {e}")

    # Load our cached MD5s from DB (mapped stations only)
    cached_md5s = {
        (r.station_id, r.date.strftime('%Y-%m-%d')): r.md5
        for r in SDScheduleMD5.objects.filter(
            epg_source=source, station_id__in=mapped_station_ids,
        )
    }

    changed_by_station = _sd_compute_schedule_changes_from_md5(
        server_md5s, cached_md5s, date_list,
    )

    window_start = datetime(today.year, today.month, today.day, tzinfo=dt_timezone.utc)
    window_end = window_start + timedelta(days=SD_DAYS_TO_FETCH)
    dates_with_data = set()
    if mapped_epg_ids:
        for epg_id, start_time in ProgramData.objects.filter(
            epg_id__in=mapped_epg_ids,
            start_time__gte=window_start,
            start_time__lt=window_end,
        ).values_list('epg_id', 'start_time'):
            dates_with_data.add((epg_id, start_time.date()))

    stations_without_any_data = mapped_tvg_ids - set(
        ProgramData.objects.filter(epg_id__in=mapped_epg_ids)
        .values_list('tvg_id', flat=True).distinct()
    )
    backfilled_count = _sd_backfill_schedule_dates_without_data(
        changed_by_station,
        server_md5s,
        date_list,
        mapped_station_ids,
        epg_id_map,
        dates_with_data,
        cached_md5s,
        stations_without_any_data,
    )
    if backfilled_count:
        logger.info(
            f"Backfilling {backfilled_count} station/date combinations with no ProgramData "
            f"in the {SD_DAYS_TO_FETCH}-day fetch window."
        )

    total_changed = sum(len(v) for v in changed_by_station.values())
    total_possible = len(mapped_station_ids) * len(date_list)
    logger.info(
        f"Schedule MD5 check: {len(server_md5s)} hashes checked, "
        f"{total_changed} station/date combinations to fetch (of {total_possible} possible)."
    )
    send_epg_update(source.id, "parsing_programs", 38,
                    message=f"MD5 check complete: {len(changed_by_station)} stations have schedule updates.")

    # schedules_by_station: stationID -> list of {programID, airDateTime, duration, ...}
    schedules_by_station = {sid: [] for sid in mapped_station_ids}
    program_ids_needed = set()

    if not changed_by_station:
        logger.info("No schedule changes detected, skipping schedule and program downloads.")
        _sd_post_refresh_tasks(mapped_epg_ids, {}, today)
        if lightweight_sd_fetch:
            msg = "No schedule updates needed; guide data is up to date."
            source.last_message = msg
            source.save(update_fields=['last_message'])
            send_epg_update(source.id, "parsing_programs", 100, status="success", message=msg)
            return
        send_epg_update(source.id, "parsing_programs", 100, status="success",
                        message="No schedule changes detected since last refresh. Guide data is up to date.")
        source.status = EPGSource.STATUS_SUCCESS
        source.last_message = "No schedule changes detected. Guide data is up to date."
        source.updated_at = timezone.now()
        source.save(update_fields=['status', 'last_message', 'updated_at'])
        return

    # Download only changed schedules, batched by 7-day windows per station
    SCHEDULE_BATCH_DAYS = 7
    changed_station_ids = list(changed_by_station.keys())
    date_batches = [date_list[i:i + SCHEDULE_BATCH_DAYS] for i in range(0, len(date_list), SCHEDULE_BATCH_DAYS)]
    new_md5_records = []
    updated_md5_records = []
    existing_md5_map = {
        (r.station_id, r.date.strftime('%Y-%m-%d')): r
        for r in SDScheduleMD5.objects.filter(epg_source=source, station_id__in=changed_station_ids)
    }

    for batch_idx, date_batch in enumerate(date_batches):
        # Notify frontend at the start of each batch so progress updates immediately
        pre_progress = 38 + int((batch_idx / len(date_batches)) * 22)
        logger.info(f"Fetching schedule batch {batch_idx + 1} of {len(date_batches)}...")
        send_epg_update(source.id, "parsing_programs", min(59, pre_progress),
                        message=f"Fetching schedules: batch {batch_idx + 1} of {len(date_batches)}...")
        # Yield to gevent hub so the WebSocket update is delivered before the blocking request
        try:
            import gevent; gevent.sleep(0)
        except ImportError:
            pass
        # Only include stations that have changes in this date batch
        request_body = [
            {'stationID': sid, 'date': [d for d in date_batch if d in changed_by_station.get(sid, [])]}
            for sid in changed_station_ids
            if any(d in changed_by_station.get(sid, []) for d in date_batch)
        ]
        if not request_body:
            continue
        try:
            sched_response = requests.post(
                f"{SD_BASE_URL}/schedules",
                json=request_body,
                headers=_sd_headers(token),
                timeout=120,
            )
            sched_response.raise_for_status()
            sched_data = sched_response.json()

            for station_sched in sched_data:
                sid = station_sched.get('stationID')
                if not sid:
                    continue
                programs = station_sched.get('programs', [])
                schedules_by_station.setdefault(sid, []).extend(programs)
                for prog in programs:
                    pid = prog.get('programID')
                    if pid:
                        program_ids_needed.add(pid)

                # Update MD5 cache for this station/date
                meta = station_sched.get('metadata', {})
                start_date = meta.get('startDate')
                md5_val = meta.get('md5', '')
                last_mod_str = meta.get('modified', '')
                if start_date and md5_val:
                    key = (sid, start_date)
                    last_mod = parse_datetime(last_mod_str) if last_mod_str else timezone.now()
                    if key in existing_md5_map:
                        rec = existing_md5_map[key]
                        rec.md5 = md5_val
                        rec.last_modified = last_mod
                        updated_md5_records.append(rec)
                    else:
                        import datetime as dt_module
                        try:
                            date_obj = dt_module.date.fromisoformat(start_date)
                            new_md5_records.append(SDScheduleMD5(
                                epg_source=source,
                                station_id=sid,
                                date=date_obj,
                                md5=md5_val,
                                last_modified=last_mod,
                            ))
                        except ValueError:
                            pass

            progress = 38 + int(((batch_idx + 1) / len(date_batches)) * 22)
            send_epg_update(source.id, "parsing_programs", min(60, progress),
                            message=f"Fetching changed schedules: batch {batch_idx + 1}/{len(date_batches)} ({len(program_ids_needed):,} programs found)")

        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch schedule batch {batch_idx + 1}: {e}")

    # Persist updated MD5 cache
    if new_md5_records:
        SDScheduleMD5.objects.bulk_create(new_md5_records, ignore_conflicts=True)
        logger.info(f"Cached {len(new_md5_records)} new schedule MD5s.")
    if updated_md5_records:
        SDScheduleMD5.objects.bulk_update(updated_md5_records, ['md5', 'last_modified'])
        logger.info(f"Updated {len(updated_md5_records)} existing schedule MD5s.")

    if not program_ids_needed:
        msg = "No schedule data returned from Schedules Direct."
        logger.warning(msg)
        source.status = EPGSource.STATUS_ERROR
        source.last_message = msg
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "parsing_programs", 100, status="error", error=msg)
        return

    # -------------------------------------------------------------------------
    # Step 6: MD5-delta program metadata fetch
    # The schedule response includes an MD5 hash per program airing.
    # Compare against our cached program MD5s to only download programs
    # whose metadata has changed since our last fetch.
    # -------------------------------------------------------------------------

    # Build map of programID -> md5 from schedule data
    schedule_program_md5s = {}  # programID -> md5 from schedule
    for sid, airings in schedules_by_station.items():
        for airing in airings:
            pid = airing.get('programID')
            md5 = airing.get('md5')
            if pid and md5:
                schedule_program_md5s[pid] = md5

    # Load cached program MD5s from SDProgramMD5 table, keyed by programID
    cached_prog_md5s = {
        r.program_id: r.md5
        for r in SDProgramMD5.objects.filter(
            epg_source=source,
            program_id__in=program_ids_needed,
        ).only('program_id', 'md5')
    }

    programs_with_data = set()
    if program_ids_needed:
        programs_with_data = set(
            ProgramData.objects.filter(
                epg__epg_source=source,
                program_id__in=program_ids_needed,
            ).values_list('program_id', flat=True).distinct()
        )

    programs_to_fetch = _sd_programs_needing_metadata(
        program_ids_needed,
        schedule_program_md5s,
        cached_prog_md5s,
        programs_with_data,
    )

    logger.info(
        f"Program MD5 delta: {len(program_ids_needed)} programs in schedules, "
        f"{len(programs_to_fetch)} need downloading ({len(program_ids_needed) - len(programs_to_fetch)} unchanged).")

    program_metadata = {}
    program_id_list = list(programs_to_fetch)
    total_batches = max(1, (len(program_id_list) + SD_PROGRAM_BATCH_SIZE - 1) // SD_PROGRAM_BATCH_SIZE)

    if program_id_list:
        logger.info(f"Fetching metadata for {len(program_id_list)} programs in {total_batches} batch(es).")
        for batch_idx in range(total_batches):
            # Notify frontend at the start of each batch so progress updates immediately
            pre_progress = 60 + int((batch_idx / total_batches) * 20)
            logger.info(f"Fetching program metadata batch {batch_idx + 1} of {total_batches} ({batch_idx * SD_PROGRAM_BATCH_SIZE:,} of {len(program_id_list):,} programs)...")
            send_epg_update(source.id, "parsing_programs", min(79, pre_progress),
                            message=f"Fetching program data: batch {batch_idx + 1} of {total_batches} ({batch_idx * SD_PROGRAM_BATCH_SIZE:,} of {len(program_id_list):,} programs)")
            # Yield to gevent hub so the WebSocket update is delivered before the blocking request
            try:
                import gevent; gevent.sleep(0)
            except ImportError:
                pass
            batch = program_id_list[batch_idx * SD_PROGRAM_BATCH_SIZE:(batch_idx + 1) * SD_PROGRAM_BATCH_SIZE]
            try:
                prog_response = requests.post(
                    f"{SD_BASE_URL}/programs",
                    json=batch,
                    headers=_sd_headers(token),
                    timeout=120,
                )
                prog_response.raise_for_status()
                prog_data = prog_response.json()
                for prog in prog_data:
                    pid = prog.get('programID')
                    if pid:
                        program_metadata[pid] = prog

                progress = 60 + int(((batch_idx + 1) / total_batches) * 20)
                send_epg_update(source.id, "parsing_programs", min(80, progress),
                                message=f"Fetching program details: batch {batch_idx + 1}/{total_batches} ({len(program_metadata):,} programs loaded)")
                logger.debug(f"Fetched program metadata batch {batch_idx + 1}/{total_batches}")

            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to fetch program metadata batch {batch_idx + 1}: {e}")
    else:
        logger.info("All program metadata unchanged - skipping program download.")
        send_epg_update(source.id, "parsing_programs", 80, message="Program metadata unchanged - using cached data.")

    gc.collect()

    # -------------------------------------------------------------------------
    # Step 7: Build ProgramData records and persist atomically
    # -------------------------------------------------------------------------
    logger.info("Building program records...")
    send_epg_update(source.id, "parsing_programs", 80)

    # Cache existing program data for unchanged programs BEFORE surgical delete.
    # When a station/date schedule MD5 changes, ALL airings are re-fetched, but only
    # programs with changed program MD5s get metadata re-downloaded. The surgical delete
    # wipes ALL ProgramData for changed dates, so unchanged programs lose their titles.
    # This cache preserves their data for rebuilding.
    unchanged_pids = set()
    for sid, airings in schedules_by_station.items():
        if sid not in mapped_tvg_ids:
            continue
        for airing in airings:
            pid = airing.get('programID')
            if pid and pid not in program_metadata:
                unchanged_pids.add(pid)

    existing_program_cache = {}
    if unchanged_pids:
        for pd in ProgramData.objects.filter(
            epg__epg_source=source,
            program_id__in=unchanged_pids,
        ).only('program_id', 'title', 'description', 'sub_title', 'custom_properties'):
            if pd.program_id not in existing_program_cache:
                existing_program_cache[pd.program_id] = {
                    'title': pd.title,
                    'description': pd.description,
                    'sub_title': pd.sub_title,
                    'custom_properties': pd.custom_properties,
                }
        logger.info(f"Cached {len(existing_program_cache)} existing program records for unchanged programs.")

    all_programs_to_create = []
    total_programs = 0
    skipped_unmapped = 0

    for sid, airings in schedules_by_station.items():
        if sid not in mapped_tvg_ids:
            skipped_unmapped += len(airings)
            continue

        epg_db_id = epg_id_map.get(sid)
        if not epg_db_id:
            continue

        for airing in airings:
            pid = airing.get('programID')
            air_time = airing.get('airDateTime')
            duration_secs = airing.get('duration', 0)

            if not pid or not air_time or not duration_secs:
                continue

            try:
                start_dt = parse_schedules_direct_time(air_time)
                end_dt = start_dt + timedelta(seconds=int(duration_secs))
            except Exception as e:
                logger.debug(f"Could not parse air time '{air_time}': {e}")
                continue

            meta = program_metadata.get(pid, {})
            cached_prog = existing_program_cache.get(pid) if not meta else None

            if cached_prog:
                # Unchanged program — reuse cached data from before surgical delete
                title = cached_prog['title'] or 'No Title'
                desc = cached_prog['description'] or ''
                episode_title = cached_prog['sub_title'] or ''
                custom_props = cached_prog['custom_properties'] or {}
            else:
                titles = meta.get('titles', [{}])
                title = titles[0].get('title120', '') if titles else ''
                if not title:
                    title = meta.get('episodeTitle150', '') or 'No Title'
            title = title[:255]

            if not cached_prog:
                descriptions = meta.get('descriptions', {})
                desc = ''
                for key in ('description1000', 'description255', 'description100'):
                    candidates = descriptions.get(key, [])
                    if candidates:
                        desc = candidates[0].get('description', '')
                        if desc:
                            break

                episode_title = meta.get('episodeTitle150', '')

                # Build custom_properties following the same pattern as the XMLTV parser
                custom_props = {}

                # Season/Episode — search all metadata entries, not just [0]
                metadata_block = meta.get('metadata', [])
                gracenote_meta = {}
                for md_entry in metadata_block:
                    if 'Gracenote' in md_entry:
                        gracenote_meta = md_entry['Gracenote']
                        break
                if not gracenote_meta:
                    # Fall back to TVmaze if Gracenote is absent
                    for md_entry in metadata_block:
                        if 'TVmaze' in md_entry:
                            gracenote_meta = md_entry['TVmaze']
                            break
                season = gracenote_meta.get('season')
                episode = gracenote_meta.get('episode')
                if season:
                    custom_props['season'] = int(season)
                if episode:
                    custom_props['episode'] = int(episode)
                if season and episode:
                    custom_props['onscreen_episode'] = f"S{int(season)} E{int(episode)}"

                # Content rating — store full array, pick display rating by lineup country
                content_rating = meta.get('contentRating', [])
                if content_rating:
                    custom_props['content_ratings'] = content_rating
                    selected = None
                    if sd_lineup_country:
                        for cr in content_rating:
                            if cr.get('country', '') == sd_lineup_country:
                                selected = cr
                                break
                    if not selected:
                        # Fall back to USA, then first available
                        for cr in content_rating:
                            if cr.get('country', '') == 'USA':
                                selected = cr
                                break
                    if not selected:
                        selected = content_rating[0]
                    custom_props['rating'] = selected.get('code', '')
                    custom_props['rating_system'] = selected.get('body', '')

                # Content advisory — content warnings
                content_advisory = meta.get('contentAdvisory', [])
                if content_advisory:
                    custom_props['content_advisory'] = content_advisory

                # Categories — combine entityType, showType, and genres
                categories = []
                entity_type = meta.get('entityType', '')
                show_type = meta.get('showType', '')
                if entity_type:
                    categories.append(entity_type)
                if show_type and show_type != entity_type:
                    categories.append(show_type)
                genres = meta.get('genres', [])
                categories.extend(genres)
                if categories:
                    custom_props['categories'] = categories

                # Cast — top-billed only. SD's 'role' field = job type (Actor/Guest Star);
                # SD's 'characterName' = the character played. We store characterName under
                # the key 'role' to match the XMLTV parser convention
                #
                # Guest stars are stored with guest=True so the XMLTV generator emits
                # <actor role="Character" guest="yes"> per the XMLTV DTD standard.
                cast = meta.get('cast', [])
                crew = meta.get('crew', [])
                credits = {}
                if cast:
                    # Sort by billingOrder and cap at top-billed actors
                    sorted_cast = sorted(
                        [p for p in cast if p.get('name')],
                        key=lambda p: int(p.get('billingOrder', '999'))
                    )
                    # Separate regular cast from guest stars (SD 'role' = job type here)
                    main_cast = [p for p in sorted_cast if p.get('role', '').lower() != 'guest star']
                    guest_stars = [p for p in sorted_cast if p.get('role', '').lower() == 'guest star']
                    # Use main cast if available, otherwise fall back to full sorted list
                    primary = main_cast[:6] if main_cast else sorted_cast[:6]
                    actors = [
                        {
                            'name': p.get('name', ''),
                            **(({'role': p['characterName']}) if p.get('characterName') else {}),
                        }
                        for p in primary
                    ]
                    # Append notable guest stars with XMLTV guest="yes" marker (cap at 3)
                    actors += [
                        {
                            'name': p.get('name', ''),
                            **(({'role': p['characterName']}) if p.get('characterName') else {}),
                            'guest': True,
                        }
                        for p in guest_stars[:3]
                    ]
                    if actors:
                        credits['actor'] = actors
                if crew:
                    for member in crew:
                        role = member.get('role', '').lower()
                        name = member.get('name', '')
                        if not name:
                            continue
                        if 'director' in role:
                            credits.setdefault('director', []).append(name)
                        elif 'writer' in role or 'screenwriter' in role:
                            credits.setdefault('writer', []).append(name)
                        elif 'producer' in role:
                            credits.setdefault('producer', []).append(name)
                if credits:
                    custom_props['credits'] = credits

                # Airing flags
                if airing.get('liveTapeDelay') == 'Live':
                    custom_props['live'] = True
                if airing.get('new'):
                    custom_props['new'] = True
                else:
                    custom_props['previously_shown'] = True
                if airing.get('premiere'):
                    custom_props['premiere'] = True

                # Original air date — full date, not just year
                original_air_date = meta.get('originalAirDate', '')
                movie_year = meta.get('movie', {}).get('year', '')
                if original_air_date:
                    custom_props['date'] = original_air_date
                elif movie_year:
                    custom_props['date'] = str(movie_year)

                # Country of production
                country = meta.get('country', [])
                if country:
                    custom_props['country'] = country[0] if len(country) == 1 else ', '.join(country)

                # Runtime — program duration without commercials (seconds → store for display)
                runtime_secs = meta.get('duration') or meta.get('movie', {}).get('duration')
                if runtime_secs:
                    runtime_mins = int(runtime_secs) // 60
                    custom_props['length'] = {'value': str(runtime_mins), 'units': 'minutes'}

                # Movie quality ratings → star_ratings (matches XMLTV key)
                movie_data = meta.get('movie', {})
                quality_ratings = movie_data.get('qualityRating', [])
                if quality_ratings:
                    star_ratings = []
                    for qr in quality_ratings:
                        rating_str = qr.get('rating', '')
                        max_rating = qr.get('maxRating', '')
                        if rating_str and max_rating:
                            star_ratings.append({
                                'value': f"{rating_str}/{max_rating}",
                                'system': qr.get('ratingsBody', ''),
                            })
                    if star_ratings:
                        custom_props['star_ratings'] = star_ratings

                # Sports event details
                event_details = meta.get('eventDetails', {})
                if event_details:
                    custom_props['event_details'] = event_details

            all_programs_to_create.append(ProgramData(
                epg_id=epg_db_id,
                start_time=start_dt,
                end_time=end_dt,
                title=title,
                sub_title=episode_title or None,
                description=desc or None,
                tvg_id=sid,
                program_id=pid,
                custom_properties=custom_props or None,
            ))
            total_programs += 1

    logger.info(f"Built {total_programs} program records "
                f"({skipped_unmapped} skipped for unmapped stations).")

    send_epg_update(source.id, "parsing_programs", 88)

    # Build a map of epg_db_id -> list of (day_start_utc, day_end_utc) for each changed date.
    # Only programs that fall within changed station/date pairs will be deleted and replaced;
    # programs for unchanged stations or unchanged dates are left intact.
    import datetime as dt_module
    epg_changed_date_ranges = {}
    for sid, changed_date_strs in changed_by_station.items():
        epg_db_id = epg_id_map.get(sid)
        if not epg_db_id or epg_db_id not in mapped_epg_ids:
            continue
        ranges = []
        for ds in changed_date_strs:
            d = dt_module.date.fromisoformat(ds)
            day_start = datetime(d.year, d.month, d.day, tzinfo=dt_timezone.utc)
            ranges.append((day_start, day_start + timedelta(days=1)))
        if ranges:
            epg_changed_date_ranges[epg_db_id] = ranges

    # Atomic delete (surgical) + bulk insert
    BATCH_SIZE = 1000
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '10min'")
            total_deleted = 0
            for epg_db_id, day_ranges in epg_changed_date_ranges.items():
                q = Q()
                for day_start, day_end in day_ranges:
                    q |= Q(start_time__gte=day_start, start_time__lt=day_end)
                cnt = ProgramData.objects.filter(epg_id=epg_db_id).filter(q).delete()[0]
                total_deleted += cnt
            logger.debug(f"Deleted {total_deleted} changed SD programs across {len(epg_changed_date_ranges)} stations.")
            for i in range(0, len(all_programs_to_create), BATCH_SIZE):
                ProgramData.objects.bulk_create(all_programs_to_create[i:i + BATCH_SIZE])
                progress = 88 + int(((i + BATCH_SIZE) / max(len(all_programs_to_create), 1)) * 10)
                send_epg_update(source.id, "parsing_programs", min(98, progress))

        logger.info(f"Committed {total_programs} Schedules Direct programs to database.")

        # Upsert SDProgramMD5 records for programs we just downloaded
        # This updates the cache so future fetches can skip unchanged programs
        if schedule_program_md5s:
            md5_records = [
                SDProgramMD5(
                    epg_source=source,
                    program_id=pid,
                    md5=md5,
                )
                for pid, md5 in schedule_program_md5s.items()
                if pid in program_metadata  # Only cache programs that were actually downloaded
            ]
            if md5_records:
                SDProgramMD5.objects.bulk_create(
                    md5_records,
                    update_conflicts=True,
                    unique_fields=['epg_source', 'program_id'],
                    update_fields=['md5'],
                )
                logger.info(f"Cached {len(md5_records)} program MD5s for future delta detection.")

    except Exception as db_error:
        msg = f"Database error persisting Schedules Direct programs: {db_error}"
        logger.error(msg, exc_info=True)
        source.status = EPGSource.STATUS_ERROR
        source.last_message = msg
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "parsing_programs", 100, status="error", error=msg)
        return
    finally:
        all_programs_to_create = None
        gc.collect()

    # -------------------------------------------------------------------------
    # Step 8–9: Posters, logo auto-apply, and pruning
    # -------------------------------------------------------------------------
    _sd_post_refresh_tasks(mapped_epg_ids, program_metadata, today)

    # -------------------------------------------------------------------------
    # Done
    # -------------------------------------------------------------------------
    if single_epg_fetch:
        epg_label = EPGData.objects.filter(id=epg_id_only).values_list('name', flat=True).first()
        success_msg = (
            f"Fetched {total_programs:,} programs for "
            f"{epg_label or epg_id_only} from Schedules Direct."
        )
        source.last_message = success_msg
        source.save(update_fields=['last_message'])
        send_epg_update(source.id, "parsing_programs", 100, status="success", message=success_msg)
        log_system_event(
            event_type='epg_refresh',
            source_name=source.name,
            programs=total_programs,
            channels=1,
            skipped_programs=skipped_unmapped,
        )
        logger.info(f"Schedules Direct single-EPG fetch complete for source: {source.name}")
        return

    if mapped_guide_batch:
        success_msg = (
            f"Fetched {total_programs:,} programs for "
            f"{len(mapped_tvg_ids)} mapped stations from Schedules Direct "
            f"({skipped_unmapped:,} programs skipped for unmapped stations)."
        )
        source.last_message = success_msg
        source.save(update_fields=['last_message'])
        send_epg_update(source.id, "parsing_programs", 100, status="success", message=success_msg)
        log_system_event(
            event_type='epg_refresh',
            source_name=source.name,
            programs=total_programs,
            channels=len(mapped_tvg_ids),
            skipped_programs=skipped_unmapped,
        )
        logger.info(f"Schedules Direct mapped guide batch complete for source: {source.name}")
        return

    success_msg = (
        f"Successfully fetched {total_programs:,} programs for "
        f"{len(mapped_tvg_ids)} mapped stations from Schedules Direct "
        f"({skipped_unmapped:,} programs skipped for unmapped stations)."
    )
    source.status = EPGSource.STATUS_SUCCESS
    source.last_message = success_msg
    source.updated_at = timezone.now()
    source.save(update_fields=['status', 'last_message', 'updated_at'])
    send_epg_update(source.id, "parsing_programs", 100, status="success", message=success_msg)
    log_system_event(
        event_type='epg_refresh',
        source_name=source.name,
        programs=total_programs,
        channels=len(mapped_tvg_ids),
        skipped_programs=skipped_unmapped,
    )
    logger.info(f"Schedules Direct fetch complete for source: {source.name}")


# -------------------------------
# Helper parse functions
# -------------------------------
def parse_xmltv_time(time_str):
    try:
        # Basic format validation
        if len(time_str) < 14:
            logger.warning(f"XMLTV timestamp too short: '{time_str}', using as-is")
            dt_obj = datetime.strptime(time_str, '%Y%m%d%H%M%S')
            return timezone.make_aware(dt_obj, timezone=dt_timezone.utc)

        # Parse base datetime
        dt_obj = datetime.strptime(time_str[:14], '%Y%m%d%H%M%S')

        # Handle timezone if present
        if len(time_str) >= 20:  # Has timezone info
            tz_sign = time_str[15]
            tz_hours = int(time_str[16:18])
            tz_minutes = int(time_str[18:20])

            # Create a timezone object
            if tz_sign == '+':
                tz_offset = dt_timezone(timedelta(hours=tz_hours, minutes=tz_minutes))
            elif tz_sign == '-':
                tz_offset = dt_timezone(timedelta(hours=-tz_hours, minutes=-tz_minutes))
            else:
                tz_offset = dt_timezone.utc

            # Make datetime aware with correct timezone
            aware_dt = datetime.replace(dt_obj, tzinfo=tz_offset)
            # Convert to UTC
            aware_dt = aware_dt.astimezone(dt_timezone.utc)

            logger.trace(f"Parsed XMLTV time '{time_str}' to {aware_dt}")
            return aware_dt
        else:
            # No timezone info, assume UTC
            aware_dt = timezone.make_aware(dt_obj, timezone=dt_timezone.utc)
            logger.trace(f"Parsed XMLTV time without timezone '{time_str}' as UTC: {aware_dt}")
            return aware_dt

    except Exception as e:
        logger.error(f"Error parsing XMLTV time '{time_str}': {e}", exc_info=True)
        raise


def parse_schedules_direct_time(time_str):
    try:
        dt_obj = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%SZ')
        return timezone.make_aware(dt_obj, timezone=dt_timezone.utc)
    except Exception as e:
        logger.error(f"Error parsing Schedules Direct time '{time_str}': {e}", exc_info=True)
        raise


# Re-export from utils to preserve backward compatibility for any callers
from apps.epg.utils import extract_season_episode_from_description, _ONSCREEN_RE  # noqa: F401


# Helper function to extract custom properties - moved to a separate function to clean up the code
def extract_custom_properties(prog):
    # Create a new dictionary for each call
    custom_props = {}

    # Extract categories with a single comprehension to reduce intermediate objects
    categories = [cat.text.strip() for cat in prog.findall('category') if cat.text and cat.text.strip()]
    if categories:
        custom_props['categories'] = categories

    # Extract keywords (new)
    keywords = [kw.text.strip() for kw in prog.findall('keyword') if kw.text and kw.text.strip()]
    if keywords:
        custom_props['keywords'] = keywords

    # Extract episode numbers
    for ep_num in prog.findall('episode-num'):
        system = ep_num.get('system', '')
        if system == 'xmltv_ns' and ep_num.text:
            # Parse XMLTV episode-num format (season.episode.part)
            parts = ep_num.text.split('.')
            if len(parts) >= 2:
                if parts[0].strip() != '':
                    try:
                        season = int(parts[0]) + 1  # XMLTV format is zero-based
                        custom_props['season'] = season
                    except ValueError:
                        pass
                if parts[1].strip() != '':
                    try:
                        episode = int(parts[1]) + 1  # XMLTV format is zero-based
                        custom_props['episode'] = episode
                    except ValueError:
                        pass
        elif system == 'onscreen' and ep_num.text:
            onscreen_text = ep_num.text.strip()
            custom_props['onscreen_episode'] = onscreen_text
            # Extract season/episode from onscreen format if not already set by xmltv_ns
            if 'season' not in custom_props or 'episode' not in custom_props:
                match = _ONSCREEN_RE.search(onscreen_text)
                if match:
                    if 'season' not in custom_props:
                        custom_props['season'] = int(match.group(1))
                    if 'episode' not in custom_props:
                        custom_props['episode'] = int(match.group(2))
        elif system == 'dd_progid' and ep_num.text:
            # Store the dd_progid format
            custom_props['dd_progid'] = ep_num.text.strip()
        # Add support for other systems like thetvdb.com, themoviedb.org, imdb.com
        elif system in ['thetvdb.com', 'themoviedb.org', 'imdb.com'] and ep_num.text:
            custom_props[f'{system}_id'] = ep_num.text.strip()

    # Extract ratings more efficiently
    rating_elem = prog.find('rating')
    if rating_elem is not None:
        value_elem = rating_elem.find('value')
        if value_elem is not None and value_elem.text:
            custom_props['rating'] = value_elem.text.strip()
            if rating_elem.get('system'):
                custom_props['rating_system'] = rating_elem.get('system')

    # Extract star ratings (new)
    star_ratings = []
    for star_rating in prog.findall('star-rating'):
        value_elem = star_rating.find('value')
        if value_elem is not None and value_elem.text:
            rating_data = {'value': value_elem.text.strip()}
            if star_rating.get('system'):
                rating_data['system'] = star_rating.get('system')
            star_ratings.append(rating_data)
    if star_ratings:
        custom_props['star_ratings'] = star_ratings

    # Extract credits more efficiently
    credits_elem = prog.find('credits')
    if credits_elem is not None:
        credits = {}
        for credit_type in ['director', 'actor', 'writer', 'adapter', 'producer', 'composer', 'editor', 'presenter', 'commentator', 'guest']:
            if credit_type == 'actor':
                # Handle actors with roles and guest status
                actors = []
                for actor_elem in credits_elem.findall('actor'):
                    if actor_elem.text and actor_elem.text.strip():
                        actor_data = {'name': actor_elem.text.strip()}
                        if actor_elem.get('role'):
                            actor_data['role'] = actor_elem.get('role')
                        if actor_elem.get('guest') == 'yes':
                            actor_data['guest'] = True
                        actors.append(actor_data)
                if actors:
                    credits['actor'] = actors
            else:
                names = [e.text.strip() for e in credits_elem.findall(credit_type) if e.text and e.text.strip()]
                if names:
                    credits[credit_type] = names
        if credits:
            custom_props['credits'] = credits

    # Extract other common program metadata
    date_elem = prog.find('date')
    if date_elem is not None and date_elem.text:
        custom_props['date'] = date_elem.text.strip()

    country_elem = prog.find('country')
    if country_elem is not None and country_elem.text:
        custom_props['country'] = country_elem.text.strip()

    # Extract language information (new)
    language_elem = prog.find('language')
    if language_elem is not None and language_elem.text:
        custom_props['language'] = language_elem.text.strip()

    orig_language_elem = prog.find('orig-language')
    if orig_language_elem is not None and orig_language_elem.text:
        custom_props['original_language'] = orig_language_elem.text.strip()

    # Extract length (new)
    length_elem = prog.find('length')
    if length_elem is not None and length_elem.text:
        try:
            length_value = int(length_elem.text.strip())
            length_units = length_elem.get('units', 'minutes')
            custom_props['length'] = {'value': length_value, 'units': length_units}
        except ValueError:
            pass

    # Extract video information (new)
    video_elem = prog.find('video')
    if video_elem is not None:
        video_info = {}
        for video_attr in ['present', 'colour', 'aspect', 'quality']:
            attr_elem = video_elem.find(video_attr)
            if attr_elem is not None and attr_elem.text:
                video_info[video_attr] = attr_elem.text.strip()
        if video_info:
            custom_props['video'] = video_info

    # Extract audio information (new)
    audio_elem = prog.find('audio')
    if audio_elem is not None:
        audio_info = {}
        for audio_attr in ['present', 'stereo']:
            attr_elem = audio_elem.find(audio_attr)
            if attr_elem is not None and attr_elem.text:
                audio_info[audio_attr] = attr_elem.text.strip()
        if audio_info:
            custom_props['audio'] = audio_info

    # Extract subtitles information (new)
    subtitles = []
    for subtitle_elem in prog.findall('subtitles'):
        subtitle_data = {}
        if subtitle_elem.get('type'):
            subtitle_data['type'] = subtitle_elem.get('type')
        lang_elem = subtitle_elem.find('language')
        if lang_elem is not None and lang_elem.text:
            subtitle_data['language'] = lang_elem.text.strip()
        if subtitle_data:
            subtitles.append(subtitle_data)

    if subtitles:
        custom_props['subtitles'] = subtitles

    # Extract reviews (new)
    reviews = []
    for review_elem in prog.findall('review'):
        if review_elem.text and review_elem.text.strip():
            review_data = {'content': review_elem.text.strip()}
            if review_elem.get('type'):
                review_data['type'] = review_elem.get('type')
            if review_elem.get('source'):
                review_data['source'] = review_elem.get('source')
            if review_elem.get('reviewer'):
                review_data['reviewer'] = review_elem.get('reviewer')
            reviews.append(review_data)
    if reviews:
        custom_props['reviews'] = reviews

    # Extract images (new)
    images = []
    for image_elem in prog.findall('image'):
        if image_elem.text and image_elem.text.strip():
            image_data = {'url': image_elem.text.strip()}
            for attr in ['type', 'size', 'orient', 'system']:
                if image_elem.get(attr):
                    image_data[attr] = image_elem.get(attr)
            images.append(image_data)
    if images:
        custom_props['images'] = images

    icon_elem = prog.find('icon')
    if icon_elem is not None and icon_elem.get('src'):
        custom_props['icon'] = icon_elem.get('src')

    # Simpler approach for boolean flags - expanded list
    for kw in ['previously-shown', 'premiere', 'new', 'live', 'last-chance']:
        if prog.find(kw) is not None:
            custom_props[kw.replace('-', '_')] = True

    # Extract premiere and last-chance text content if available
    premiere_elem = prog.find('premiere')
    if premiere_elem is not None:
        custom_props['premiere'] = True
        if premiere_elem.text and premiere_elem.text.strip():
            custom_props['premiere_text'] = premiere_elem.text.strip()

    last_chance_elem = prog.find('last-chance')
    if last_chance_elem is not None:
        custom_props['last_chance'] = True
        if last_chance_elem.text and last_chance_elem.text.strip():
            custom_props['last_chance_text'] = last_chance_elem.text.strip()

    # Extract previously-shown details
    prev_shown_elem = prog.find('previously-shown')
    if prev_shown_elem is not None:
        custom_props['previously_shown'] = True
        prev_shown_data = {}
        if prev_shown_elem.get('start'):
            prev_shown_data['start'] = prev_shown_elem.get('start')
        if prev_shown_elem.get('channel'):
            prev_shown_data['channel'] = prev_shown_elem.get('channel')
        if prev_shown_data:
            custom_props['previously_shown_details'] = prev_shown_data

    return custom_props


def clear_element(elem):
    """Clear an XML element and its parent to free memory."""
    try:
        elem.clear()
        parent = elem.getparent()
        if parent is not None:
            while elem.getprevious() is not None:
                del parent[0]
            parent.remove(elem)
    except Exception as e:
        logger.warning(f"Error clearing XML element: {e}", exc_info=True)


def detect_file_format(file_path=None, content=None):
    """
    Detect file format by examining content or file path.

    Args:
        file_path: Path to file (optional)
        content: Raw file content bytes (optional)

    Returns:
        tuple: (format_type, is_compressed, file_extension)
        format_type: 'gzip', 'zip', 'xml', or 'unknown'
        is_compressed: Boolean indicating if the file is compressed
        file_extension: Appropriate file extension including dot (.gz, .zip, .xml)
    """
    # Default return values
    format_type = 'unknown'
    is_compressed = False
    file_extension = '.tmp'

    # First priority: check content magic numbers as they're most reliable
    if content:
        # We only need the first few bytes for magic number detection
        header = content[:20] if len(content) >= 20 else content

        # Check for gzip magic number (1f 8b)
        if len(header) >= 2 and header[:2] == b'\x1f\x8b':
            return 'gzip', True, '.gz'

        # Check for zip magic number (PK..)
        if len(header) >= 2 and header[:2] == b'PK':
            return 'zip', True, '.zip'

        # Check for XML - either standard XML header or XMLTV-specific tag
        if len(header) >= 5 and (b'<?xml' in header or b'<tv>' in header):
            return 'xml', False, '.xml'

    # Second priority: check file extension - focus on the final extension for compression
    if file_path:
        logger.debug(f"Detecting file format for: {file_path}")

        # Handle compound extensions like .xml.gz - prioritize compression extensions
        lower_path = file_path.lower()

        # Check for compression extensions explicitly
        if lower_path.endswith('.gz') or lower_path.endswith('.gzip'):
            return 'gzip', True, '.gz'
        elif lower_path.endswith('.zip'):
            return 'zip', True, '.zip'
        elif lower_path.endswith('.xml'):
            return 'xml', False, '.xml'

        # Fallback to mimetypes only if direct extension check doesn't work
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        logger.debug(f"Guessed MIME type: {mime_type}")
        if mime_type:
            if mime_type == 'application/gzip' or mime_type == 'application/x-gzip':
                return 'gzip', True, '.gz'
            elif mime_type == 'application/zip':
                return 'zip', True, '.zip'
            elif mime_type == 'application/xml' or mime_type == 'text/xml':
                return 'xml', False, '.xml'

    # If we reach here, we couldn't reliably determine the format
    return format_type, is_compressed, file_extension


def generate_dummy_epg(source):
    """
    DEPRECATED: This function is no longer used.

    Dummy EPG programs are now generated on-demand when they are requested
    (during XMLTV export or EPG grid display), rather than being pre-generated
    and stored in the database.

    See: apps/output/views.py - generate_custom_dummy_programs()

    This function remains for backward compatibility but should not be called.
    """
    logger.warning(f"generate_dummy_epg() called for {source.name} but this function is deprecated. "
                   f"Dummy EPG programs are now generated on-demand.")
    return True


# ---------------------------------------------------------------------------
# Byte-offset programme index (ported from dev branch)
# These functions support fast current-program lookup for the CurrentPrograms
# API without doing a full DB query for every channel on every poll.
# ---------------------------------------------------------------------------


def _resolve_source_file(epg_source):
    """Resolve the XML file path for an EPG source."""
    file_path = epg_source.extracted_file_path or epg_source.file_path
    if not file_path:
        file_path = epg_source.get_cache_file()
    return file_path


_CHANNEL_ATTR_RE = re.compile(rb"""channel\s*=\s*(?:"([^"]+)"|'([^']+)')""")
_PROGRAMME_TAG = b'<programme'
_PROGRAMME_TAG_LEN = len(_PROGRAMME_TAG)
_TAG_FOLLOW = b' \t\n\r>/'
_MAX_START_TAG = 4096  # generous upper bound for a start tag with namespaces/extra attrs
_OFFSET_CAP = 10  # max block-starts recorded per channel; exceeding this flags the channel as interleaved


def _decode_channel_id(raw):
    """Match how EPGData.tvg_id is stored: resolve XML entities and strip, so byte-level index keys equal the lxml-parsed channel ids."""
    s = raw.decode('utf-8', errors='replace')
    if '&' in s:
        s = html.unescape(s)
    return s.strip()


def _find_programme_tag(buf, start):
    """
    Find the next <programme element in *buf* starting from *start*.
    Returns (tag_pos, tag_end) or (-1, -1) if not found.
    """
    pos = start
    while True:
        idx = buf.find(_PROGRAMME_TAG, pos)
        if idx == -1:
            return -1, -1
        # Validate next byte is whitespace or '>'
        follow = idx + _PROGRAMME_TAG_LEN
        if follow >= len(buf):
            return idx, -1  # need more data
        if buf[follow: follow + 1] not in _TAG_FOLLOW:
            pos = follow  # false match (e.g. <programmeXYZ), skip
            continue
        # Find the '>' that closes the opening tag (scan up to _MAX_START_TAG bytes)
        tag_end = buf.find(b'>', follow, idx + _MAX_START_TAG)
        if tag_end == -1:
            if len(buf) >= idx + _MAX_START_TAG:
                logger.warning(
                    f'[_find_programme_tag] <programme> start tag exceeds {_MAX_START_TAG} bytes at offset {idx}, skipping'
                )
                return -1, -1
            return idx, -1  # need more data
        return idx, tag_end


def _programme_to_dict(elem, start_time, end_time):
    """Convert a <programme> lxml element to a serializable dict."""
    title_el = elem.find('title')
    desc_el = elem.find('desc')
    sub_el = elem.find('sub-title')
    return {
        'title': title_el.text if title_el is not None and title_el.text else '',
        'description': desc_el.text if desc_el is not None and desc_el.text else '',
        'sub_title': sub_el.text if sub_el is not None and sub_el.text else '',
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat(),
    }


def build_programme_index(source_id):
    """
    Scan the XML file with raw binary I/O to build a {tvg_id: [byte_offset, ...]} map.
    Persists the result to the EPGSourceIndex table. Most XMLTV files group programmes
    by channel, but some split a channel across multiple non-contiguous blocks, so we
    record block starts up to _OFFSET_CAP and mark only channels that exceed the cap
    as interleaved.
    """
    try:
        source = EPGSource.objects.get(id=source_id)
    except EPGSource.DoesNotExist:
        logger.error(f'[build_programme_index] EPGSource {source_id} not found')
        return

    file_path = _resolve_source_file(source)
    if not file_path or not os.path.exists(file_path):
        logger.warning(
            f'[build_programme_index] File not found for source {source_id}: {file_path}'
        )
        return

    logger.debug(
        f'[build_programme_index] Building byte-offset index for source {source_id} from {file_path}'
    )
    start = time.monotonic()
    index = {}
    prev_channel = None
    interleaved_channels = set()

    CHUNK = 8 * 1024 * 1024  # 8MB

    with open(file_path, 'rb') as f:
        buf = bytearray()
        buf_offset = 0  # absolute file offset of buf[0]

        while True:
            chunk = f.read(CHUNK)
            if not chunk and not buf:
                break
            buf.extend(chunk)
            search_from = 0

            while True:
                idx, tag_end = _find_programme_tag(buf, search_from)
                if idx == -1:
                    break
                if tag_end == -1 and chunk:
                    break  # incomplete tag at buffer edge, need more data

                abs_pos = buf_offset + idx
                m = _CHANNEL_ATTR_RE.search(
                    buf, idx, tag_end + 1 if tag_end != -1 else idx + _MAX_START_TAG
                )
                if m:
                    channel_id = _decode_channel_id(m.group(1) or m.group(2))
                    if channel_id not in index:
                        index[channel_id] = [abs_pos]
                    elif channel_id != prev_channel:
                        if len(index[channel_id]) < _OFFSET_CAP:
                            index[channel_id].append(abs_pos)
                        else:
                            interleaved_channels.add(channel_id)
                    prev_channel = channel_id

                search_from = (
                    (tag_end + 1) if tag_end != -1 else (idx + _PROGRAMME_TAG_LEN)
                )

            if not chunk:
                break

            # Keep unprocessed tail for next iteration
            keep_from = (
                max(search_from, len(buf) - _MAX_START_TAG) if chunk else len(buf)
            )
            del buf[:keep_from]
            buf_offset += keep_from

    elapsed = time.monotonic() - start
    logger.info(
        f'[build_programme_index] Indexed {len(index)} channels in {elapsed:.1f}s for source {source_id}'
        + (
            f' ({len(interleaved_channels)} interleaved)'
            if interleaved_channels
            else ''
        )
    )

    result = {
        'channels': index,
        'interleaved_channels': sorted(interleaved_channels),
    }
    EPGSourceIndex.objects.update_or_create(
        source_id=source_id, defaults={'data': result}
    )


@shared_task
def build_programme_index_task(source_id):
    """Celery wrapper. Locks so refresh and preview don't both build the same source. Releases on finish rather than waiting out the TTL."""
    from core.utils import RedisClient

    redis_client = RedisClient.get_client()
    lock_key = f'building_programme_index_{source_id}'
    if not redis_client.set(lock_key, '1', nx=True, ex=300):
        return
    try:
        build_programme_index(source_id)
    finally:
        redis_client.delete(lock_key)


def find_current_program_for_tvg_id(epg_or_id):
    """
    Look up the currently-airing program for an EPGData instance (or id) using
    the byte-offset index. If no index exists yet, queue an async build and let
    the caller retry rather than doing a blocking scan.

    Returns dict, None, or "timeout".
    """
    if isinstance(epg_or_id, EPGData):
        epg = epg_or_id
    else:
        try:
            epg = EPGData.objects.select_related('epg_source').get(id=epg_or_id)
        except EPGData.DoesNotExist:
            return None

    source = epg.epg_source
    if not source or source.source_type in ('dummy', 'schedules_direct'):
        return None

    tvg_id = epg.tvg_id
    if not tvg_id:
        return None

    file_path = _resolve_source_file(source)
    if not file_path or not os.path.exists(file_path):
        return None

    now = timezone.now()
    # The property reads the EPGSourceIndex table fresh on each access, so a
    # concurrent refresh invalidating/rebuilding the index can't serve stale state.
    index = source.programme_index

    if index is not None:
        channels = index.get('channels', {})
        if tvg_id not in channels:
            # Channel has no programmes in the file
            return None
        offsets = channels[tvg_id]
        if tvg_id in (index.get('interleaved_channels') or ()):
            # Check all stored offsets first (cheap: one seek + one element parse each)
            result = _read_programs_at_offsets(file_path, tvg_id, offsets, now)
            if result is not None:
                return result
            # Current programme is beyond the stored offsets; scan forward from the
            # last known position to avoid re-reading the already-checked portion
            result = _scan_from_offset_for_tvg_id(file_path, tvg_id, offsets[-1], now)
            if result == 'timeout':
                logger.warning(
                    f'[find_current_program_for_tvg_id] Interleaved scan timed out for '
                    f'tvg_id={tvg_id} source={source.id}; index has {len(offsets)} offsets'
                )
                return None
            return result
        return _read_programs_at_offsets(file_path, tvg_id, offsets, now)

    # No index yet: dispatch a background build and let the frontend retry.
    # A sync scan can block a worker for ~10s on SMB-hosted EPGs.
    build_programme_index_task.delay(source.id)
    return 'timeout'


def _read_programs_at_offsets(file_path, tvg_id, offsets, now):
    """
    Seek to each offset, extract <programme> elements for *tvg_id*, return the
    first one currently airing. Chunk-based so it works on minified XML.
    """
    PROG_CLOSE = b'</programme>'
    CLOSE_LEN = len(PROG_CLOSE)
    READ_SIZE = 2 * 1024 * 1024  # 2MB per read

    with open(file_path, 'rb') as f:
        for offset in offsets:
            f.seek(offset)
            buf = bytearray()
            done = False

            while not done:
                chunk = f.read(READ_SIZE)
                if not chunk and not buf:
                    break
                buf.extend(chunk)
                search_from = 0

                while True:
                    tag_start, tag_end = _find_programme_tag(buf, search_from)
                    if tag_start == -1:
                        break
                    if tag_end == -1 and chunk:
                        break  # incomplete tag, need more data

                    # Check channel before searching for close tag
                    m = _CHANNEL_ATTR_RE.search(
                        buf,
                        tag_start,
                        tag_end + 1 if tag_end != -1 else tag_start + _MAX_START_TAG,
                    )
                    if not m:
                        search_from = (
                            (tag_end + 1)
                            if tag_end != -1
                            else (tag_start + _PROGRAMME_TAG_LEN)
                        )
                        continue

                    ch = _decode_channel_id(m.group(1) or m.group(2))
                    if ch != tvg_id:
                        done = True  # different channel, end of block
                        break

                    # Find the closing </programme> tag
                    close_pos = buf.find(
                        PROG_CLOSE, tag_end + 1 if tag_end != -1 else m.end()
                    )
                    if close_pos == -1:
                        if not chunk:
                            done = True  # EOF with no close tag
                        break  # need more data
                    close_end = close_pos + CLOSE_LEN

                    element_bytes = bytes(buf[tag_start:close_end])
                    search_from = close_end

                    try:
                        prog = _parse_programme_element(element_bytes)
                    except etree.XMLSyntaxError:
                        continue

                    start_str = prog.get('start')
                    stop_str = prog.get('stop')
                    if not start_str or not stop_str:
                        continue
                    start_time = parse_xmltv_time(start_str)
                    end_time = parse_xmltv_time(stop_str)
                    if start_time is None or end_time is None:
                        continue
                    if start_time <= now < end_time:
                        return _programme_to_dict(prog, start_time, end_time)

                # Trim processed bytes
                if search_from > 0:
                    del buf[:search_from]
                    search_from = 0

                if not chunk:
                    break

    return None


def _scan_from_offset_for_tvg_id(file_path, tvg_id, start_offset, now, timeout_sec=10):
    """
    Scan forward from start_offset for tvg_id, skipping other channels rather than
    stopping at a channel boundary. Used for interleaved/time-sorted XMLTV files where
    a channel exceeded the stored offset cap.
    Returns dict, None, or 'timeout'.
    """
    PROG_CLOSE = b'</programme>'
    CLOSE_LEN = len(PROG_CLOSE)
    READ_SIZE = 2 * 1024 * 1024
    deadline = time.monotonic() + timeout_sec

    with open(file_path, 'rb') as f:
        f.seek(start_offset)
        buf = bytearray()

        while True:
            if time.monotonic() > deadline:
                return 'timeout'

            chunk = f.read(READ_SIZE)
            if not chunk and not buf:
                break
            buf.extend(chunk)
            search_from = 0

            trim_to = 0

            while True:
                tag_start, tag_end = _find_programme_tag(buf, search_from)
                if tag_start == -1:
                    trim_to = search_from
                    break
                if tag_end == -1 and chunk:
                    trim_to = tag_start  # keep incomplete tag for next read
                    break

                m = _CHANNEL_ATTR_RE.search(
                    buf,
                    tag_start,
                    tag_end + 1 if tag_end != -1 else tag_start + _MAX_START_TAG,
                )
                if not m:
                    search_from = (
                        tag_end + 1 if tag_end != -1 else tag_start + _PROGRAMME_TAG_LEN
                    )
                    continue

                ch = _decode_channel_id(m.group(1) or m.group(2))
                if ch != tvg_id:
                    search_from = (
                        tag_end + 1 if tag_end != -1 else tag_start + _PROGRAMME_TAG_LEN
                    )
                    continue

                close_pos = buf.find(
                    PROG_CLOSE, tag_end + 1 if tag_end != -1 else m.end()
                )
                if close_pos == -1:
                    trim_to = tag_start  # keep incomplete element for next read
                    break
                close_end = close_pos + CLOSE_LEN

                element_bytes = bytes(buf[tag_start:close_end])
                search_from = close_end

                try:
                    prog = _parse_programme_element(element_bytes)
                except etree.XMLSyntaxError:
                    continue

                start_str = prog.get('start')
                stop_str = prog.get('stop')
                if not start_str or not stop_str:
                    continue
                start_time = parse_xmltv_time(start_str)
                end_time = parse_xmltv_time(stop_str)
                if start_time is None or end_time is None:
                    continue
                if start_time <= now < end_time:
                    return _programme_to_dict(prog, start_time, end_time)

            if trim_to > 0:
                del buf[:trim_to]

            if not chunk:
                break

    return None
