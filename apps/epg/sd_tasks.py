"""
Schedules Direct EPG fetch pipeline and related Celery tasks.

Protocol helpers (headers, auth, lockouts, tokens) live in ``sd_utils``.
XMLTV / dummy EPG processing stays in ``tasks``.
"""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone as dt_timezone

import requests
from celery import shared_task
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.channels.models import Channel
from apps.epg.models import EPGData, EPGSource, ProgramData, SDProgramMD5, SDScheduleMD5
from apps.epg.sd_utils import SD_BASE_URL, sd_headers_for_source, sd_obtain_token
from core.utils import (
    acquire_task_lock,
    is_task_lock_held,
    log_system_event,
    release_task_lock,
    TaskLockRenewer,
)

logger = logging.getLogger(__name__)


def _send_epg_update(*args, **kwargs):
    """Lazy import to avoid circular import with apps.epg.tasks."""
    from apps.epg.tasks import send_epg_update
    return send_epg_update(*args, **kwargs)


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
        _send_epg_update(source.id, "parsing_programs", 100, status="error", error=msg)
        return None

    sd_lineup_country = _sd_fetch_lineup_country(token, sd_headers_fn)

    _send_epg_update(
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
        _send_epg_update(source.id, "parsing_programs", 100, status="idle", message=msg)
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
        _send_epg_update(source.id, "parsing_programs", 100, status="error", error=msg)
        return None

    sd_lineup_country = _sd_fetch_lineup_country(token, sd_headers_fn)
    _send_epg_update(
        source.id, "parsing_programs", 15,
        message=f"Fetching guide data for {len(station_map)} mapped stations...",
    )
    return station_map, epg_id_map, sd_lineup_country



@shared_task(
    name='apps.epg.tasks.fetch_sd_mapped_guide_batch',
    time_limit=3600,
    soft_time_limit=3500,
)
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


@shared_task(
    name='apps.epg.tasks.fetch_sd_guide_for_epg',
    time_limit=3600,
    soft_time_limit=3500,
)
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


@shared_task(name='apps.epg.tasks.fetch_schedules_direct_stations', bind=True)
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
        _send_epg_update(source.id, "refresh", 100, status="error", error=msg)
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
                _send_epg_update(source.id, "refresh", 100, status="idle", message=msg)
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
    from apps.epg.sd_utils import sd_headers_for_source, sd_obtain_token

    def _sd_headers(token=None, content_type='application/json'):
        return sd_headers_for_source(source, token=token, content_type=content_type)

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
            # Do not re-request artwork for URIs that SD already reported missing
            # (code 5000), unless the user changed poster_style (explicit retry).
            needs_poster_q = needs_poster_q & ~(
                Q(custom_properties__sd_icon_missing=True)
                & Q(custom_properties__sd_poster_style=poster_style)
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
            _send_epg_update(source.id, "parsing_programs", 98,
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
                            cp.pop('sd_icon_missing', None)
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
    _send_epg_update(source.id, "parsing_programs", 2, message="Authenticating with Schedules Direct...")

    auth = sd_obtain_token(source, username, password, timeout=30)
    if auth.debug_rejected:
        logger.error(auth.message)
        source.status = EPGSource.STATUS_ERROR
        source.last_message = auth.message
        source.save(update_fields=['status', 'last_message'])
        _send_epg_update(
            source.id, "refresh", 100, status="error", error=auth.message
        )
        return

    if not auth.ok:
        if auth.soft:
            logger.warning(auth.message)
            source.status = EPGSource.STATUS_IDLE
            source.last_message = auth.message
            source.save(update_fields=['status', 'last_message'])
            _send_epg_update(
                source.id, "refresh", 100, status="idle", message=auth.message
            )
            return
        logger.error(auth.message)
        source.status = EPGSource.STATUS_ERROR
        source.last_message = auth.message
        source.save(update_fields=['status', 'last_message'])
        _send_epg_update(
            source.id, "refresh", 100, status="error", error=auth.message
        )
        return

    token = auth.token
    logger.info("Schedules Direct authentication successful.")

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
            # retry for 1 hour. Next attempt is the next scheduled/manual refresh.
            msg = (
                "Schedules Direct system is currently offline. "
                "Do not retry for at least 1 hour."
            )
            logger.warning(msg)
            source.status = EPGSource.STATUS_IDLE
            source.last_message = msg
            source.save(update_fields=['status', 'last_message'])
            _send_epg_update(source.id, "refresh", 100, status="idle", message=msg)
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
        _send_epg_update(source.id, "parsing_programs", 10, message="Fetching subscribed lineups...")
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
                    _send_epg_update(source.id, "refresh", 100, status="idle", message=msg)
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
                _send_epg_update(source.id, "refresh", 100, status="idle", message=msg)
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
            _send_epg_update(source.id, "refresh", 100, status="error", error=msg)
            return

        # Build station metadata map: stationID -> {name, callsign, logo_url}
        station_map = {}
        _send_epg_update(source.id, "parsing_programs", 18, message=f"Fetching station metadata for {len(lineups)} lineup(s)...")
        for lineup in lineups:
            lineup_id = lineup.get('lineupID') or lineup.get('lineup')
            if not lineup_id:
                continue
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
            _send_epg_update(source.id, "refresh", 100, status="error", error=msg)
            return

        logger.info(f"Built station map with {len(station_map)} stations.")

        # -------------------------------------------------------------------------
        # Step 4: Persist station metadata to EPGData
        # -------------------------------------------------------------------------
        source.status = EPGSource.STATUS_PARSING
        source.last_message = f"Syncing {len(station_map)} stations..."
        source.save(update_fields=['status', 'last_message'])
        _send_epg_update(source.id, "parsing_programs", 28, message=f"Syncing {len(station_map)} stations to database...")

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

            if sid in existing_epg_map:
                epg_obj = existing_epg_map[sid]
                needs_update = False
                if epg_obj.name != display_name:
                    epg_obj.name = display_name
                    needs_update = True
                if epg_obj.icon_url != logo:
                    epg_obj.icon_url = logo
                    needs_update = True
                if needs_update:
                    epgs_to_update.append(epg_obj)
            else:
                epgs_to_create.append(EPGData(
                    tvg_id=sid,
                    name=display_name,
                    icon_url=logo,
                    epg_source=source,
                ))

        if epgs_to_create:
            EPGData.objects.bulk_create(epgs_to_create, ignore_conflicts=True)
            logger.info(f"Created {len(epgs_to_create)} new EPGData entries.")
        if epgs_to_update:
            EPGData.objects.bulk_update(epgs_to_update, ['name', 'icon_url'])
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
        _send_epg_update(source.id, "parsing_programs", 30,
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
            _send_epg_update(source.id, "parsing_channels", 100, status="success",
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
            _send_epg_update(source.id, "parsing_programs", 100, status="idle", message=msg)
            return
        if mapped_guide_batch:
            msg = "No mapped channels with guide data to fetch."
            source.last_message = msg
            source.save(update_fields=['last_message'])
            _send_epg_update(source.id, "parsing_programs", 100, status="idle", message=msg)
            return
        success_msg = (
            f"{len(station_map)} lineup stations synced. "
            "Map channels to EPG entries, then refresh to populate guide data."
        )
        source.status = EPGSource.STATUS_SUCCESS
        source.last_message = success_msg
        source.updated_at = timezone.now()
        source.save(update_fields=['status', 'last_message', 'updated_at'])
        _send_epg_update(source.id, "parsing_programs", 100, status="success", message=success_msg)
        return

    _send_epg_update(
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
    _send_epg_update(source.id, "parsing_programs", 38,
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
            _send_epg_update(source.id, "parsing_programs", 100, status="success", message=msg)
            return
        _send_epg_update(source.id, "parsing_programs", 100, status="success",
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
        _send_epg_update(source.id, "parsing_programs", min(59, pre_progress),
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
            _send_epg_update(source.id, "parsing_programs", min(60, progress),
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
        _send_epg_update(source.id, "parsing_programs", 100, status="error", error=msg)
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
            _send_epg_update(source.id, "parsing_programs", min(79, pre_progress),
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
                _send_epg_update(source.id, "parsing_programs", min(80, progress),
                                message=f"Fetching program details: batch {batch_idx + 1}/{total_batches} ({len(program_metadata):,} programs loaded)")
                logger.debug(f"Fetched program metadata batch {batch_idx + 1}/{total_batches}")

            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to fetch program metadata batch {batch_idx + 1}: {e}")
    else:
        logger.info("All program metadata unchanged - skipping program download.")
        _send_epg_update(source.id, "parsing_programs", 80, message="Program metadata unchanged - using cached data.")

    gc.collect()

    # -------------------------------------------------------------------------
    # Step 7: Build ProgramData records and persist atomically
    # -------------------------------------------------------------------------
    logger.info("Building program records...")
    _send_epg_update(source.id, "parsing_programs", 80)

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

    _send_epg_update(source.id, "parsing_programs", 88)

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
                _send_epg_update(source.id, "parsing_programs", min(98, progress))

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
        _send_epg_update(source.id, "parsing_programs", 100, status="error", error=msg)
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
        _send_epg_update(source.id, "parsing_programs", 100, status="success", message=success_msg)
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
        _send_epg_update(source.id, "parsing_programs", 100, status="success", message=success_msg)
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
    _send_epg_update(source.id, "parsing_programs", 100, status="success", message=success_msg)
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

def parse_schedules_direct_time(time_str):
    try:
        dt_obj = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%SZ')
        return timezone.make_aware(dt_obj, timezone=dt_timezone.utc)
    except Exception as e:
        logger.error(f"Error parsing Schedules Direct time '{time_str}': {e}", exc_info=True)
        raise
