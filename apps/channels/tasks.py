# apps/channels/tasks.py
import logging
import os
import select
import re
import requests
import time
import json
import shutil
import subprocess
import signal
import threading
from collections import deque
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
import gc

from celery import shared_task
from celery.signals import worker_shutting_down
from django.utils.text import slugify

from apps.channels.epg_matching import (
    apply_matched_epg_to_channels,
    build_epg_matching_catalog,
    cleanup_after_matching,
    match_channels_to_epg,
    normalize_name,
    run_single_channel_epg_match,
)
from apps.channels.models import Channel
from apps.epg.models import EPGData
from core.models import CoreSettings
from core.utils import acquire_task_lock, release_task_lock

from django.db import OperationalError, close_old_connections
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import tempfile
from urllib.parse import quote

logger = logging.getLogger(__name__)


# Flag set by the Celery `worker_shutting_down` signal so in-flight
# `run_recording` tasks can distinguish a graceful worker shutdown (e.g.
# `docker stop`, container update) from the natural end of a recording.
# When set, the post-FFmpeg path leaves the HLS working directory intact
# and marks the recording "interrupted" so `recover_recordings_on_startup`
# can resume it on the next boot via the existing path-reuse logic.
_DVR_SHUTTING_DOWN = False


@worker_shutting_down.connect
def _dvr_mark_shutting_down(**_kwargs):
    global _DVR_SHUTTING_DOWN
    _DVR_SHUTTING_DOWN = True


_url_validation_cache = {}
_URL_CACHE_TTL = 300  # seconds


def _validate_url(url, timeout=4):
    """Validate that an HTTP(S) URL is reachable via HEAD request.
    Returns True for non-HTTP URLs (skip validation) or 2xx/3xx responses.
    Results are cached per-worker for 5 minutes to avoid redundant requests
    when multiple recordings reference the same dead URL.
    """
    if not url or not isinstance(url, str):
        return False
    if not url.startswith(("http://", "https://")):
        return True

    now = time.monotonic()
    cached = _url_validation_cache.get(url)
    if cached is not None and (now - cached[1]) < _URL_CACHE_TTL:
        return cached[0]

    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 405:
            # Server doesn't support HEAD; fall back to ranged GET
            resp = requests.get(
                url, timeout=timeout, allow_redirects=True,
                headers={"Range": "bytes=0-0"}, stream=True,
            )
            resp.close()
        result = resp.status_code < 400
    except Exception:
        result = False

    _url_validation_cache[url] = (result, now)

    # Evict expired entries when cache grows large
    if len(_url_validation_cache) > 512:
        cutoff = now - _URL_CACHE_TTL
        expired = [k for k, v in _url_validation_cache.items() if v[1] < cutoff]
        for k in expired:
            del _url_validation_cache[k]

    return result


def _pick_best_image_from_epg_props(epg_props):
    """Select the highest-quality poster/cover image from EPG custom_properties."""
    try:
        images = epg_props.get("images") or []
        if not isinstance(images, list):
            return None
        size_order = {"xxl": 6, "xl": 5, "l": 4, "m": 3, "s": 2, "xs": 1}
        def score(img):
            t = (img.get("type") or "").lower()
            size = (img.get("size") or "").lower()
            return (2 if t in ("poster", "cover") else 1, size_order.get(size, 0))
        best = None
        for im in images:
            if not isinstance(im, dict):
                continue
            url = im.get("url")
            if not url:
                continue
            if best is None or score(im) > score(best):
                best = im
        return best.get("url") if best else None
    except Exception:
        return None


def _match_epg_program_by_timeslot(channel_epg_data, rec_start, rec_end):
    """Find an EPG program that covers at least 80% of the recording window.

    Queries all programs overlapping the recording, calculates overlap for
    each, and returns the best match only if it covers >= 80% of the
    recording duration.  Recordings spanning multiple programs with no
    dominant show return None (displayed as "Custom Recording").
    Returns a dict with id, title, sub_title, and description, or None.
    """
    if not channel_epg_data or not rec_start or not rec_end:
        return None
    try:
        candidates = channel_epg_data.programs.filter(
            start_time__lt=rec_end,
            end_time__gt=rec_start,
        ).only("id", "title", "sub_title", "description", "start_time", "end_time")

        rec_duration = (rec_end - rec_start).total_seconds()
        if rec_duration <= 0:
            return None

        best = None
        best_overlap = 0
        for prog in candidates:
            overlap_start = max(rec_start, prog.start_time)
            overlap_end = min(rec_end, prog.end_time)
            overlap = (overlap_end - overlap_start).total_seconds()
            if overlap > best_overlap:
                best_overlap = overlap
                best = prog

        if best and (best_overlap / rec_duration) >= 0.8:
            return {
                "id": best.id,
                "title": best.title or "",
                "sub_title": best.sub_title or "",
                "description": best.description or "",
            }
    except Exception:
        pass
    return None


def _db_retry(fn, max_retries=3, base_interval=1, label="DB operation"):
    """Execute fn() with exponential backoff retry on transient DB errors.

    Follows the same backoff pattern as RedisClient.get_client().
    Resets stale connections between attempts so the ORM reconnects.
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except OperationalError:
            if attempt + 1 >= max_retries:
                raise
            wait = base_interval * (2 ** attempt)
            logger.warning(
                f"{label}: failed, retrying in {wait}s "
                f"({attempt + 1}/{max_retries})..."
            )
            close_old_connections()
            time.sleep(wait)


# PostgreSQL btree index has a limit of ~2704 bytes (1/3 of 8KB page size)
# We use 2000 as a safe maximum to account for multibyte characters
def validate_logo_url(logo_url, max_length=2000):
    """
    Fast validation for logo URLs during bulk creation.
    Returns None if URL is too long (would exceed PostgreSQL btree index limit),
    original URL otherwise.

    PostgreSQL btree indexes have a maximum size of ~2704 bytes. URLs longer than
    this cannot be indexed and would cause database errors. These are typically
    base64-encoded images embedded in URLs.
    """
    if logo_url and len(logo_url) > max_length:
        logger.warning(f"Logo URL too long ({len(logo_url)} > {max_length}), skipping: {logo_url[:100]}...")
        return None
    return logo_url

@shared_task
def match_epg_channels():
    """
    Uses integrated EPG matching instead of external script.
    Provides the same functionality with better performance and maintainability.
    """
    try:
        logger.info("Starting integrated EPG matching...")

        # Get region preference
        try:
            region_obj = CoreSettings.objects.get(key="preferred-region")
            region_code = region_obj.value.strip().lower()
        except CoreSettings.DoesNotExist:
            region_code = None

        # Get channels that don't have EPG data assigned
        channels_without_epg = Channel.objects.filter(epg_data__isnull=True)
        logger.info(f"Found {channels_without_epg.count()} channels without EPG data")

        channels_data = []
        for channel in channels_without_epg:
            normalized_tvg_id = channel.tvg_id.strip().lower() if channel.tvg_id else ""
            normalized_gracenote_id = channel.tvc_guide_stationid.strip().lower() if channel.tvc_guide_stationid else ""
            channels_data.append({
                "id": channel.id,
                "name": channel.name,
                "tvg_id": normalized_tvg_id,
                "original_tvg_id": channel.tvg_id,
                "gracenote_id": normalized_gracenote_id,
                "original_gracenote_id": channel.tvc_guide_stationid,
                "fallback_name": normalized_tvg_id if normalized_tvg_id else channel.name,
                "norm_chan": normalize_name(channel.name),  # Always use channel name for fuzzy matching!
                "current_epg_data_id": channel.epg_data_id,
            })

        epg_data, epg_tvg_id_index = build_epg_matching_catalog()
        logger.info(f"Processing {len(channels_data)} channels against {len(epg_data)} EPG entries (from active sources only)")

        # Run EPG matching with progress updates - automatically uses conservative thresholds for bulk operations
        result = match_channels_to_epg(
            channels_data,
            epg_data,
            region_code,
            use_ml=True,
            send_progress=True,
            epg_tvg_id_index=epg_tvg_id_index,
        )
        channels_to_update_dicts = result["channels_to_update"]
        matched_channels = result["matched_channels"]
        unchanged_channels = result.get("unchanged_channels", [])

        changed_associations = apply_matched_epg_to_channels(channels_to_update_dicts)

        channels_updated = len(changed_associations)
        if channels_updated:
            logger.info(f"Match Summary: {channels_updated} channel(s) updated.")
            for (cid, cname, tvg) in matched_channels:
                logger.info(f"  - Channel '{cname}' (id={cid}) => tvg_id={tvg!r}")
        if unchanged_channels:
            logger.debug(
                f"{len(unchanged_channels)} channel(s) already correctly matched (unchanged)"
            )
        if not channels_updated and not unchanged_channels:
            logger.info("No channels were matched.")

        logger.info("Finished integrated EPG matching.")

        from core.utils import send_websocket_update

        if channels_updated:
            match_message = f"EPG matching complete: {channels_updated} channel(s) updated"
        elif unchanged_channels:
            match_message = (
                f"EPG matching complete: {len(unchanged_channels)} channel(s) "
                f"already correctly matched"
            )
        else:
            match_message = "EPG matching complete: no matches found"

        send_websocket_update(
            'updates',
            'update',
            {
                "success": True,
                "type": "epg_match",
                "refresh_channels": True,
                "matches_count": channels_updated,
                "message": match_message,
                "associations": changed_associations,
            },
        )

        return (
            f"Done. {channels_updated} channel(s) updated "
            f"({len(unchanged_channels)} unchanged)."
        )

    finally:
        cleanup_after_matching()
        from core.utils import cleanup_memory
        cleanup_memory(log_usage=True, force_collection=True)


@shared_task
def match_selected_channels_epg(channel_ids):
    """
    Match EPG data for only the specified selected channels.
    Uses the same integrated EPG matching logic but processes only selected channels.
    """
    try:
        logger.info(f"Starting integrated EPG matching for {len(channel_ids)} selected channels...")

        # Get region preference
        try:
            region_obj = CoreSettings.objects.get(key="preferred-region")
            region_code = region_obj.value.strip().lower()
        except CoreSettings.DoesNotExist:
            region_code = None

        # Selected-channel matching always runs, including channels that already have EPG.
        selected_channels = Channel.objects.filter(id__in=channel_ids)
        logger.info(f"Processing {selected_channels.count()} selected channel(s) for EPG matching")

        if not selected_channels.exists():
            logger.info("No selected channels found for EPG matching.")

            from core.utils import send_websocket_update

            send_websocket_update(
                'updates',
                'update',
                {
                    "success": True,
                    "type": "epg_match",
                    "refresh_channels": True,
                    "matches_count": 0,
                    "message": "No selected channels found for EPG matching",
                    "associations": [],
                },
            )
            return "No selected channels found for EPG matching."

        channels_data = []
        for channel in selected_channels:
            normalized_tvg_id = channel.tvg_id.strip().lower() if channel.tvg_id else ""
            normalized_gracenote_id = channel.tvc_guide_stationid.strip().lower() if channel.tvc_guide_stationid else ""
            channels_data.append({
                "id": channel.id,
                "name": channel.name,
                "tvg_id": normalized_tvg_id,
                "original_tvg_id": channel.tvg_id,
                "gracenote_id": normalized_gracenote_id,
                "original_gracenote_id": channel.tvc_guide_stationid,
                "fallback_name": normalized_tvg_id if normalized_tvg_id else channel.name,
                "norm_chan": normalize_name(channel.name),
                "current_epg_data_id": channel.epg_data_id,
            })

        epg_data, epg_tvg_id_index = build_epg_matching_catalog()
        logger.info(f"Processing {len(channels_data)} selected channels against {len(epg_data)} EPG entries (from active sources only)")

        # Run EPG matching with progress updates - automatically uses appropriate thresholds
        result = match_channels_to_epg(
            channels_data,
            epg_data,
            region_code,
            use_ml=True,
            send_progress=True,
            epg_tvg_id_index=epg_tvg_id_index,
        )
        channels_to_update_dicts = result["channels_to_update"]
        matched_channels = result["matched_channels"]
        unchanged_channels = result.get("unchanged_channels", [])

        changed_associations = apply_matched_epg_to_channels(channels_to_update_dicts)

        channels_updated = len(changed_associations)
        if channels_updated:
            logger.info(
                f"Selected Channel Match Summary: {channels_updated} channel(s) updated."
            )
            for (cid, cname, tvg) in matched_channels:
                logger.info(f"  - Channel '{cname}' (id={cid}) => tvg_id={tvg!r}")
        if unchanged_channels:
            logger.debug(
                f"{len(unchanged_channels)} selected channel(s) already correctly matched "
                f"(unchanged)"
            )
        if not channels_updated and not unchanged_channels:
            logger.info("No selected channels were matched.")

        logger.info("Finished integrated EPG matching for selected channels.")

        from core.utils import send_websocket_update

        if channels_updated:
            match_message = (
                f"EPG matching complete: {channels_updated} selected channel(s) updated"
            )
        elif unchanged_channels:
            match_message = (
                f"EPG matching complete: {len(unchanged_channels)} selected channel(s) "
                f"already correctly matched"
            )
        else:
            match_message = "EPG matching complete: no matches found"

        send_websocket_update(
            'updates',
            'update',
            {
                "success": True,
                "type": "epg_match",
                "refresh_channels": True,
                "matches_count": channels_updated,
                "message": match_message,
                "associations": changed_associations,
            },
        )

        return (
            f"Done. {channels_updated} selected channel(s) updated "
            f"({len(unchanged_channels)} unchanged)."
        )

    finally:
        cleanup_after_matching()
        from core.utils import cleanup_memory
        cleanup_memory(log_usage=True, force_collection=True)


@shared_task
def match_single_channel_epg(channel_id):
    """Match one channel to EPG data (async; results pushed via WebSocket)."""
    try:
        return run_single_channel_epg_match(channel_id)
    finally:
        from core.utils import cleanup_memory
        cleanup_memory(log_usage=True, force_collection=True)


def evaluate_series_rules_impl(tvg_id: str | None = None):
    """Synchronous implementation of series rule evaluation; returns details for debugging."""
    result = {"scheduled": 0, "details": []}

    # Serialize all invocations to prevent concurrent evaluations from
    # racing to create duplicate recordings (e.g. multiple EPG sources
    # refreshing simultaneously each firing evaluate_series_rules.delay()).
    # If Redis is unavailable, proceed without lock — the primary and
    # secondary dedup guards still prevent duplicates.
    lock_acquired = False
    try:
        lock_acquired = acquire_task_lock('evaluate_series_rules', 'all')
        if not lock_acquired:
            result["details"].append({"status": "skipped", "reason": "concurrent evaluation in progress"})
            return result
    except (ConnectionError, OSError, AttributeError):
        logger.warning("Could not acquire series rule evaluation lock (Redis unavailable), proceeding without lock")

    try:
        return _evaluate_series_rules_locked(tvg_id, result)
    finally:
        if lock_acquired:
            try:
                release_task_lock('evaluate_series_rules', 'all')
            except (ConnectionError, OSError, AttributeError):
                logger.warning("Could not release series rule evaluation lock")


def _evaluate_series_rules_locked(tvg_id, result):
    """Inner implementation of series rule evaluation, called under lock."""
    from django.utils import timezone
    from apps.channels.models import Recording, Channel
    from apps.epg.models import EPGData, ProgramData

    rules = CoreSettings.get_dvr_series_rules()
    if not isinstance(rules, list) or not rules:
        return result

    # Optionally filter for tvg_id
    if tvg_id:
        rules = [r for r in rules if str(r.get("tvg_id")) == str(tvg_id)]
        if not rules:
            result["details"].append({"tvg_id": tvg_id, "status": "no_rule"})
            return result

    now = timezone.now()
    horizon = now + timedelta(days=7)

    try:
        pre_min = int(CoreSettings.get_dvr_pre_offset_minutes())
    except Exception:
        pre_min = 0
    try:
        post_min = int(CoreSettings.get_dvr_post_offset_minutes())
    except Exception:
        post_min = 0

    # Preload existing recordings keyed by stable program attributes that
    # survive EPG refreshes (tvg_id + original start/end times stored in
    # custom_properties).  ProgramData.id changes on every EPG refresh so
    # it cannot be used for deduplication.  Only load future recordings
    # to bound the set size — past recordings cannot collide with newly
    # scheduled future programs.
    existing_program_keys = set()
    for cp in Recording.objects.filter(
        end_time__gte=now,
    ).values_list("custom_properties", flat=True):
        try:
            prog_data = (cp or {}).get("program", {})
            tvg_id_val = prog_data.get("tvg_id")
            st = prog_data.get("start_time")
            et = prog_data.get("end_time")
            if tvg_id_val and st and et:
                existing_program_keys.add((str(tvg_id_val), str(st), str(et)))
        except Exception:
            continue

    for rule in rules:
        rv_tvg = str(rule.get("tvg_id") or "").strip()
        mode = (rule.get("mode") or "all").lower()
        series_title = (rule.get("title") or "").strip()
        title_mode = (rule.get("title_mode") or "exact").lower()
        description = (rule.get("description") or "").strip()
        description_mode = (rule.get("description_mode") or "contains").lower()
        try:
            pinned_channel_id = int(rule["channel_id"]) if rule.get("channel_id") not in (None, "") else None
        except (TypeError, ValueError):
            pinned_channel_id = None
        if not series_title and not description:
            result["details"].append({"tvg_id": rv_tvg, "status": "invalid_rule"})
            continue

        if rv_tvg:
            epg = EPGData.objects.filter(tvg_id=rv_tvg).first()
            if not epg:
                result["details"].append({"tvg_id": rv_tvg, "status": "no_epg_match"})
                continue
            programs_qs = ProgramData.objects.filter(
                epg=epg,
                end_time__gt=now,
                start_time__lte=horizon,
            )
        else:
            epg = None
            programs_qs = ProgramData.objects.select_related("epg").filter(
                end_time__gt=now,
                start_time__lte=horizon,
            )

        from apps.epg.query_utils import parse_text_query

        if series_title:
            if title_mode == "exact":
                programs_qs = programs_qs.filter(title__iexact=series_title)
            else:
                use_regex = title_mode == "regex"
                whole_words = title_mode == "search"
                programs_qs = programs_qs.filter(
                    parse_text_query("title", series_title, use_regex=use_regex, whole_words=whole_words)
                )

        if description:
            use_regex = description_mode == "regex"
            whole_words = description_mode == "search"
            programs_qs = programs_qs.filter(
                parse_text_query("description", description, use_regex=use_regex, whole_words=whole_words)
            )

        programs = list(programs_qs.distinct().order_by("start_time"))

        if pinned_channel_id is not None:
            pinned_channel = Channel.objects.filter(id=pinned_channel_id).first()
            if pinned_channel is None:
                result["details"].append({"tvg_id": rv_tvg, "status": "pinned_channel_missing", "channel_id": pinned_channel_id})
                continue
            channels_by_epg_id = None
        elif rv_tvg:
            pinned_channel = Channel.objects.filter(epg_data=epg).order_by("channel_number").first()
            if not pinned_channel:
                result["details"].append({"tvg_id": rv_tvg, "status": "no_channel_for_epg"})
                continue
            channels_by_epg_id = None
        else:
            pinned_channel = None
            epg_ids = {p.epg_id for p in programs}
            channels_by_epg_id = {}
            for ch in Channel.objects.filter(epg_data_id__in=epg_ids).order_by("channel_number"):
                if ch.epg_data_id not in channels_by_epg_id:
                    channels_by_epg_id[ch.epg_data_id] = ch

        #
        # Many providers list multiple future airings of the same episode
        # (e.g., prime-time and a late-night repeat). Previously we scheduled
        # a recording for each airing which shows up as duplicates in the DVR.
        #
        # To avoid that, we collapse programs to the earliest airing per
        # unique episode using the best identifier available:
        #  - season+episode from ProgramData.custom_properties
        #  - onscreen_episode (e.g., S08E03)
        #  - sub_title (episode name), scoped by tvg_id+series title
        # If none of the above exist, we fall back to keeping each program
        # (usually movies or specials without episode identifiers).
        #
        def _episode_key(p: "ProgramData"):
            try:
                props = p.custom_properties or {}
                season = props.get("season")
                episode = props.get("episode")
                onscreen = props.get("onscreen_episode")
            except Exception:
                season = episode = onscreen = None
            base = f"{p.tvg_id or ''}|{(p.title or '').strip().lower()}"  # series scope
            if season is not None and episode is not None:
                return f"{base}|s{season}e{episode}"
            if onscreen:
                return f"{base}|{str(onscreen).strip().lower()}"
            if p.sub_title:
                return f"{base}|{p.sub_title.strip().lower()}"
            # No reliable episode identity; use the program id to avoid over-merging
            return f"id:{p.id}"

        # Optionally filter to only brand-new episodes before grouping
        if mode == "new":
            filtered = []
            for p in programs:
                try:
                    if (p.custom_properties or {}).get("new"):
                        filtered.append(p)
                except Exception:
                    pass
            programs = filtered

        # Pick the earliest airing for each episode key
        earliest_by_key = {}
        for p in programs:
            k = _episode_key(p)
            cur = earliest_by_key.get(k)
            if cur is None or p.start_time < cur.start_time:
                earliest_by_key[k] = p

        unique_programs = list(earliest_by_key.values())

        created_here = 0
        for prog in unique_programs:
            try:
                if pinned_channel is not None:
                    rec_channel = pinned_channel
                else:
                    rec_channel = channels_by_epg_id.get(prog.epg_id)
                    if rec_channel is None:
                        continue
                # Skip if a recording already exists for this exact airing
                # (keyed by tvg_id + original program times, which are stable
                # across EPG refreshes unlike ProgramData.id).
                prog_key = (str(prog.tvg_id), prog.start_time.isoformat(), prog.end_time.isoformat())
                if prog_key in existing_program_keys:
                    continue
                # Extra guard: DB query using the same stable attributes
                # stored in custom_properties (unadjusted program times,
                # not offset-adjusted Recording.start_time/end_time).
                try:
                    if Recording.objects.filter(
                        custom_properties__program__tvg_id=prog.tvg_id,
                        custom_properties__program__start_time=prog.start_time.isoformat(),
                        custom_properties__program__end_time=prog.end_time.isoformat(),
                    ).exists():
                        continue
                except Exception:
                    continue  # already scheduled/recorded

                adj_start = prog.start_time
                adj_end = prog.end_time
                try:
                    if pre_min and pre_min > 0:
                        adj_start = adj_start - timedelta(minutes=pre_min)
                except Exception:
                    pass
                try:
                    if post_min and post_min > 0:
                        adj_end = adj_end + timedelta(minutes=post_min)
                except Exception:
                    pass

                rec = Recording.objects.create(
                    channel=rec_channel,
                    start_time=adj_start,
                    end_time=adj_end,
                    custom_properties={
                        "program": {
                            "id": prog.id,
                            "tvg_id": prog.tvg_id,
                            "title": prog.title,
                            "sub_title": prog.sub_title,
                            "description": prog.description,
                            "start_time": prog.start_time.isoformat(),
                            "end_time": prog.end_time.isoformat(),
                        }
                    },
                )
                existing_program_keys.add(prog_key)
                created_here += 1
                try:
                    prefetch_recording_artwork.apply_async(args=[rec.id], countdown=1)
                except Exception:
                    pass
            except Exception as e:
                result["details"].append({"tvg_id": rv_tvg, "status": "error", "error": str(e)})
                continue
        result["scheduled"] += created_here
        result["details"].append({"tvg_id": rv_tvg, "title": series_title, "status": "ok", "created": created_here})

    # Notify frontend to refresh
    try:
        from core.utils import send_websocket_update
        send_websocket_update('updates', 'update', {"success": True, "type": "recordings_refreshed", "scheduled": result["scheduled"]})
    except Exception:
        pass

    return result


@shared_task
def evaluate_series_rules(tvg_id: str | None = None):
    return evaluate_series_rules_impl(tvg_id)


def reschedule_upcoming_recordings_for_offset_change_impl():
    """Recalculate start/end for all future EPG-based recordings using current DVR offsets.

    Only recordings that have not yet started (start_time > now) and that were
    scheduled from EPG data (custom_properties.program present) are updated.
    """
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    from apps.channels.models import Recording

    now = timezone.now()

    try:
        pre_min = int(CoreSettings.get_dvr_pre_offset_minutes())
    except Exception:
        pre_min = 0
    try:
        post_min = int(CoreSettings.get_dvr_post_offset_minutes())
    except Exception:
        post_min = 0

    changed = 0
    scanned = 0

    for rec in Recording.objects.filter(start_time__gt=now).iterator():
        scanned += 1
        try:
            cp = rec.custom_properties or {}
            program = cp.get("program") if isinstance(cp, dict) else None
            if not isinstance(program, dict):
                continue
            base_start = program.get("start_time")
            base_end = program.get("end_time")
            if not base_start or not base_end:
                continue
            start_dt = parse_datetime(str(base_start))
            end_dt = parse_datetime(str(base_end))
            if start_dt is None or end_dt is None:
                continue

            adj_start = start_dt
            adj_end = end_dt
            try:
                if pre_min and pre_min > 0:
                    adj_start = adj_start - timedelta(minutes=pre_min)
            except Exception:
                pass
            try:
                if post_min and post_min > 0:
                    adj_end = adj_end + timedelta(minutes=post_min)
            except Exception:
                pass

            if rec.start_time != adj_start or rec.end_time != adj_end:
                rec.start_time = adj_start
                rec.end_time = adj_end
                rec.save(update_fields=["start_time", "end_time"])
                changed += 1
        except Exception:
            continue

    # Notify frontend to refresh
    try:
        from core.utils import send_websocket_update
        send_websocket_update('updates', 'update', {"success": True, "type": "recordings_refreshed", "rescheduled": changed})
    except Exception:
        pass

    return {"changed": changed, "scanned": scanned, "pre": pre_min, "post": post_min}


@shared_task
def reschedule_upcoming_recordings_for_offset_change():
    return reschedule_upcoming_recordings_for_offset_change_impl()


def _notify_recordings_refresh():
    try:
        from core.utils import send_websocket_update
        send_websocket_update('updates', 'update', {"success": True, "type": "recordings_refreshed"})
    except Exception:
        pass


def purge_recurring_rule_impl(rule_id: int) -> int:
    """Remove all future recordings created by a recurring rule."""
    from django.utils import timezone
    from .models import Recording

    now = timezone.now()
    try:
        removed, _ = Recording.objects.filter(
            start_time__gte=now,
            custom_properties__rule__id=rule_id,
        ).delete()
    except Exception:
        removed = 0
    if removed:
        _notify_recordings_refresh()
    return removed


def sync_recurring_rule_impl(rule_id: int, drop_existing: bool = True, horizon_days: int = 14) -> int:
    """Ensure recordings exist for a recurring rule within the scheduling horizon."""
    from django.utils import timezone
    from .models import RecurringRecordingRule, Recording

    rule = RecurringRecordingRule.objects.filter(pk=rule_id).select_related("channel").first()
    now = timezone.now()
    removed = 0
    if drop_existing:
        removed = purge_recurring_rule_impl(rule_id)

    if not rule or not rule.enabled:
        return 0

    days = rule.cleaned_days()
    if not days:
        return 0

    tz_name = CoreSettings.get_system_time_zone()
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid or unsupported time zone '%s'; falling back to Server default", tz_name)
        tz = timezone.get_current_timezone()
    local_today = now.astimezone(tz).date()
    start_limit = rule.start_date or local_today
    end_limit = rule.end_date
    horizon = now + timedelta(days=horizon_days)
    start_window = max(start_limit, local_today)
    if drop_existing and end_limit:
        end_window = end_limit
    else:
        end_window = horizon.astimezone(tz).date()
        if end_limit and end_limit < end_window:
            end_window = end_limit
    if end_window < start_window:
        return 0
    total_created = 0

    for offset in range((end_window - start_window).days + 1):
        target_date = start_window + timedelta(days=offset)
        if target_date.weekday() not in days:
            continue
        if end_limit and target_date > end_limit:
            continue
        try:
            start_dt = timezone.make_aware(datetime.combine(target_date, rule.start_time), tz)
            end_dt = timezone.make_aware(datetime.combine(target_date, rule.end_time), tz)
        except Exception:
            continue
        if end_dt <= start_dt:
            end_dt = end_dt + timedelta(days=1)
        if start_dt <= now:
            continue
        exists = Recording.objects.filter(
            channel=rule.channel,
            start_time=start_dt,
            custom_properties__rule__id=rule.id,
        ).exists()
        if exists:
            continue
        description = rule.name or f"Recurring recording for {rule.channel.name}"
        cp = {
            "rule": {
                "type": "recurring",
                "id": rule.id,
                "days_of_week": days,
                "name": rule.name or "",
            },
            "status": "scheduled",
            "description": description,
            "program": {
                "title": rule.name or rule.channel.name,
                "description": description,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
            },
        }
        try:
            Recording.objects.create(
                channel=rule.channel,
                start_time=start_dt,
                end_time=end_dt,
                custom_properties=cp,
            )
            total_created += 1
        except Exception as err:
            logger.warning(f"Failed to create recurring recording for rule {rule.id}: {err}")

    if removed or total_created:
        _notify_recordings_refresh()

    return total_created


@shared_task
def rebuild_recurring_rule(rule_id: int, horizon_days: int = 14):
    return sync_recurring_rule_impl(rule_id, drop_existing=True, horizon_days=horizon_days)


@shared_task
def maintain_recurring_recordings():
    from .models import RecurringRecordingRule

    total = 0
    for rule_id in RecurringRecordingRule.objects.filter(enabled=True).values_list("id", flat=True):
        try:
            total += sync_recurring_rule_impl(rule_id, drop_existing=False)
        except Exception as err:
            logger.warning(f"Recurring rule maintenance failed for {rule_id}: {err}")
    return total


@shared_task
def purge_recurring_rule(rule_id: int):
    return purge_recurring_rule_impl(rule_id)

@shared_task
def _safe_name(s):
    try:
        import re
        s = s or ""
        # Remove forbidden filename characters and normalize spaces
        s = re.sub(r'[\\/:*?"<>|]+', '', s)
        s = s.strip()
        return s
    except Exception:
        return s or ""


def _parse_epg_tv_movie_info(program):
    """Return tuple (is_movie, season, episode, year, sub_title) from EPG ProgramData if available."""
    is_movie = False
    season = None
    episode = None
    year = None
    sub_title = program.get('sub_title') if isinstance(program, dict) else None
    try:
        from apps.epg.models import ProgramData
        prog_id = program.get('id') if isinstance(program, dict) else None
        epg_program = ProgramData.objects.filter(id=prog_id).only('custom_properties').first() if prog_id else None
        if epg_program and epg_program.custom_properties:
            cp = epg_program.custom_properties
            # Determine categories
            cats = [c.lower() for c in (cp.get('categories') or []) if isinstance(c, str)]
            is_movie = 'movie' in cats or 'film' in cats
            season = cp.get('season')
            episode = cp.get('episode')
            onscreen = cp.get('onscreen_episode')
            if (season is None or episode is None) and isinstance(onscreen, str):
                import re as _re
                m = _re.search(r'[sS](\d+)[eE](\d+)', onscreen)
                if m:
                    season = season or int(m.group(1))
                    episode = episode or int(m.group(2))
            d = cp.get('date')
            if d:
                year = str(d)[:4]
    except Exception:
        pass
    return is_movie, season, episode, year, sub_title


def _build_output_paths(channel, program, start_time, end_time, recording_id):
    """
    Build (final_path, hls_dir, final_filename) using DVR templates.

    The HLS working directory is hidden and tagged with the recording id
    (e.g. ``.dvr_71_hls``) so it cannot collide with another recording's
    files and so orphan-cleanup utilities can identify internal scratch
    directories unambiguously.
    """
    from core.models import CoreSettings
    # Root for DVR recordings: fixed to /data/recordings inside the container
    library_root = '/data/recordings'

    is_movie, season, episode, year, sub_title = _parse_epg_tv_movie_info(program)
    show = _safe_name(program.get('title') if isinstance(program, dict) else channel.name)
    title = _safe_name(program.get('title') if isinstance(program, dict) else channel.name)
    sub_title = _safe_name(sub_title)
    season = int(season) if season is not None else 0
    episode = int(episode) if episode is not None else 0
    year = year or str(start_time.year)

    values = {
        'show': show,
        'title': title,
        'sub_title': sub_title,
        'season': season,
        'episode': episode,
        'year': year,
        'channel': _safe_name(channel.name),
        'start': start_time.strftime('%Y%m%d_%H%M%S'),
        'end': end_time.strftime('%Y%m%d_%H%M%S'),
    }

    template = CoreSettings.get_dvr_movie_template() if is_movie else CoreSettings.get_dvr_tv_template()
    # Build relative path from templates with smart fallbacks
    rel_path = None
    if not is_movie and (season == 0 or episode == 0):
        # TV fallback template when S/E are missing
        try:
            tv_fb = CoreSettings.get_dvr_tv_fallback_template()
            rel_path = tv_fb.format(**values)
        except Exception:
            # Older setting support
            try:
                fallback_root = CoreSettings.get_dvr_tv_fallback_dir()
            except Exception:
                fallback_root = "TV_Shows"
            rel_path = f"{fallback_root}/{show}/{values['start']}.mkv"
    if not rel_path:
        try:
            rel_path = template.format(**values)
        except Exception:
            rel_path = None
    # Movie-specific fallback if formatting failed or title missing
    if is_movie and not rel_path:
        try:
            m_fb = CoreSettings.get_dvr_movie_fallback_template()
            rel_path = m_fb.format(**values)
        except Exception:
            rel_path = f"Movies/{values['start']}.mkv"
    # As a last resort for TV
    if not is_movie and not rel_path:
        rel_path = f"TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"
    # Keep any leading folder like 'Recordings/' from the template so users can
    # structure their library under /data as desired.
    if not rel_path.lower().endswith('.mkv'):
        rel_path = f"{rel_path}.mkv"

    # Normalize path (strip ./)
    if rel_path.startswith('./'):
        rel_path = rel_path[2:]
    final_path = rel_path if rel_path.startswith('/') else os.path.join(library_root, rel_path)
    final_path = os.path.normpath(final_path)

    # Avoid overwriting an existing MKV from a different recording.  The HLS
    # working directory is keyed by recording id, so it cannot collide and is
    # not part of this check.
    base, ext = os.path.splitext(final_path)
    counter = 1
    while True:
        try:
            mkv_occupied = os.stat(final_path).st_size > 0
        except OSError:
            mkv_occupied = False
        if not mkv_occupied:
            break
        counter += 1
        final_path = f"{base}_{counter}{ext}"

    # Ensure directory exists
    os.makedirs(os.path.dirname(final_path), exist_ok=True)

    # HLS working directory: hidden and id-tagged alongside the final MKV.
    hls_dir = os.path.join(os.path.dirname(final_path), f".dvr_{recording_id}_hls")
    return final_path, hls_dir, os.path.basename(final_path)


def _dvr_ffmpeg_retry_window_seconds():
    """Max continuous outage duration before giving up on FFmpeg restarts.
    """
    try:
        from apps.proxy.live_proxy.config_helper import ConfigHelper
        return ConfigHelper.stream_timeout() + ConfigHelper.failover_grace_period()
    except Exception:
        return 80.0


def _dvr_count_hls_segments(hls_dir):
    """Return the number of HLS segment files in hls_dir."""
    if not hls_dir or not os.path.isdir(hls_dir):
        return 0
    try:
        return sum(
            1 for f in os.listdir(hls_dir)
            if f.startswith("seg_") and f.endswith(".ts")
        )
    except OSError:
        return 0


def _dvr_max_hls_segment_index(hls_dir):
    """Return the highest ``seg_NNNNN.ts`` index in hls_dir, or -1 if none."""
    if not hls_dir or not os.path.isdir(hls_dir):
        return -1
    max_idx = -1
    try:
        for f in os.listdir(hls_dir):
            if not (f.startswith("seg_") and f.endswith(".ts")):
                continue
            try:
                max_idx = max(max_idx, int(f[4:9]))
            except ValueError:
                continue
    except OSError:
        return -1
    return max_idx


def _dvr_hls_playlist_has_segments(hls_m3u8):
    """Return True if the m3u8 lists at least one segment URI."""
    if not hls_m3u8 or not os.path.isfile(hls_m3u8):
        return False
    try:
        with open(hls_m3u8) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#'):
                    return True
    except OSError:
        pass
    return False


def _dvr_hls_start_number(hls_dir, hls_m3u8):
    """Return FFmpeg ``-start_number`` for an HLS recording (re)start.

    With ``append_list``, FFmpeg reloads existing segments from ``index.m3u8``
    and increments its internal sequence counter for each one.  Passing our
    segment count as ``-start_number`` double-counts (e.g. 14 on disk plus
    14 from ``-start_number`` → first new segment written as ``seg_00028.ts``).
    When the playlist already lists segments, use 0 and let ``append_list``
    derive the continuation.  When only loose ``.ts`` files remain, seed from
    the highest filename index + 1.
    """
    if _dvr_hls_playlist_has_segments(hls_m3u8):
        return 0
    max_idx = _dvr_max_hls_segment_index(hls_dir)
    return max_idx + 1 if max_idx >= 0 else 0


def _dvr_ffmpeg_retry_backoff_seconds(retry_index):
    """Backoff delay before FFmpeg restart (1-based retry index).

    Matches live-proxy StreamManager reconnect pacing so more attempts fit
    inside the outage window than a long exponential series would allow.
    """
    return min(0.25 * retry_index, 3.0)


def _dvr_build_ffmpeg_cmd(stream_url, recording_id, hls_m3u8, hls_seg_pattern, hls_start_number):
    """Build the FFmpeg command for DVR HLS segment recording."""
    from core.utils import dispatcharr_dvr_user_agent
    return [
        "ffmpeg", "-y",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-user_agent", dispatcharr_dvr_user_agent(recording_id),
        # Regenerate monotonic PTS to handle erratic/discontinuous timestamps
        # from IPTV sources.
        "-fflags", "+genpts",
        # Tolerate minor TS corruption without aborting the whole process.
        "-err_detect", "ignore_err",
        "-i", stream_url,
        "-c", "copy",
        # Shift output timestamps so they start from 0, fixing negative PTS
        # values that can prevent segment boundary detection in the HLS muxer.
        "-avoid_negative_ts", "make_zero",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "0",
        "-hls_flags", "append_list+omit_endlist+independent_segments",
        "-start_number", str(hls_start_number),
        "-hls_segment_filename", hls_seg_pattern,
        hls_m3u8,
    ]


def _dvr_build_hls_concat_cmd(concat_list_path, output_path, extra_args=None):
    """Build an error-tolerant FFmpeg concat command for HLS ``.ts`` segments.

    Tolerates truncated tail segments, timestamp discontinuities at FFmpeg
    restart splices, and minor MPEG-TS corruption from IPTV sources.  The
    concat demuxer already re-bases timestamps between files; ``genpts``,
    ``igndts``, and ``avoid_negative_ts`` keep the copied stream muxable.
    """
    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts+igndts+discardcorrupt",
        "-err_detect", "ignore_err",
        "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(output_path)
    return cmd


def _dvr_drain_ffmpeg_stderr(proc, rec_id, tail):
    """Drain FFmpeg stderr in a background thread (see run_recording for rationale)."""
    try:
        buf = bytearray()
        stream = proc.stderr
        while True:
            byte = stream.read(1)
            if not byte:
                break
            if byte in (b'\r', b'\n'):
                if buf:
                    line = buf.decode('utf-8', errors='replace').strip()
                    buf.clear()
                    if line:
                        tail.append(line)
                        low = line.lower()
                        if 'error' in low or 'failed' in low or 'invalid' in low:
                            logger.warning(f"DVR recording {rec_id} ffmpeg: {line}")
                        else:
                            logger.debug(f"DVR recording {rec_id} ffmpeg: {line}")
                continue
            buf.append(byte[0])
            if len(buf) > 4096:
                line = buf.decode('utf-8', errors='replace').strip()
                buf.clear()
                if line:
                    tail.append(line)
                    logger.debug(f"DVR recording {rec_id} ffmpeg: {line}")
        if buf:
            line = buf.decode('utf-8', errors='replace').strip()
            if line:
                tail.append(line)
                logger.debug(f"DVR recording {rec_id} ffmpeg: {line}")
    except Exception as _de:
        logger.debug(f"DVR recording {rec_id}: stderr drain ended: {_de}")


def _dvr_ensure_ffmpeg_exited(ffmpeg_proc, timeout=5):
    """Wait for FFmpeg to exit, force-kill if necessary."""
    if ffmpeg_proc is None or ffmpeg_proc.poll() is not None:
        return
    try:
        ffmpeg_proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        ffmpeg_proc.kill()
        try:
            ffmpeg_proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass


def get_dvr_stream_base_url():
    """Return the single correct base URL for DVR to reach the TS stream proxy.

    Priority:
    1. DISPATCHARR_INTERNAL_TS_BASE_URL — explicit override, always wins.
    2. Modular mode (DISPATCHARR_ENV=modular) — celery runs in a separate container
       and must reach the web container by its Docker service name on DISPATCHARR_PORT.
       Override the host with DISPATCHARR_WEB_HOST for non-standard compose setups.
    3. AIO / dev / debug — celery shares the container with uwsgi which binds on
       port 5656; use 127.0.0.1 to avoid any nginx layer.
    """
    explicit = os.environ.get('DISPATCHARR_INTERNAL_TS_BASE_URL')
    if explicit:
        return explicit.rstrip('/')

    dispatcharr_env = os.environ.get('DISPATCHARR_ENV', 'aio').lower()

    if dispatcharr_env == 'modular':
        host = os.environ.get('DISPATCHARR_WEB_HOST', 'web')
        port = os.environ.get('DISPATCHARR_PORT', '9191')
        return f'http://{host}:{port}'

    # AIO, dev, debug: celery and uwsgi share the container, reach uwsgi directly
    return 'http://127.0.0.1:5656'


@shared_task
def run_recording(recording_id, channel_id, start_time_str, end_time_str):
    """
    Execute a scheduled recording for the given channel/recording.

    Enhancements:
    - Accepts recording_id so we can persist metadata back to the Recording row
    - Persists basic file info (name/path) to Recording.custom_properties
    - Attempts to capture stream stats from TS proxy (codec, resolution, fps, etc.)
    - Attempts to capture a poster (via program.custom_properties) and store a Logo reference
    """
    from .models import Recording, Logo

    # --- Idempotency guard (prevents duplicate recordings from task redelivery) ---
    # Fail closed: if the DB is unreachable, abort rather than risk a duplicate
    # task overwriting a valid recording.
    try:
        rec_check = Recording.objects.filter(id=recording_id).only("custom_properties").first()
        if not rec_check:
            logger.info(
                f"run_recording called for recording {recording_id} but it no longer exists — skipping."
            )
            return
        status = (rec_check.custom_properties or {}).get("status", "")
        if status in ("recording", "completed", "stopped"):
            logger.warning(
                f"run_recording called for recording {recording_id} but status "
                f"is already '{status}' - skipping duplicate execution."
            )
            return
    except Exception as e:
        logger.error(
            f"Idempotency guard DB check failed for recording {recording_id} "
            f"({type(e).__name__}: {e}) — aborting to prevent potential duplicate."
        )
        return

    # --- Per-recording active lock (prevents concurrent ffmpeg processes
    # writing to the same HLS dir when duplicate recovery dispatches occur). ---
    # The lock is refreshed inside the main loop below; if a worker crashes
    # the TTL expires within ~45s and recovery can re-acquire it.
    _active_lock_key = f"dvr:recording-active:{recording_id}"
    _active_lock_ttl = 45
    _active_lock_redis = None
    try:
        from core.utils import RedisClient
        _active_lock_redis = RedisClient.get_client()
    except Exception:
        _active_lock_redis = None

    if _active_lock_redis is not None:
        try:
            if not _active_lock_redis.set(
                _active_lock_key, "1", ex=_active_lock_ttl, nx=True
            ):
                logger.warning(
                    f"run_recording {recording_id}: another worker holds the "
                    f"active-recording lock, aborting duplicate dispatch."
                )
                return
        except Exception as _le:
            logger.warning(
                f"run_recording {recording_id}: active-lock acquisition error "
                f"({type(_le).__name__}: {_le}), proceeding without lock."
            )
            _active_lock_redis = None

    # --- Clean up the one-off PeriodicTask that dispatched this task ---
    try:
        from apps.channels.signals import revoke_task, _dvr_task_name
        revoke_task(_dvr_task_name(recording_id))
    except Exception as e:
        logger.debug(f"PeriodicTask cleanup failed (non-fatal): {e}")

    channel = Channel.objects.get(id=channel_id)

    start_time = datetime.fromisoformat(start_time_str)
    end_time = datetime.fromisoformat(end_time_str)

    # Build output paths from templates (refined after loading Recording cp below)
    filename = None
    final_path = None
    hls_dir = None

    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        "updates",
        {
            "type": "update",
            "data": {"success": True, "type": "recording_started", "channel": channel.name}
        },
    )

    logger.info(f"Starting recording for channel {channel.name}")

    # Log system event for recording start
    try:
        from core.utils import log_system_event
        log_system_event(
            'recording_start',
            channel_id=channel.uuid,
            channel_name=channel.name,
            recording_id=recording_id
        )
    except Exception as e:
        logger.error(f"Could not log recording start event: {e}")

    # Try to resolve the Recording row up front
    recording_obj = None
    try:
        recording_obj = Recording.objects.get(id=recording_id)
        # If the stop endpoint already wrote "stopped" before the task started,
        # honor it instead of overwriting with "recording".
        _pre_cp = recording_obj.custom_properties or {}
        if _pre_cp.get("status") == "stopped":
            logger.info(
                f"run_recording {recording_id}: 'stopped' found in DB before stream started "
                f"— task exits without connecting."
            )
            return

        # Prime custom_properties with file info/status
        cp = recording_obj.custom_properties or {}
        cp.update({
            "status": "recording",
            "started_at": str(datetime.now()),
        })
        # Provide a predictable playback URL for the frontend
        cp["file_url"] = f"/api/channels/recordings/{recording_id}/hls/index.m3u8"
        cp["output_file_url"] = cp["file_url"]

        # Determine program info (may include id for deeper details)
        program = cp.get("program") or {}

        # Enrich empty program dicts (manual recordings) from EPG time-slot data.
        if isinstance(program, dict) and not program.get("user_edited") and not program.get("id") and not program.get("title"):
            epg_match = _match_epg_program_by_timeslot(
                channel.epg_data, recording_obj.start_time, recording_obj.end_time,
            )
            if epg_match:
                program.update(epg_match)
                cp["program"] = program

        # Resume into the existing working set if this task is a recovery run.
        # `recover_recordings_on_startup` re-dispatches `run_recording` for an
        # interrupted recording with `_hls_dir` and `file_path` already set in
        # custom_properties.  Re-running `_build_output_paths` would allocate a
        # fresh `Foo_2.mkv` / `.dvr_{id}_hls` pair and orphan the original
        # segments, producing two MKVs at the end.  Reuse the original paths
        # whenever the HLS directory is still on disk.
        existing_hls = cp.get("_hls_dir")
        existing_file = cp.get("file_path")
        if (
            existing_hls
            and existing_file
            and os.path.isdir(existing_hls)
        ):
            final_path = existing_file
            hls_dir = existing_hls
            filename = os.path.basename(final_path)
            try:
                _seg_count = sum(
                    1 for f in os.listdir(hls_dir) if f.endswith(".ts")
                )
            except OSError:
                _seg_count = 0
            logger.info(
                f"run_recording {recording_id}: resuming into existing HLS dir "
                f"{hls_dir} ({_seg_count} segment(s)), final={final_path}"
            )
        else:
            final_path, hls_dir, filename = _build_output_paths(
                channel, program, start_time, end_time, recording_id
            )
        cp["file_name"] = filename
        cp["file_path"] = final_path
        cp["_hls_dir"] = hls_dir

        # Resolve poster art via the shared pipeline (EPG → VOD → TMDB/OMDb →
        # TVMaze/iTunes → direct program fields → Logo table → channel logo).
        poster_logo_id, poster_url = _resolve_poster_for_program(
            channel.name, program, channel_logo_id=channel.logo_id,
        )
        if poster_logo_id:
            cp["poster_logo_id"] = poster_logo_id
        if poster_url and "poster_url" not in cp:
            cp["poster_url"] = poster_url

        # Ensure destination directory exists.  No placeholder MKV is created
        # here on purpose: with the HLS pipeline, the final MKV is materialized
        # by the post-recording concat step, and `/file/` redirects to `/hls/`
        # while no MKV exists, so a 0-byte placeholder serves no functional
        # purpose.  Writing one previously caused an orphan-file bug on server
        # restart in cases where the resume path could not adopt the original
        # final_path, since the second run would generate a fresh placeholder
        # at a new path and leave the original behind.
        try:
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
        except Exception:
            pass

        # Re-read from DB to preserve concurrent changes (e.g., artwork
        # prefetch may have saved poster/rating info while resolving).
        recording_obj.refresh_from_db()
        fresh_cp = recording_obj.custom_properties or {}

        # If the stop endpoint set "stopped" while resolving, honor it.
        if fresh_cp.get("status") == "stopped":
            logger.info(
                f"run_recording {recording_id}: 'stopped' found after metadata "
                f"prep — task exits without streaming."
            )
            return

        # Merge only the keys explicitly set into the fresh copy
        for key in ("status", "started_at", "file_url", "output_file_url",
                     "file_name", "file_path", "_hls_dir",
                     "program", "poster_logo_id", "poster_url"):
            if key in cp:
                fresh_cp[key] = cp[key]
        recording_obj.custom_properties = fresh_cp
        recording_obj.save(update_fields=["custom_properties"])

        # Notify frontends so the tile picks up poster/metadata immediately
        try:
            from core.utils import send_websocket_update
            send_websocket_update('updates', 'update', {
                "success": True,
                "type": "recording_updated",
                "recording_id": recording_id,
            })
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"Unable to prime Recording metadata: {e}")
    interrupted = False
    interrupted_reason = None
    bytes_written = 0

    base_url = get_dvr_stream_base_url()
    logger.info(f"DVR recording {recording_id}: using stream base URL {base_url}")

    # --- DB retry constants ---
    _dvr_db_max_retries = 3
    _dvr_db_retry_interval = 1  # seconds (base for exponential backoff)

    # Redis key used to signal that an HLS client is actively fetching segments.
    # The hls endpoint refreshes this on every .ts request; we check it before
    # deleting the HLS directory so in-flight downloads are not cut short.
    _hls_viewer_key = f"dvr:hls_viewer:{recording_id}"

    # --- HLS recording pipeline ---
    # Launch FFmpeg with the deterministic base URL resolved above.  Wait up to
    # _first_segment_timeout seconds for the first segment to appear before
    # treating the stream as unavailable.
    from django.utils import timezone as _tz

    last_error = None
    ffmpeg_proc = None
    hls_m3u8 = None
    hls_seg_pattern = None
    _stream_confirmed = False

    if hls_dir:
        os.makedirs(hls_dir, exist_ok=True)
        hls_m3u8 = os.path.join(hls_dir, "index.m3u8")
        hls_seg_pattern = os.path.join(hls_dir, "seg_%05d.ts")

    base = base_url

    if not interrupted:
        # Check for stop/delete before starting
        try:
            _pre = Recording.objects.filter(id=recording_id).only("custom_properties").first()
            if _pre is None:
                interrupted = True
                interrupted_reason = "recording_deleted"
            elif (_pre.custom_properties or {}).get("status") == "stopped":
                interrupted = False
                interrupted_reason = "stopped_by_user"
        except Exception:
            pass

    end_timestamp = end_time.timestamp()
    _stop_poll_interval = 2.0
    _first_segment_timeout = 15.0
    _stall_timeout = 60.0  # seconds without new segments → source stream gone
    _active_lock_refresh_interval = 15.0
    _ffmpeg_stderr_tail = deque(maxlen=200)
    _break_reason = None
    _ffmpeg_retry_count = 0
    _ffmpeg_outage_started = None
    _ffmpeg_retry_window = _dvr_ffmpeg_retry_window_seconds()

    if not interrupted and hls_dir:
        stream_url = f"{base}/proxy/ts/stream/{channel.uuid}"
        logger.info(f"DVR recording {recording_id}: stream URL: {stream_url}")
        logger.info(f"DVR recording {recording_id}: HLS output dir: {hls_dir}")
        logger.info(
            f"DVR recording {recording_id}: FFmpeg outage retry window "
            f"is {_ffmpeg_retry_window:.0f}s (stream_timeout + failover_grace_period)"
        )

        while (
            not interrupted
            and time.time() < end_timestamp
            and not _DVR_SHUTTING_DOWN
            and (
                _ffmpeg_outage_started is None
                or time.time() - _ffmpeg_outage_started < _ffmpeg_retry_window
            )
        ):
            if _ffmpeg_retry_count > 0:
                _outage_elapsed = time.time() - _ffmpeg_outage_started
                _backoff = min(
                    _dvr_ffmpeg_retry_backoff_seconds(_ffmpeg_retry_count),
                    max(0.0, _ffmpeg_retry_window - _outage_elapsed),
                )
                if _backoff <= 0:
                    logger.warning(
                        f"DVR recording {recording_id}: FFmpeg outage window "
                        f"({_ffmpeg_retry_window:.0f}s) exhausted after "
                        f"{_outage_elapsed:.0f}s (last reason={_break_reason})"
                    )
                    break
                logger.info(
                    f"DVR recording {recording_id}: retrying FFmpeg in {_backoff:.0f}s "
                    f"(outage {_outage_elapsed:.0f}s / {_ffmpeg_retry_window:.0f}s, "
                    f"attempt {_ffmpeg_retry_count + 1}, last reason={_break_reason})"
                )
                _backoff_deadline = time.time() + _backoff
                while time.time() < _backoff_deadline:
                    if _DVR_SHUTTING_DOWN or time.time() >= end_timestamp:
                        break
                    if (
                        _ffmpeg_outage_started is not None
                        and time.time() - _ffmpeg_outage_started >= _ffmpeg_retry_window
                    ):
                        break
                    try:
                        _pre_retry = Recording.objects.filter(
                            id=recording_id
                        ).only("custom_properties").first()
                        if _pre_retry is None:
                            interrupted = True
                            interrupted_reason = "recording_deleted"
                            break
                        if (_pre_retry.custom_properties or {}).get("status") == "stopped":
                            _break_reason = "stopped"
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
                if interrupted or _break_reason == "stopped" or _DVR_SHUTTING_DOWN:
                    break
                if time.time() >= end_timestamp:
                    break
                if (
                    _ffmpeg_outage_started is not None
                    and time.time() - _ffmpeg_outage_started >= _ffmpeg_retry_window
                ):
                    logger.warning(
                        f"DVR recording {recording_id}: FFmpeg outage window "
                        f"({_ffmpeg_retry_window:.0f}s) exhausted during backoff "
                        f"(last reason={_break_reason})"
                    )
                    break

            hls_start_number = _dvr_hls_start_number(hls_dir, hls_m3u8)
            ffmpeg_cmd = _dvr_build_ffmpeg_cmd(
                stream_url, recording_id, hls_m3u8, hls_seg_pattern, hls_start_number,
            )

            logger.info(
                f"DVR recording {recording_id}: starting FFmpeg "
                f"(attempt {_ffmpeg_retry_count + 1}, segment start={hls_start_number}, "
                f"{_dvr_count_hls_segments(hls_dir)} existing segment(s))"
            )
            logger.debug(
                f"DVR recording {recording_id}: FFmpeg command: "
                f"{' '.join(str(a) for a in ffmpeg_cmd)}"
            )

            ffmpeg_proc = None
            _break_reason = None
            _attempt_stream_confirmed = False

            try:
                ffmpeg_proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except Exception as _fe:
                last_error = str(_fe)
                logger.warning(
                    f"DVR recording {recording_id}: failed to launch FFmpeg: {_fe}"
                )
                _break_reason = "launch_failed"

            if ffmpeg_proc is not None and ffmpeg_proc.stderr is not None:
                _stderr_thread = threading.Thread(
                    target=_dvr_drain_ffmpeg_stderr,
                    args=(ffmpeg_proc, recording_id, _ffmpeg_stderr_tail),
                    daemon=True,
                    name=f"dvr-ffmpeg-stderr-{recording_id}-{_ffmpeg_retry_count}",
                )
                _stderr_thread.start()

            _last_stop_poll = time.time()
            _ffmpeg_start = time.time()
            _last_seg_count = hls_start_number
            _last_new_seg_time = time.time()
            _last_active_lock_refresh = 0.0

            if ffmpeg_proc is not None:
                while ffmpeg_proc.poll() is None:
                    time.sleep(0.5)
                    now = time.time()

                    if _DVR_SHUTTING_DOWN:
                        logger.info(
                            f"DVR recording {recording_id}: worker shutting down — stopping FFmpeg"
                        )
                        ffmpeg_proc.send_signal(signal.SIGINT)
                        try:
                            ffmpeg_proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            ffmpeg_proc.kill()
                        _break_reason = "server_shutdown"
                        break

                    if (
                        _active_lock_redis is not None
                        and now - _last_active_lock_refresh >= _active_lock_refresh_interval
                    ):
                        try:
                            _active_lock_redis.expire(_active_lock_key, _active_lock_ttl)
                        except Exception:
                            pass
                        _last_active_lock_refresh = now

                    segs_now = [
                        f for f in os.listdir(hls_dir)
                        if f.startswith("seg_") and f.endswith(".ts")
                    ]

                    if not _attempt_stream_confirmed:
                        if len(segs_now) > _last_seg_count:
                            _attempt_stream_confirmed = True
                            _stream_confirmed = True
                            _ffmpeg_outage_started = None
                            _ffmpeg_retry_count = 0
                            _last_seg_count = len(segs_now)
                            _last_new_seg_time = now
                            logger.info(
                                f"DVR recording {recording_id}: HLS segment written, "
                                f"stream confirmed"
                            )
                        else:
                            try:
                                if segs_now:
                                    _newest = max(segs_now)
                                    _newest_mtime = os.path.getmtime(
                                        os.path.join(hls_dir, _newest)
                                    )
                                    if _newest_mtime >= _ffmpeg_start:
                                        _attempt_stream_confirmed = True
                                        _stream_confirmed = True
                                        _ffmpeg_outage_started = None
                                        _ffmpeg_retry_count = 0
                                        _last_new_seg_time = _newest_mtime
                                        logger.info(
                                            f"DVR recording {recording_id}: HLS segment "
                                            f"activity detected, stream confirmed"
                                        )
                            except Exception:
                                pass
                        if (
                            not _attempt_stream_confirmed
                            and now - _ffmpeg_start > _first_segment_timeout
                        ):
                            logger.warning(
                                f"DVR recording {recording_id}: no HLS segments produced "
                                f"after {_first_segment_timeout}s from {base} — stream unavailable"
                            )
                            ffmpeg_proc.kill()
                            try:
                                ffmpeg_proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                pass
                            last_error = f"no_segments_in_{_first_segment_timeout}s_from_{base}"
                            _break_reason = "no_segments"
                            break
                    else:
                        if len(segs_now) > _last_seg_count:
                            _last_seg_count = len(segs_now)
                            _last_new_seg_time = now
                        else:
                            try:
                                if segs_now:
                                    _newest = max(segs_now)
                                    _newest_mtime = os.path.getmtime(
                                        os.path.join(hls_dir, _newest)
                                    )
                                    if _newest_mtime > _last_new_seg_time:
                                        _last_new_seg_time = _newest_mtime
                            except Exception:
                                pass
                        if now - _last_new_seg_time > _stall_timeout:
                            logger.warning(
                                f"DVR recording {recording_id}: no new HLS segments for "
                                f"{_stall_timeout:.0f}s — source stream stalled, stopping FFmpeg"
                            )
                            ffmpeg_proc.send_signal(signal.SIGINT)
                            try:
                                ffmpeg_proc.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                ffmpeg_proc.kill()
                            _break_reason = "stall"
                            break

                    if now >= end_timestamp:
                        logger.info(
                            f"DVR recording {recording_id}: scheduled end time reached, "
                            f"stopping FFmpeg"
                        )
                        ffmpeg_proc.send_signal(signal.SIGINT)
                        try:
                            ffmpeg_proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            ffmpeg_proc.kill()
                        _break_reason = "end_time"
                        break

                    if now - _last_stop_poll >= _stop_poll_interval:
                        _last_stop_poll = now
                        try:
                            _sc = Recording.objects.filter(
                                id=recording_id
                            ).only("custom_properties", "end_time").first()
                            if _sc is None:
                                logger.info(
                                    f"DVR recording {recording_id}: deleted — stopping FFmpeg"
                                )
                                ffmpeg_proc.send_signal(signal.SIGINT)
                                try:
                                    ffmpeg_proc.wait(timeout=10)
                                except subprocess.TimeoutExpired:
                                    ffmpeg_proc.kill()
                                interrupted = False
                                _break_reason = "deleted"
                                break
                            if (_sc.custom_properties or {}).get("status") == "stopped":
                                logger.info(
                                    f"DVR recording {recording_id}: stop requested — stopping FFmpeg"
                                )
                                ffmpeg_proc.send_signal(signal.SIGINT)
                                try:
                                    ffmpeg_proc.wait(timeout=10)
                                except subprocess.TimeoutExpired:
                                    ffmpeg_proc.kill()
                                _break_reason = "stopped"
                                break
                            try:
                                new_end = _sc.end_time
                                if new_end is not None:
                                    if _tz.is_naive(new_end):
                                        new_end = _tz.make_aware(new_end)
                                    new_ts = new_end.timestamp()
                                    if new_ts > end_timestamp:
                                        logger.info(
                                            f"DVR recording {recording_id}: end_time extended "
                                            f"to {new_end}"
                                        )
                                        end_timestamp = new_ts
                            except Exception:
                                pass
                        except Exception:
                            pass

                if _break_reason is None:
                    if time.time() >= end_timestamp:
                        _break_reason = "end_time"
                    elif ffmpeg_proc.poll() is not None:
                        _break_reason = "unexpected_exit"
                        _exit_code = ffmpeg_proc.poll()
                        if _stream_confirmed and _exit_code not in (0, None):
                            logger.warning(
                                f"DVR recording {recording_id}: FFmpeg exited unexpectedly "
                                f"(rc={_exit_code}) after stream was confirmed — "
                                f"source stream likely disconnected"
                            )
                        elif not _stream_confirmed:
                            last_error = f"rc={_exit_code} from {base}"
                            _tail_text = "\n".join(_ffmpeg_stderr_tail)
                            if _tail_text:
                                logger.warning(
                                    f"DVR recording {recording_id}: FFmpeg exited "
                                    f"(rc={_exit_code}) for {base} without producing "
                                    f"segments.\nFFmpeg stderr tail:\n{_tail_text[-1000:]}"
                                )
                            else:
                                logger.warning(
                                    f"DVR recording {recording_id}: FFmpeg exited "
                                    f"(rc={_exit_code}) for {base} without producing "
                                    f"segments (no stderr output)"
                                )

            _dvr_ensure_ffmpeg_exited(ffmpeg_proc)

            if _break_reason in ("end_time", "stopped", "deleted"):
                break

            if _DVR_SHUTTING_DOWN or time.time() >= end_timestamp:
                break

            if _ffmpeg_outage_started is None:
                _ffmpeg_outage_started = time.time()

            _outage_elapsed = time.time() - _ffmpeg_outage_started
            if _outage_elapsed >= _ffmpeg_retry_window:
                logger.warning(
                    f"DVR recording {recording_id}: FFmpeg outage window "
                    f"({_ffmpeg_retry_window:.0f}s) exhausted "
                    f"(last reason={_break_reason})"
                )
                break

            _ffmpeg_retry_count += 1
            logger.info(
                f"DVR recording {recording_id}: FFmpeg stopped early "
                f"(reason={_break_reason}), scheduling retry "
                f"({_outage_elapsed:.0f}s / {_ffmpeg_retry_window:.0f}s into outage window)"
            )

    _dvr_ensure_ffmpeg_exited(ffmpeg_proc)

    if (
        _stream_confirmed
        and not interrupted
        and _break_reason not in ("end_time", "stopped", "deleted", "server_shutdown")
        and time.time() < end_timestamp
        and not _DVR_SHUTTING_DOWN
    ):
        interrupted = True
        interrupted_reason = (
            f"ffmpeg_outage_window_exhausted: {_break_reason or last_error or 'unknown'}"
        )

    # If the loop broke because the Celery worker is shutting down (e.g.
    # docker stop, container update) and the recording window is still open,
    # leave the HLS working directory intact and mark the recording as
    # interrupted.  `recover_recordings_on_startup` will re-dispatch this task
    # on the next boot, and the resume-path logic in the prep block will
    # adopt the existing `_hls_dir` and `file_path` so FFmpeg appends to the
    # same playlist and the eventual concat produces a single MKV.
    #
    # Note: `_DVR_SHUTTING_DOWN` is per-process. The DVR queue currently uses
    # a threads pool worker (one process, all threads see the flag). If the
    # DVR queue is ever switched back to prefork, the parent's flag will not
    # propagate to in-flight child workers.
    if _DVR_SHUTTING_DOWN and time.time() < end_timestamp:
        try:
            _shutdown_rec = Recording.objects.filter(id=recording_id).first()
            if _shutdown_rec:
                _shutdown_cp = _shutdown_rec.custom_properties or {}
                # Preserve _hls_dir / file_path / file_url exactly as they are
                # so the HLS endpoint keeps serving until the worker dies and
                # so recovery can find the working directory on next boot.
                _shutdown_cp["status"] = "interrupted"
                _shutdown_cp["interrupted_reason"] = "server_shutdown"
                _shutdown_cp["ended_at"] = str(datetime.now())
                _shutdown_rec.custom_properties = _shutdown_cp
                _shutdown_rec.save(update_fields=["custom_properties"])
        except Exception as _se:
            logger.warning(
                f"DVR recording {recording_id}: failed to flag interrupted on shutdown: {_se}"
            )
        logger.info(
            f"DVR recording {recording_id}: worker shutting down with "
            f"{int(end_timestamp - time.time())}s of recording window remaining; "
            f"leaving HLS dir intact for resume on next boot, skipping concat."
        )
        return

    if not _stream_confirmed and not interrupted:
        interrupted = True
        interrupted_reason = f"no_stream_data: {last_error or 'ffmpeg_failed'}"

    # Measure bytes from HLS segment files
    try:
        bytes_written = sum(
            os.path.getsize(os.path.join(hls_dir, f))
            for f in os.listdir(hls_dir)
            if f.startswith("seg_") and f.endswith(".ts")
        ) if hls_dir and os.path.isdir(hls_dir) else 0
    except Exception:
        bytes_written = 0
    if bytes_written == 0 and not interrupted:
        _deliberately_stopped = False
        try:
            _rc = Recording.objects.filter(id=recording_id).only("custom_properties").first()
            if _rc and (_rc.custom_properties or {}).get("status") == "stopped":
                _deliberately_stopped = True
        except Exception:
            pass

        if not _deliberately_stopped:
            interrupted = True
            interrupted_reason = f"no_stream_data: {last_error or 'unknown'}"

            # Update DB status immediately so the UI reflects the change on the event below
            try:
                if recording_obj is None:
                    recording_obj = Recording.objects.get(id=recording_id)
                cp_now = recording_obj.custom_properties or {}
                cp_now.update({
                    "status": "interrupted",
                    "ended_at": str(datetime.now()),
                    "file_name": filename or cp_now.get("file_name"),
                    "file_path": final_path or cp_now.get("file_path"),
                    "interrupted_reason": interrupted_reason,
                })
                recording_obj.custom_properties = cp_now
                recording_obj.save(update_fields=["custom_properties"])
            except Exception as e:
                logger.debug(f"Failed to update immediate recording status: {e}")

            async_to_sync(channel_layer.group_send)(
                "updates",
                {
                    "type": "update",
                    "data": {"success": True, "type": "recording_ended", "channel": channel.name}
                },
            )
            # After the loop, the file and response are closed automatically.
            logger.info(f"Finished recording for channel {channel.name}")

    # Log system event for recording end
    try:
        from core.utils import log_system_event
        log_system_event(
            'recording_end',
            channel_id=channel.uuid,
            channel_name=channel.name,
            recording_id=recording_id,
            interrupted=interrupted,
            bytes_written=bytes_written
        )
    except Exception as e:
        logger.error(f"Could not log recording end event: {e}")

    # If the Recording was deleted (cancelled by user), skip post-processing
    recording_cancelled = not Recording.objects.filter(id=recording_id).exists()
    if recording_cancelled:
        logger.info(f"Recording {recording_id} was cancelled — skipping remux and metadata.")
        # Clean up all artifacts for the cancelled recording,
        # including any pre-restart .ts segments from server recovery.
        # Use the in-memory recording_obj since the DB row is already deleted.
        if hls_dir and os.path.isdir(hls_dir):
            try:
                shutil.rmtree(hls_dir)
                logger.info(f"Cleaned up cancelled recording HLS directory: {hls_dir}")
            except Exception as _e:
                logger.warning(f"Failed to remove HLS directory {hls_dir}: {_e}")
        if final_path:
            try:
                if os.path.exists(final_path):
                    os.remove(final_path)
                    logger.info(f"Cleaned up cancelled recording MKV placeholder: {final_path}")
            except Exception:
                pass
        return

    # --- Post-processing: concat HLS segments → final MKV ---
    remux_success = False
    hls_m3u8 = os.path.join(hls_dir, "index.m3u8") if hls_dir else None

    def _get_hls_segments(m3u8_path, seg_dir):
        """Return ordered segment paths from an HLS m3u8 playlist."""
        segs = []
        try:
            with open(m3u8_path) as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith('#'):
                        sp = os.path.join(seg_dir, _line) if not os.path.isabs(_line) else _line
                        if os.path.exists(sp):
                            segs.append(sp)
        except Exception as _e:
            logger.warning(f"DVR recording {recording_id}: failed to parse m3u8: {_e}")
        return segs

    segments = (
        _get_hls_segments(hls_m3u8, hls_dir)
        if (hls_m3u8 and os.path.exists(hls_m3u8))
        else []
    )
    if not segments and hls_dir and os.path.isdir(hls_dir):
        # Fallback: sort all segment files by name if m3u8 is missing or empty
        try:
            segments = sorted(
                os.path.join(hls_dir, f)
                for f in os.listdir(hls_dir)
                if f.startswith("seg_") and f.endswith(".ts")
            )
        except Exception:
            segments = []

    if segments:
        concat_list_path = os.path.join(hls_dir, "concat.txt")
        try:
            with open(concat_list_path, "w") as _cl:
                for seg in segments:
                    _escaped = seg.replace("'", "'\\''")
                    _cl.write(f"file '{_escaped}'\n")

            concat_result = subprocess.run(
                _dvr_build_hls_concat_cmd(concat_list_path, final_path),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            _ok = (
                concat_result.returncode == 0
                and os.path.exists(final_path)
                and os.path.getsize(final_path) > 0
            )
            _fallback_used = False
            # MP4-intermediate fallback: some MPEG-TS streams (parameter set
            # changes mid-stream, weird PMT updates, audio discontinuities)
            # fail to mux directly into Matroska but go through an MP4
            # container cleanly, which can then be remuxed losslessly to
            # MKV.  Try this before declaring the recording lost.
            if not _ok:
                logger.warning(
                    f"DVR recording {recording_id}: direct HLS\u2192MKV concat failed "
                    f"(rc={concat_result.returncode}); attempting MP4-intermediate "
                    f"fallback. stderr: {(concat_result.stderr or '')[:300]}"
                )
                try:
                    if os.path.exists(final_path) and os.path.getsize(final_path) == 0:
                        os.remove(final_path)
                except OSError:
                    pass
                _intermediate_mp4 = os.path.join(
                    hls_dir, f".dvr_{recording_id}_intermediate.mp4"
                )
                try:
                    if os.path.exists(_intermediate_mp4):
                        os.remove(_intermediate_mp4)
                except OSError:
                    pass
                _mp4_concat = subprocess.run(
                    _dvr_build_hls_concat_cmd(
                        concat_list_path,
                        _intermediate_mp4,
                        extra_args=["-bsf:a", "aac_adtstoasc"],
                    ),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                if (
                    _mp4_concat.returncode == 0
                    and os.path.exists(_intermediate_mp4)
                    and os.path.getsize(_intermediate_mp4) > 0
                ):
                    _mp4_to_mkv = subprocess.run(
                        [
                            "ffmpeg", "-y",
                            "-err_detect", "ignore_err",
                            "-i", _intermediate_mp4,
                            "-c", "copy",
                            final_path,
                        ],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    )
                    if (
                        _mp4_to_mkv.returncode == 0
                        and os.path.exists(final_path)
                        and os.path.getsize(final_path) > 0
                    ):
                        _ok = True
                        _fallback_used = True
                    else:
                        logger.error(
                            f"DVR recording {recording_id}: MP4\u2192MKV remux step "
                            f"failed (rc={_mp4_to_mkv.returncode}). stderr: "
                            f"{(_mp4_to_mkv.stderr or '')[:300]}"
                        )
                else:
                    logger.error(
                        f"DVR recording {recording_id}: HLS\u2192MP4 concat fallback "
                        f"failed (rc={_mp4_concat.returncode}). stderr: "
                        f"{(_mp4_concat.stderr or '')[:300]}"
                    )
                try:
                    if os.path.exists(_intermediate_mp4):
                        os.remove(_intermediate_mp4)
                except OSError:
                    pass

            if _ok:
                remux_success = True
                if _fallback_used:
                    logger.info(
                        f"DVR recording {recording_id}: HLS\u2192MP4\u2192MKV fallback "
                        f"concat succeeded \u2014 {len(segments)} segments \u2192 "
                        f"{os.path.basename(final_path)} "
                        f"({os.path.getsize(final_path):,} bytes)"
                    )
                else:
                    logger.info(
                        f"DVR recording {recording_id}: HLS\u2192MKV concat succeeded \u2014 "
                        f"{len(segments)} segments \u2192 {os.path.basename(final_path)} "
                        f"({os.path.getsize(final_path):,} bytes)"
                    )
                # Update DB so *new* client requests go to /file/ (the final MKV)
                # rather than the soon-to-be-removed /hls/ endpoint.  Important:
                # we do NOT clear _hls_dir here, active viewers still in the
                # 20s heartbeat window need it to keep fetching .ts segments
                # during the viewer-wait grace period below.  _hls_dir is
                # cleared only after the directory is actually removed.
                try:
                    _pre_rmtree_rec = Recording.objects.filter(id=recording_id).first()
                    if _pre_rmtree_rec:
                        _pre_rmtree_cp = _pre_rmtree_rec.custom_properties or {}
                        _pre_rmtree_cp["file_url"] = f"/api/channels/recordings/{recording_id}/file/"
                        _pre_rmtree_cp["output_file_url"] = _pre_rmtree_cp["file_url"]
                        _pre_rmtree_rec.custom_properties = _pre_rmtree_cp
                        _pre_rmtree_rec.save(update_fields=["custom_properties"])
                except Exception as _pre_e:
                    logger.warning(f"DVR recording {recording_id}: pre-rmtree DB update failed: {_pre_e}")
                # Wait for active HLS viewers to finish downloading segments
                # before deleting the directory.  The hls endpoint refreshes
                # _hls_viewer_key on every .ts request with a 20s TTL, so the
                # key expiring naturally means no segment was fetched in the
                # last 20 seconds (client has stopped).  We loop until the key
                # is gone with a 4-hour hard safety cap in case Redis gets stuck.
                _viewer_wait_start = time.time()
                _safety_timeout = 14400  # 4 hours absolute maximum
                try:
                    from core.utils import RedisClient as _RC
                    _rv = _RC.get_client(max_retries=1, retry_interval=0)
                    if _rv and _rv.exists(_hls_viewer_key):
                        logger.info(
                            f"DVR recording {recording_id}: active HLS viewer detected, "
                            f"deferring HLS directory cleanup until client disconnects"
                        )
                        while _rv.exists(_hls_viewer_key):
                            if time.time() - _viewer_wait_start > _safety_timeout:
                                logger.warning(
                                    f"DVR recording {recording_id}: viewer wait safety timeout "
                                    f"({_safety_timeout}s) reached, proceeding with HLS directory cleanup"
                                )
                                break
                            time.sleep(2)
                        logger.info(
                            f"DVR recording {recording_id}: viewer wait complete after "
                            f"{time.time() - _viewer_wait_start:.1f}s"
                        )
                except Exception as _ve:
                    logger.debug(f"DVR recording {recording_id}: viewer wait check failed: {_ve}")
                try:
                    shutil.rmtree(hls_dir)
                    logger.debug(f"Cleaned up HLS directory: {hls_dir}")
                except Exception as _e:
                    logger.warning(f"Failed to remove HLS directory {hls_dir}: {_e}")
                # Now that the HLS dir is gone, clear _hls_dir from custom_properties
                # so the hls endpoint will redirect (.m3u8) or 404 (.ts) cleanly.
                try:
                    _post_rmtree_rec = Recording.objects.filter(id=recording_id).first()
                    if _post_rmtree_rec:
                        _post_rmtree_cp = _post_rmtree_rec.custom_properties or {}
                        if "_hls_dir" in _post_rmtree_cp:
                            _post_rmtree_cp.pop("_hls_dir", None)
                            _post_rmtree_rec.custom_properties = _post_rmtree_cp
                            _post_rmtree_rec.save(update_fields=["custom_properties"])
                except Exception as _post_e:
                    logger.warning(f"DVR recording {recording_id}: post-rmtree DB update failed: {_post_e}")
            else:
                logger.error(
                    f"DVR recording {recording_id}: all HLS\u2192MKV concat attempts "
                    f"failed (direct rc={concat_result.returncode}, MP4 fallback also "
                    f"failed). Keeping HLS segments for recovery. stderr: "
                    f"{(concat_result.stderr or '')[:500]}"
                )
        except Exception as _ce:
            logger.error(f"DVR recording {recording_id}: concat exception: {_ce}")
        finally:
            try:
                os.remove(concat_list_path)
            except OSError:
                pass
    else:
        logger.warning(f"DVR recording {recording_id}: no HLS segments found. Nothing to concat")

    # Persist final metadata to Recording (status, ended_at, and stream stats if available)
    try:
        if recording_obj is None:
            recording_obj = Recording.objects.get(id=recording_id)

        # Re-read from DB to get the latest status (stop endpoint may have set it)
        recording_obj.refresh_from_db()
        cp = recording_obj.custom_properties or {}
        cp["ended_at"] = str(datetime.now())

        # Restore file_url to the permanent MKV endpoint now that recording has ended.
        # During recording it pointed to /hls/index.m3u8; clients should use /file/ hereafter.
        cp["file_url"] = f"/api/channels/recordings/{recording_id}/file/"
        cp["output_file_url"] = cp["file_url"]

        # Final status priority: stopped > completed > interrupted.
        # "stopped" is set by the stop endpoint before stream teardown, so
        # refresh_from_db() above guarantees it is visible here.
        db_status_now = cp.get("status", "")
        if db_status_now == "stopped":
            # Deliberate user stop — preserve; do not overwrite with "completed".
            cp.pop("interrupted_reason", None)
        elif not interrupted:
            cp["status"] = "completed"
            cp.pop("interrupted_reason", None)
        else:
            cp["status"] = "interrupted"
            if interrupted_reason:
                cp["interrupted_reason"] = interrupted_reason
        cp["bytes_written"] = bytes_written
        cp["remux_success"] = remux_success

        # Try to get stream stats from TS proxy Redis metadata
        try:
            from core.utils import RedisClient
            from apps.proxy.live_proxy.redis_keys import RedisKeys
            from apps.proxy.live_proxy.constants import ChannelMetadataField

            r = RedisClient.get_client()
            if r is not None:
                metadata_key = RedisKeys.channel_metadata(str(channel.uuid))
                md = r.hgetall(metadata_key)
                if md:
                    def _d(bkey, cast=str):
                        v = md.get(bkey)
                        try:
                            if v is None:
                                return None
                            s = v
                            return cast(s) if cast is not str else s
                        except Exception:
                            return None

                    stream_info = {}
                    # Video fields
                    for key, caster in [
                        (ChannelMetadataField.VIDEO_CODEC, str),
                        (ChannelMetadataField.RESOLUTION, str),
                        (ChannelMetadataField.WIDTH, float),
                        (ChannelMetadataField.HEIGHT, float),
                        (ChannelMetadataField.SOURCE_FPS, float),
                        (ChannelMetadataField.PIXEL_FORMAT, str),
                        (ChannelMetadataField.VIDEO_BITRATE, float),
                    ]:
                        val = _d(key, caster)
                        if val is not None:
                            stream_info[key] = val

                    # Audio fields
                    for key, caster in [
                        (ChannelMetadataField.AUDIO_CODEC, str),
                        (ChannelMetadataField.SAMPLE_RATE, float),
                        (ChannelMetadataField.AUDIO_CHANNELS, str),
                        (ChannelMetadataField.AUDIO_BITRATE, float),
                    ]:
                        val = _d(key, caster)
                        if val is not None:
                            stream_info[key] = val

                    if stream_info:
                        cp["stream_info"] = stream_info
        except Exception as e:
            logger.debug(f"Unable to capture stream stats for recording: {e}")

        # Removed: local thumbnail generation. We rely on EPG/VOD/TMDB/OMDb/keyless providers only.

        # Final cancellation guard: destroy() may have deleted the record while
        # remuxing.  If it's gone now, skip saving "interrupted" status and
        # skip the notification — destroy() already sent recording_cancelled.
        if not Recording.objects.filter(id=recording_id).exists():
            logger.info(
                f"Recording {recording_id} was deleted during post-processing — skipping final save."
            )
            return

        def _save_final_metadata():
            recording_obj.custom_properties = cp
            recording_obj.save(update_fields=["custom_properties"])

        _db_retry(
            _save_final_metadata,
            max_retries=_dvr_db_max_retries,
            base_interval=_dvr_db_retry_interval,
            label=f"DVR recording {recording_id}: metadata save",
        )

        # Notify frontends so the UI refreshes immediately (e.g. "Stopped" → "Completed")
        try:
            async_to_sync(channel_layer.group_send)(
                "updates",
                {
                    "type": "update",
                    "data": {"success": True, "type": "recording_ended", "channel": channel.name},
                },
            )
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"Unable to finalize Recording metadata: {e}")

    # Optionally run comskip post-process
    try:
        from core.models import CoreSettings
        if CoreSettings.get_dvr_comskip_enabled():
            comskip_process_recording.delay(recording_id)
    except Exception:
        pass

    # Release the per-recording active lock so a follow-up dispatch (e.g.
    # manual re-record) does not have to wait for TTL expiry.
    if _active_lock_redis is not None:
        try:
            _active_lock_redis.delete(_active_lock_key)
        except Exception:
            pass


@shared_task
def recover_recordings_on_startup():
    """
    On service startup, reschedule or resume recordings to handle server restarts.
    - For recordings whose window includes 'now': mark interrupted and start a new recording for the remainder.
    - For future recordings: ensure a task is scheduled at start_time.
    Uses a Redis lock to ensure only one worker runs this recovery.
    """
    try:
        from django.utils import timezone
        from .models import Recording
        from core.utils import RedisClient
        from .signals import schedule_recording_task, revoke_task

        redis = RedisClient.get_client()
        if redis is None:
            # Fail closed: without Redis we cannot guarantee single-execution
            # across workers, and running unguarded has been shown to start
            # duplicate ffmpeg processes against the same HLS output dir.
            logger.warning(
                "recover_recordings_on_startup: Redis unavailable, "
                "skipping recovery to avoid duplicate recording dispatch."
            )
            return "Redis unavailable"

        lock_key = "dvr:recover_lock"
        # Set lock with 10-minute TTL; must be long enough for Phase 2
        # ffmpeg remux operations on large files.
        if not redis.set(lock_key, "1", ex=600, nx=True):
            return "Recovery already in progress"

        now = timezone.now()

        # Resume in-window recordings.  DB queries and saves use _db_retry
        # to tolerate transient connection errors common during startup.
        active = _db_retry(
            lambda: list(Recording.objects.filter(
                start_time__lte=now, end_time__gt=now
            )),
            label="DVR recovery: fetching active recordings",
        )
        for rec in active:
            try:
                cp = rec.custom_properties or {}
                current_status = cp.get("status", "")

                # Skip recordings that are already in a terminal state.
                # "completed" / "stopped" — user stopped or it finished normally; do NOT
                # overwrite the status and re-schedule (that would cause the
                # Interrupted → In-Progress → Previously-Recorded ghost cycle).
                # NOTE: "recording" is NOT skipped — this function runs on
                # worker_ready, meaning all previous workers are dead.  A
                # recording stuck in "recording" status is from a crashed
                # worker and must be recovered.
                if current_status in ("completed", "stopped"):
                    logger.info(
                        f"recover_recordings_on_startup: skipping recording {rec.id} "
                        f"(status={current_status!r}, already in terminal/active state)."
                    )
                    continue

                # If a live worker still holds the per-recording active lock,
                # skip recovery, that worker is currently writing to the HLS
                # output dir and re-dispatching `run_recording` would spawn a
                # second ffmpeg racing on the same files. The lock auto-expires
                # within ~45s if the worker died, so this only blocks recovery
                # while the recording is genuinely live.
                try:
                    if redis.exists(f"dvr:recording-active:{rec.id}"):
                        logger.info(
                            f"recover_recordings_on_startup: skipping recording {rec.id} "
                            f"(active-recording lock held by live worker)."
                        )
                        continue
                except Exception:
                    pass

                # Mark interrupted due to restart; will flip to 'recording' when task starts
                cp["status"] = "interrupted"
                cp["interrupted_reason"] = "server_restarted"

                # Preserve the pre-restart .ts segment path so run_recording
                # can concatenate it with the resumed segment later.
                hls_dir_path = cp.get("_hls_dir")
                if hls_dir_path and os.path.isdir(hls_dir_path):
                    existing_segs = [f for f in os.listdir(hls_dir_path) if f.endswith(".ts")]
                    logger.info(
                        f"recover_recordings_on_startup: recording {rec.id} — "
                        f"HLS dir has {len(existing_segs)} existing segment(s), will resume"
                    )

                rec.custom_properties = cp
                _db_retry(
                    lambda r=rec: r.save(update_fields=["custom_properties"]),
                    label=f"DVR recovery: recording {rec.id} status update",
                )

                # Revoke the old PeriodicTask so Celery Beat doesn't also
                # fire run_recording for this recording (would be a duplicate).
                old_task_id = rec.task_id
                if old_task_id:
                    try:
                        revoke_task(old_task_id)
                    except Exception:
                        pass

                # Start recording for remaining window.  Use a deterministic
                # task_id so duplicate dispatches (e.g. from a second recovery
                # attempt) are deduplicated by Celery/Redis.
                recovery_task_id = f"dvr-recover-{rec.id}"
                run_recording.apply_async(
                    args=[rec.id, rec.channel_id, str(now), str(rec.end_time)],
                    eta=now,
                    task_id=recovery_task_id,
                )
            except Exception as e:
                logger.warning(f"Failed to resume recording {rec.id}: {e}")

        # Finalize expired recordings that were active when the server crashed
        # but whose end_time has now passed.  Remux the partial .ts and mark
        # as interrupted so the user can watch whatever was captured.
        expired = _db_retry(
            lambda: list(Recording.objects.filter(
                end_time__lte=now,
                custom_properties__status="recording",
            )),
            label="DVR recovery: fetching expired recordings",
        )
        for rec in expired:
            try:
                cp = rec.custom_properties or {}
                hls_dir_path = cp.get("_hls_dir")
                mkv_path = cp.get("file_path")

                if hls_dir_path and os.path.isdir(hls_dir_path) and mkv_path:
                    # Parse m3u8 for ordered segment list; fall back to sorted filenames
                    _m3u8 = os.path.join(hls_dir_path, "index.m3u8")
                    _segs = []
                    if os.path.exists(_m3u8):
                        try:
                            with open(_m3u8) as _f:
                                for _l in _f:
                                    _l = _l.strip()
                                    if _l and not _l.startswith('#'):
                                        _sp = os.path.join(hls_dir_path, _l) if not os.path.isabs(_l) else _l
                                        if os.path.exists(_sp):
                                            _segs.append(_sp)
                        except Exception:
                            pass
                    if not _segs:
                        _segs = sorted(
                            os.path.join(hls_dir_path, f)
                            for f in os.listdir(hls_dir_path)
                            if f.startswith("seg_") and f.endswith(".ts")
                        )

                    if _segs:
                        logger.info(
                            f"recover_recordings_on_startup: recording {rec.id} expired "
                            f"during downtime, concat {len(_segs)} HLS segment(s) \u2192 MKV"
                        )
                        os.makedirs(os.path.dirname(mkv_path), exist_ok=True)
                        _concat_txt = os.path.join(hls_dir_path, "concat.txt")
                        try:
                            with open(_concat_txt, "w") as _cl:
                                for _s in _segs:
                                    _escaped = _s.replace("'", "'\\''")
                                    _cl.write(f"file '{_escaped}'\n")
                            _res = subprocess.run(
                                _dvr_build_hls_concat_cmd(_concat_txt, mkv_path),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            )
                            if _res.returncode == 0 and os.path.exists(mkv_path) and os.path.getsize(mkv_path) > 0:
                                cp["status"] = "interrupted"
                                cp["interrupted_reason"] = "server_restarted_after_end"
                                cp["remux_success"] = True
                                try:
                                    shutil.rmtree(hls_dir_path)
                                except OSError:
                                    pass
                                logger.info(
                                    f"recover_recordings_on_startup: recording {rec.id} HLS\u2192MKV concat succeeded"
                                )
                            else:
                                cp["status"] = "interrupted"
                                cp["interrupted_reason"] = "server_restarted_after_end"
                                cp["remux_success"] = False
                                logger.warning(
                                    f"recover_recordings_on_startup: recording {rec.id} concat failed, keeping HLS dir"
                                )
                        except Exception as _ce:
                            cp["status"] = "interrupted"
                            cp["interrupted_reason"] = "server_restarted_after_end"
                            cp["remux_success"] = False
                            logger.warning(
                                f"recover_recordings_on_startup: recording {rec.id} concat error: {_ce}"
                            )
                        finally:
                            try:
                                os.remove(_concat_txt)
                            except OSError:
                                pass
                    else:
                        cp["status"] = "interrupted"
                        cp["interrupted_reason"] = "server_restarted_after_end"
                        cp["remux_success"] = False
                else:
                    cp["status"] = "interrupted"
                    cp["interrupted_reason"] = "server_restarted_after_end"
                    cp["remux_success"] = False

                rec.custom_properties = cp
                _db_retry(
                    lambda r=rec: r.save(update_fields=["custom_properties"]),
                    label=f"DVR recovery: recording {rec.id} expired status update",
                )
            except Exception as e:
                logger.warning(f"Failed to finalize expired recording {rec.id}: {e}")

        # Ensure future recordings are scheduled.
        # With ClockedSchedule, PeriodicTasks survive restarts in the DB.
        # Only recreate if the PeriodicTask is missing (safety net).
        from django_celery_beat.models import PeriodicTask as _PT
        from apps.channels.signals import _dvr_task_name

        upcoming = _db_retry(
            lambda: list(Recording.objects.filter(
                start_time__gt=now, end_time__gt=now
            )),
            label="DVR recovery: fetching upcoming recordings",
        )

        # Batch-fetch existing PeriodicTask names to avoid N+1 queries
        task_names = {_dvr_task_name(r.id) for r in upcoming}
        existing_tasks = set(_db_retry(
            lambda: list(_PT.objects.filter(name__in=task_names).values_list("name", flat=True)),
            label="DVR recovery: fetching existing periodic tasks",
        )) if task_names else set()

        for rec in upcoming:
            try:
                task_name = _dvr_task_name(rec.id)
                if task_name in existing_tasks:
                    if rec.task_id != task_name:
                        rec.task_id = task_name
                        _db_retry(
                            lambda r=rec: r.save(update_fields=["task_id"]),
                            label=f"DVR recovery: recording {rec.id} task_id update",
                        )
                    continue
                # PeriodicTask missing - recreate it
                task_id = schedule_recording_task(rec)
                if task_id:
                    rec.task_id = task_id
                    _db_retry(
                        lambda r=rec: r.save(update_fields=["task_id"]),
                        label=f"DVR recovery: recording {rec.id} task_id update",
                    )
            except Exception as e:
                logger.warning(f"Failed to schedule recording {rec.id}: {e}")

        # Release the lock early so a subsequent restart can recover
        # immediately.  The 10-minute TTL is only a safety net in case
        # recovery itself crashes before reaching this point.
        if redis:
            redis.delete(lock_key)

        return "Recovery complete"
    except Exception as e:
        logger.error(f"Error during DVR recovery: {e}")
        return f"Error: {e}"

@shared_task
def comskip_process_recording(recording_id: int):
    """Run comskip on the MKV to remove commercials and replace the file in place.
    Safe to call even if comskip is not installed; stores status in custom_properties.comskip.
    """
    import shutil
    from django.db import DatabaseError
    from .models import Recording
    # Helper to broadcast status over websocket
    def _ws(status: str, extra: dict | None = None):
        try:
            from core.utils import send_websocket_update
            payload = {"success": True, "type": "comskip_status", "status": status, "recording_id": recording_id}
            if extra:
                payload.update(extra)
            send_websocket_update('updates', 'update', payload)
        except Exception:
            pass

    try:
        rec = Recording.objects.get(id=recording_id)
    except Recording.DoesNotExist:
        return "not_found"

    cp = rec.custom_properties.copy() if isinstance(rec.custom_properties, dict) else {}

    def _persist_custom_properties():
        """Persist updated custom_properties without raising if the row disappeared."""
        try:
            updated = Recording.objects.filter(pk=recording_id).update(custom_properties=cp)
            if not updated:
                logger.warning(
                    "Recording %s vanished before comskip status could be saved",
                    recording_id,
                )
                return False
        except DatabaseError as db_err:
            logger.warning(
                "Failed to persist comskip status for recording %s: %s",
                recording_id,
                db_err,
            )
            return False
        except Exception as unexpected:
            logger.warning(
                "Unexpected error while saving comskip status for recording %s: %s",
                recording_id,
                unexpected,
            )
            return False
        return True
    file_path = (cp or {}).get("file_path")
    if not file_path or not os.path.exists(file_path):
        return "no_file"

    if isinstance(cp.get("comskip"), dict) and cp["comskip"].get("status") == "completed":
        return "already_processed"

    comskip_bin = shutil.which("comskip")
    if not comskip_bin:
        cp["comskip"] = {"status": "skipped", "reason": "comskip_not_installed"}
        _persist_custom_properties()
        _ws('skipped', {"reason": "comskip_not_installed"})
        return "comskip_missing"

    base, _ = os.path.splitext(file_path)
    edl_path = f"{base}.edl"

    # Notify start
    _ws('started', {"title": (cp.get('program') or {}).get('title') or os.path.basename(file_path)})

    try:
        comskip_mode = CoreSettings.get_dvr_comskip_mode()
        hw_accel = CoreSettings.get_dvr_comskip_hw_accel()
        cmd = [comskip_bin, "--output", os.path.dirname(file_path)]
        if hw_accel != "none":
            cmd.insert(1, f"--{hw_accel}")
        # Prefer user-specified INI, fall back to known defaults
        ini_candidates = []
        try:
            custom_ini = CoreSettings.get_dvr_comskip_custom_path()
            if custom_ini:
                ini_candidates.append(custom_ini)
        except Exception as ini_err:
            logger.debug(f"Unable to load custom comskip.ini path: {ini_err}")
        ini_candidates.extend(["/etc/comskip/comskip.ini", "/app/docker/comskip.ini"])
        selected_ini = None
        for ini_path in ini_candidates:
            if ini_path and os.path.exists(ini_path):
                selected_ini = ini_path
                cmd.extend([f"--ini={ini_path}"])
                break
        cmd.append(file_path)
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # comskip exit codes: 0 = commercials found, 1 = no commercials detected.
        # Negative codes indicate killed by signal; anything else is a real error.
        if result.returncode == 1:
            # No commercials detected — not an error.
            cp["comskip"] = {"status": "completed", "skipped": True}
            if selected_ini:
                cp["comskip"]["ini_path"] = selected_ini
            _persist_custom_properties()
            _ws('skipped', {"reason": "no_commercials_detected"})
            return "no_commercials"
        elif result.returncode != 0:
            stderr_tail = (result.stderr or "").strip().splitlines()
            stderr_tail = stderr_tail[-5:] if stderr_tail else []
            detail = {
                "status": "error",
                "reason": "comskip_failed",
                "returncode": result.returncode,
            }
            if result.returncode < 0:
                try:
                    detail["signal"] = signal.Signals(-result.returncode).name
                except Exception:
                    detail["signal"] = f"signal_{-result.returncode}"
            if stderr_tail:
                detail["stderr"] = "\n".join(stderr_tail)
            if selected_ini:
                detail["ini_path"] = selected_ini
            cp["comskip"] = detail
            _persist_custom_properties()
            _ws('error', {"reason": "comskip_failed", "returncode": result.returncode})
            return "comskip_failed"
    except Exception as e:
        cp["comskip"] = {"status": "error", "reason": f"comskip_failed: {e}"}
        _persist_custom_properties()
        _ws('error', {"reason": str(e)})
        return "comskip_failed"

    if not os.path.exists(edl_path):
        cp["comskip"] = {"status": "error", "reason": "edl_not_found"}
        _persist_custom_properties()
        _ws('error', {"reason": "edl_not_found"})
        return "no_edl"

    # Duration via ffprobe
    def _ffprobe_duration(path):
        try:
            p = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(p.stdout.strip())
        except Exception:
            return None

    duration = _ffprobe_duration(file_path)
    if duration is None:
        cp["comskip"] = {"status": "error", "reason": "duration_unknown"}
        _persist_custom_properties()
        _ws('error', {"reason": "duration_unknown"})
        return "no_duration"

    commercials = []
    try:
        with open(edl_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        s = float(parts[0]); e = float(parts[1])
                        commercials.append((max(0.0, s), min(duration, e)))
                    except Exception:
                        pass
    except Exception:
        pass

    commercials.sort()
    keep = []
    cur = 0.0
    for s, e in commercials:
        if s > cur:
            keep.append((cur, max(cur, s)))
        cur = max(cur, e)
    if cur < duration:
        keep.append((cur, duration))

    if not commercials or sum((e - s) for s, e in commercials) <= 0.5:
        cp["comskip"] = {
            "status": "completed",
            "skipped": True,
            "edl": os.path.basename(edl_path),
        }
        if selected_ini:
            cp["comskip"]["ini_path"] = selected_ini
        _persist_custom_properties()
        _ws('skipped', {"reason": "no_commercials", "commercials": 0})
        return "no_commercials"

    if comskip_mode == "mark":
        cp["comskip"] = {
            "status": "completed",
            "mode": "mark",
            "edl": os.path.basename(edl_path),
            "commercials": len(commercials),
        }
        if selected_ini:
            cp["comskip"]["ini_path"] = selected_ini
        _persist_custom_properties()
        _ws('completed', {"commercials": len(commercials), "mode": "mark"})
        return "ok"

    workdir = os.path.dirname(file_path)
    parts = []
    try:
        for idx, (s, e) in enumerate(keep):
            seg = os.path.join(workdir, f"segment_{idx:03d}.mkv")
            dur = max(0.0, e - s)
            if dur <= 0.01:
                continue
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{s:.3f}", "-i", file_path, "-t", f"{dur:.3f}",
                "-c", "copy", "-avoid_negative_ts", "1", seg
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            parts.append(seg)

        if not parts:
            raise RuntimeError("no_parts")

        list_path = os.path.join(workdir, "concat_list.txt")
        with open(list_path, "w") as lf:
            for pth in parts:
                escaped = pth.replace("'", "'\\''")
                lf.write(f"file '{escaped}'\n")

        output_path = os.path.join(workdir, f"{os.path.splitext(os.path.basename(file_path))[0]}.cut.mkv")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        try:
            os.replace(output_path, file_path)
        except Exception:
            shutil.copy(output_path, file_path)

        try:
            os.remove(list_path)
        except Exception:
            pass
        for pth in parts:
            try: os.remove(pth)
            except Exception: pass
        try:
            os.remove(edl_path)
        except Exception:
            pass

        cp["comskip"] = {
            "status": "completed",
            "edl": os.path.basename(edl_path),
            "segments_kept": len(parts),
            "commercials": len(commercials),
        }
        if selected_ini:
            cp["comskip"]["ini_path"] = selected_ini
        _persist_custom_properties()
        _ws('completed', {"commercials": len(commercials), "segments_kept": len(parts)})
        return "ok"
    except Exception as e:
        cp["comskip"] = {"status": "error", "reason": str(e)}
        _persist_custom_properties()
        _ws('error', {"reason": str(e)})
        return f"error:{e}"
def _resolve_poster_for_program(channel_name, program, channel_logo_id=None):
    """Resolve poster URL and/or Logo id for a recording program.

    Callers should enrich the program dict via _match_epg_program_by_timeslot
    before invoking this function so that EPG data is already available.

    Pipeline: EPG images → VOD logo → TMDB/OMDb → TVMaze/iTunes →
    direct program fields → Logo table → Logo creation → channel logo.
    Returns (poster_logo_id, poster_url) where either may be None.
    """
    poster_logo_id = None
    poster_url = None
    epg_props = None

    _title = ((program.get("title") if isinstance(program, dict) else None) or "").strip() or None

    # Guard: if the "title" is really just the channel name (common when EPG
    # has no real program data), don't use it for external API searches —
    # those queries produce false-positive artwork from unrelated shows.
    _title_is_channel_name = False
    if _title and channel_name:
        def _norm_channel(s):
            return s.lower().replace("*", "").replace("-", " ").strip()
        _title_is_channel_name = _norm_channel(_title) == _norm_channel(channel_name)

    # Stage 1: EPG Program images/icon (with URL validation)
    try:
        from apps.epg.models import ProgramData
        prog_id = program.get("id") if isinstance(program, dict) else None
        if prog_id:
            epg_program = ProgramData.objects.filter(id=prog_id).only("custom_properties").first()
            if epg_program and epg_program.custom_properties:
                epg_props = epg_program.custom_properties or {}
                poster_url = _pick_best_image_from_epg_props(epg_props)
                if poster_url and not _validate_url(poster_url):
                    poster_url = None
                if not poster_url:
                    icon = epg_props.get("icon")
                    if isinstance(icon, str) and icon and _validate_url(icon):
                        poster_url = icon
    except Exception:
        pass

    # Stage 2: VOD logo fallback by title
    if not poster_url and not poster_logo_id and _title and not _title_is_channel_name:
        try:
            from apps.vod.models import Movie, Series
            vod_logo = None
            movie = Movie.objects.filter(name__iexact=_title).select_related("logo").first()
            if movie and movie.logo:
                vod_logo = movie.logo
            if not vod_logo:
                series = Series.objects.filter(name__iexact=_title).select_related("logo").first()
                if series and series.logo:
                    vod_logo = series.logo
            if vod_logo:
                poster_logo_id = vod_logo.id
        except Exception:
            pass

    # Stage 3: TMDB/OMDb (keyed APIs)
    if not poster_url and not poster_logo_id and _title and not _title_is_channel_name:
        try:
            tmdb_key = os.environ.get('TMDB_API_KEY')
            omdb_key = os.environ.get('OMDB_API_KEY')
            title = _title
            year = None
            imdb_id = None

            # Derive year and imdb_id from cached EPG data
            if epg_props:
                d = epg_props.get('date')
                if d and len(str(d)) >= 4:
                    year = str(d)[:4]
                imdb_id = epg_props.get('imdb.com_id')

            # TMDB: by IMDb ID
            if not poster_url and tmdb_key and imdb_id:
                try:
                    url = f"https://api.themoviedb.org/3/find/{quote(imdb_id)}?api_key={tmdb_key}&external_source=imdb_id"
                    resp = requests.get(url, timeout=5)
                    if resp.ok:
                        data = resp.json() or {}
                        picks = []
                        for k in ('movie_results', 'tv_results', 'tv_episode_results', 'tv_season_results'):
                            picks.extend(data.get(k) or [])
                        for item in picks:
                            if item.get('poster_path'):
                                poster_url = f"https://image.tmdb.org/t/p/w780{item['poster_path']}"
                                break
                except Exception:
                    pass

            # TMDB: by title (and year if available)
            if not poster_url and tmdb_key and title:
                try:
                    q = quote(title)
                    extra = f"&year={year}" if year else ""
                    url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_key}&query={q}{extra}"
                    resp = requests.get(url, timeout=5)
                    if resp.ok:
                        data = resp.json() or {}
                        results = data.get('results') or []
                        results.sort(key=lambda x: float(x.get('popularity') or 0), reverse=True)
                        for item in results:
                            if item.get('poster_path'):
                                poster_url = f"https://image.tmdb.org/t/p/w780{item['poster_path']}"
                                break
                except Exception:
                    pass

            # OMDb fallback
            if not poster_url and omdb_key:
                try:
                    if imdb_id:
                        url = f"https://www.omdbapi.com/?apikey={omdb_key}&i={quote(imdb_id)}"
                    elif title:
                        yy = f"&y={year}" if year else ""
                        url = f"https://www.omdbapi.com/?apikey={omdb_key}&t={quote(title)}{yy}"
                    else:
                        url = None
                    if url:
                        resp = requests.get(url, timeout=5)
                        if resp.ok:
                            data = resp.json() or {}
                            p = data.get('Poster')
                            if p and p != 'N/A':
                                poster_url = p
                except Exception:
                    pass
        except Exception:
            pass

    # Stage 4: Keyless providers (TVMaze & iTunes)
    if not poster_url and not poster_logo_id and _title and not _title_is_channel_name:
        try:
            title = _title
            # TVMaze
            try:
                url = f"https://api.tvmaze.com/singlesearch/shows?q={quote(title)}"
                resp = requests.get(url, timeout=5)
                if resp.ok:
                    data = resp.json() or {}
                    img = (data.get('image') or {})
                    p = img.get('original') or img.get('medium')
                    if p:
                        poster_url = p
            except Exception:
                pass
            # iTunes
            if not poster_url:
                try:
                    for media in ('movie', 'tvShow'):
                        url = f"https://itunes.apple.com/search?term={quote(title)}&media={media}&limit=1"
                        resp = requests.get(url, timeout=5)
                        if resp.ok:
                            data = resp.json() or {}
                            results = data.get('results') or []
                            if results:
                                art = results[0].get('artworkUrl100')
                                if art:
                                    poster_url = art.replace('100x100', '600x600')
                                    break
                except Exception:
                    pass
        except Exception:
            pass

    # Stage 5: Direct fields on program object (with URL validation)
    if not poster_url and not poster_logo_id and isinstance(program, dict):
        for key in ("poster", "cover", "cover_big", "image", "icon"):
            val = program.get(key)
            if isinstance(val, dict):
                candidate = val.get("url")
                if candidate and _validate_url(candidate):
                    poster_url = candidate
                    break
            elif isinstance(val, str) and val and _validate_url(val):
                poster_url = val
                break

    # Stage 6: Search existing Logo entries by program title
    if not poster_logo_id and not poster_url and _title and not _title_is_channel_name:
        try:
            from .models import Logo
            existing = Logo.objects.filter(name__iexact=_title).first()
            if existing:
                poster_logo_id = existing.id
                poster_url = existing.url
        except Exception:
            pass

    # Stage 7: Persist to Logo table if URL available
    if not poster_logo_id and poster_url and len(poster_url) <= 1000:
        try:
            from .models import Logo
            logo, _ = Logo.objects.get_or_create(url=poster_url, defaults={"name": _title or channel_name})
            poster_logo_id = logo.id
        except Exception:
            pass

    # Stage 8: Fall back to channel logo
    if not poster_logo_id and not poster_url and channel_logo_id:
        poster_logo_id = channel_logo_id

    return poster_logo_id, poster_url


@shared_task
def prefetch_recording_artwork(recording_id):
    """Prefetch poster info for a scheduled recording so the UI can show art in Upcoming."""
    try:
        from .models import Recording
        rec = Recording.objects.get(id=recording_id)
        cp = rec.custom_properties or {}

        # Bail out if the recording is already active or finished — run_recording
        # handles poster resolution itself, and saving here can race with status updates.
        current_status = cp.get("status", "")
        if current_status in ("recording", "completed", "stopped", "interrupted"):
            return "skipped: status is " + current_status

        program = cp.get("program") or {}

        # Enrich empty program dicts (manual recordings) from EPG time-slot data.
        # Persists matched title/description for display in the recording card.
        if isinstance(program, dict) and not program.get("user_edited") and not program.get("id") and not program.get("title"):
            epg_match = _match_epg_program_by_timeslot(
                rec.channel.epg_data, rec.start_time, rec.end_time,
            )
            if epg_match:
                program.update(epg_match)
                cp["program"] = program

        poster_logo_id, poster_url = _resolve_poster_for_program(
            rec.channel.name, program, channel_logo_id=rec.channel.logo_id,
        )
        updated = False
        if poster_logo_id and cp.get("poster_logo_id") != poster_logo_id:
            cp["poster_logo_id"] = poster_logo_id
            updated = True
        if poster_url and cp.get("poster_url") != poster_url:
            cp["poster_url"] = poster_url
            updated = True
        # Enrich with rating if available from ProgramData.custom_properties
        try:
            from apps.epg.models import ProgramData
            prog_id = program.get("id") if isinstance(program, dict) else None
            if prog_id:
                epg_program = ProgramData.objects.filter(id=prog_id).only("custom_properties").first()
                if epg_program and isinstance(epg_program.custom_properties, dict):
                    rating_val = epg_program.custom_properties.get("rating")
                    rating_sys = epg_program.custom_properties.get("rating_system")
                    season_val = epg_program.custom_properties.get("season")
                    episode_val = epg_program.custom_properties.get("episode")
                    onscreen = epg_program.custom_properties.get("onscreen_episode")
                    if rating_val and cp.get("rating") != rating_val:
                        cp["rating"] = rating_val
                        updated = True
                    if rating_sys and cp.get("rating_system") != rating_sys:
                        cp["rating_system"] = rating_sys
                        updated = True
                    if season_val is not None and cp.get("season") != season_val:
                        cp["season"] = season_val
                        updated = True
                    if episode_val is not None and cp.get("episode") != episode_val:
                        cp["episode"] = episode_val
                        updated = True
                    if onscreen and cp.get("onscreen_episode") != onscreen:
                        cp["onscreen_episode"] = onscreen
                        updated = True
        except Exception:
            pass

        if updated:
            # Re-read from DB to avoid overwriting status changes made by
            # the stop endpoint or run_recording's final metadata save.
            rec.refresh_from_db()
            fresh_cp = rec.custom_properties or {}
            for key in ("program", "poster_logo_id", "poster_url", "rating",
                        "rating_system", "season", "episode", "onscreen_episode"):
                if key in cp:
                    fresh_cp[key] = cp[key]
            rec.custom_properties = fresh_cp
            rec.save(update_fields=["custom_properties"])
            try:
                from core.utils import send_websocket_update
                send_websocket_update('updates', 'update', {"success": True, "type": "recording_updated", "recording_id": rec.id})
            except Exception:
                pass
        return "ok"
    except Exception as e:
        logger.debug(f"prefetch_recording_artwork failed: {e}")
        return f"error: {e}"


@shared_task(bind=True)
def bulk_create_channels_from_streams(self, stream_ids, channel_profile_ids=None, starting_channel_number=None):
    """
    Asynchronously create channels from a list of stream IDs.
    Provides progress updates via WebSocket.

    Args:
        stream_ids: List of stream IDs to create channels from
        channel_profile_ids: Optional list of channel profile IDs to assign channels to
        starting_channel_number: Optional starting channel number behavior:
            - None: Use provider channel numbers, then auto-assign from 1
            - 0: Start with lowest available number and increment by 1
            - Other number: Use as starting number for auto-assignment
    """
    from apps.channels.models import Stream, Channel, ChannelGroup, ChannelProfile, ChannelProfileMembership, Logo
    from apps.epg.models import EPGData
    from django.db import transaction
    from django.shortcuts import get_object_or_404
    from core.utils import send_websocket_update

    task_id = self.request.id
    total_streams = len(stream_ids)
    created_channels = []
    errors = []

    try:
        # Send initial progress update
        send_websocket_update('updates', 'update', {
            'type': 'bulk_channel_creation_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_streams,
            'status': 'starting',
            'message': f'Starting bulk creation of {total_streams} channels...'
        })

        # Gather current used numbers once
        used_numbers = set(Channel.objects.all().values_list("channel_number", flat=True))

        # Initialize next_number based on starting_channel_number mode
        if starting_channel_number is None:
            # Mode 1: Use provider numbers when available, auto-assign when not
            next_number = 1
        elif starting_channel_number == 0:
            # Mode 2: Start from lowest available number
            next_number = 1
        elif starting_channel_number == -1:
            # Mode 4: Start after the current highest channel number
            highest = Channel.objects.order_by('-channel_number').values_list('channel_number', flat=True).first()
            next_number = (int(highest) + 1) if highest is not None else 1
        else:
            # Mode 3: Start from specified number
            next_number = starting_channel_number

        def get_auto_number():
            nonlocal next_number
            while next_number in used_numbers:
                next_number += 1
            used_numbers.add(next_number)
            return next_number

        logos_to_create = []
        channels_to_create = []
        streams_map = []
        logo_map = []
        profile_map = []

        # Process streams in batches to avoid memory issues
        batch_size = 100
        processed = 0

        for i in range(0, total_streams, batch_size):
            batch_stream_ids = stream_ids[i:i + batch_size]
            # Fetch streams and preserve the order from batch_stream_ids
            batch_streams_dict = {stream.id: stream for stream in Stream.objects.filter(id__in=batch_stream_ids)}
            batch_streams = [batch_streams_dict[stream_id] for stream_id in batch_stream_ids if stream_id in batch_streams_dict]

            # Send progress update
            send_websocket_update('updates', 'update', {
                'type': 'bulk_channel_creation_progress',
                'task_id': task_id,
                'progress': processed,
                'total': total_streams,
                'status': 'processing',
                'message': f'Processing streams {processed + 1}-{min(processed + batch_size, total_streams)} of {total_streams}...'
            })

            for stream in batch_streams:
                try:
                    name = stream.name
                    channel_group = stream.channel_group
                    stream_custom_props = stream.custom_properties or {}

                    # Determine channel number based on starting_channel_number mode
                    channel_number = None

                    if starting_channel_number is None:
                        # Mode 1: Use provider numbers when available (from stream_chno field)
                        if stream.stream_chno is not None:
                            channel_number = stream.stream_chno

                    # For modes 2 and 3 (starting_channel_number == 0 or specific number),
                    # ignore provider numbers and use sequential assignment

                    # Get TVC guide station ID
                    tvc_guide_stationid = None
                    if "tvc-guide-stationid" in stream_custom_props:
                        tvc_guide_stationid = stream_custom_props["tvc-guide-stationid"]

                    # Check if the determined/provider number is available
                    if channel_number is not None and (
                        channel_number in used_numbers
                        or Channel.objects.filter(channel_number=channel_number).exists()
                    ):
                        # Provider number is taken, use auto-assignment
                        channel_number = get_auto_number()
                    elif channel_number is not None:
                        # Provider number is available, use it
                        used_numbers.add(channel_number)
                    else:
                        # No provider number or ignoring provider numbers, use auto-assignment
                        channel_number = get_auto_number()

                    channel_data = {
                        "channel_number": channel_number,
                        "name": name,
                        "tvc_guide_stationid": tvc_guide_stationid,
                        "tvg_id": stream.tvg_id,
                        "is_adult": stream.is_adult,
                    }

                    # Only add channel_group_id if the stream has a channel group
                    if channel_group:
                        channel_data["channel_group_id"] = channel_group.id

                    # Attempt to find existing EPGs with the same tvg-id
                    epgs = EPGData.objects.filter(tvg_id=stream.tvg_id)
                    if epgs:
                        channel_data["epg_data_id"] = epgs.first().id

                    channel = Channel(**channel_data)
                    channels_to_create.append(channel)
                    streams_map.append([stream.id])

                    # Store profile IDs for this channel
                    profile_map.append(channel_profile_ids)

                    # Handle logo - validate URL length to avoid PostgreSQL btree index errors
                    validated_logo_url = validate_logo_url(stream.logo_url) if stream.logo_url else None
                    if validated_logo_url:
                        logos_to_create.append(
                            Logo(
                                url=validated_logo_url,
                                name=stream.name or stream.tvg_id,
                            )
                        )
                        logo_map.append(validated_logo_url)
                    else:
                        logo_map.append(None)

                    processed += 1

                except Exception as e:
                    errors.append({
                        'stream_id': stream.id if 'stream' in locals() else 'unknown',
                        'error': str(e)
                    })
                    processed += 1

        # Create logos first
        if logos_to_create:
            send_websocket_update('updates', 'update', {
                'type': 'bulk_channel_creation_progress',
                'task_id': task_id,
                'progress': processed,
                'total': total_streams,
                'status': 'creating_logos',
                'message': f'Creating {len(logos_to_create)} logos...'
            })
            Logo.objects.bulk_create(logos_to_create, ignore_conflicts=True)

        # Get logo objects for association
        channel_logos = {
            logo.url: logo
            for logo in Logo.objects.filter(
                url__in=[url for url in logo_map if url is not None]
            )
        }

        # Create channels in database
        if channels_to_create:
            send_websocket_update('updates', 'update', {
                'type': 'bulk_channel_creation_progress',
                'task_id': task_id,
                'progress': processed,
                'total': total_streams,
                'status': 'creating_channels',
                'message': f'Creating {len(channels_to_create)} channels in database...'
            })

            with transaction.atomic():
                created_channels = Channel.objects.bulk_create(channels_to_create)

                # Update channels with logos and create stream associations
                update = []
                channel_stream_associations = []
                channel_profile_memberships = []

                for channel, stream_ids, logo_url, profile_ids in zip(
                    created_channels, streams_map, logo_map, profile_map
                ):
                    if logo_url:
                        channel.logo = channel_logos[logo_url]
                        update.append(channel)

                    # Create stream associations
                    for stream_id in stream_ids:
                        from apps.channels.models import ChannelStream
                        channel_stream_associations.append(
                            ChannelStream(channel=channel, stream_id=stream_id, order=0)
                        )

                    # Handle channel profile membership
                    # Semantics:
                    # - None: add to ALL profiles (backward compatible default)
                    # - Empty array []: add to NO profiles
                    # - Sentinel [0] or 0 in array: add to ALL profiles (explicit)
                    # - [1,2,...]: add to specified profile IDs only
                    if profile_ids is None:
                        # Omitted -> add to all profiles (backward compatible)
                        all_profiles = ChannelProfile.objects.all()
                        channel_profile_memberships.extend([
                            ChannelProfileMembership(
                                channel_profile=profile,
                                channel=channel,
                                enabled=True
                            )
                            for profile in all_profiles
                        ])
                    elif isinstance(profile_ids, list) and len(profile_ids) == 0:
                        # Empty array -> add to no profiles
                        pass
                    elif isinstance(profile_ids, list) and 0 in profile_ids:
                        # Sentinel 0 -> add to all profiles (explicit)
                        all_profiles = ChannelProfile.objects.all()
                        channel_profile_memberships.extend([
                            ChannelProfileMembership(
                                channel_profile=profile,
                                channel=channel,
                                enabled=True
                            )
                            for profile in all_profiles
                        ])
                    else:
                        # Specific profile IDs
                        try:
                            specific_profiles = ChannelProfile.objects.filter(id__in=profile_ids)
                            channel_profile_memberships.extend([
                                ChannelProfileMembership(
                                    channel_profile=profile,
                                    channel=channel,
                                    enabled=True
                                )
                                for profile in specific_profiles
                            ])
                        except Exception as e:
                            errors.append({
                                'channel_id': channel.id,
                                'error': f'Failed to add to profiles: {str(e)}'
                            })

                # Bulk update channels with logos
                if update:
                    Channel.objects.bulk_update(update, ["logo"])

                # Bulk create channel-stream associations
                if channel_stream_associations:
                    from apps.channels.models import ChannelStream
                    ChannelStream.objects.bulk_create(channel_stream_associations, ignore_conflicts=True)

                # Bulk create profile memberships
                if channel_profile_memberships:
                    ChannelProfileMembership.objects.bulk_create(channel_profile_memberships, ignore_conflicts=True)

        # Send completion update
        send_websocket_update('updates', 'update', {
            'type': 'bulk_channel_creation_progress',
            'task_id': task_id,
            'progress': total_streams,
            'total': total_streams,
            'status': 'completed',
            'message': f'Successfully created {len(created_channels)} channels',
            'created_count': len(created_channels),
            'error_count': len(errors),
            'errors': errors[:10]  # Send first 10 errors only
        })

        # Send general channel update notification
        send_websocket_update('updates', 'update', {
            'type': 'channels_created',
            'count': len(created_channels)
        })

        return {
            'status': 'completed',
            'created_count': len(created_channels),
            'error_count': len(errors),
            'errors': errors
        }

    except Exception as e:
        logger.error(f"Bulk channel creation failed: {e}")
        send_websocket_update('updates', 'update', {
            'type': 'bulk_channel_creation_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_streams,
            'status': 'failed',
            'message': f'Task failed: {str(e)}',
            'error': str(e)
        })
        raise


@shared_task(bind=True)
def set_channels_names_from_epg(self, channel_ids):
    """
    Celery task to set channel names from EPG data for multiple channels
    """
    from core.utils import send_websocket_update

    task_id = self.request.id
    total_channels = len(channel_ids)
    updated_count = 0
    errors = []

    try:
        logger.info(f"Starting EPG name setting task for {total_channels} channels")

        # Send initial progress
        send_websocket_update('updates', 'update', {
            'type': 'epg_name_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'running',
            'message': 'Starting EPG name setting...'
        })

        batch_size = 100
        for i in range(0, total_channels, batch_size):
            batch_ids = channel_ids[i:i + batch_size]
            batch_updates = []

            # Get channels and their EPG data
            channels = Channel.objects.filter(id__in=batch_ids).select_related('epg_data')

            for channel in channels:
                try:
                    if channel.epg_data and channel.epg_data.name:
                        if channel.name != channel.epg_data.name:
                            channel.name = channel.epg_data.name
                            batch_updates.append(channel)
                            updated_count += 1
                except Exception as e:
                    errors.append(f"Channel {channel.id}: {str(e)}")
                    logger.error(f"Error processing channel {channel.id}: {e}")

            # Bulk update the batch
            if batch_updates:
                Channel.objects.bulk_update(batch_updates, ['name'])

            # Send progress update
            progress = min(i + batch_size, total_channels)
            send_websocket_update('updates', 'update', {
                'type': 'epg_name_setting_progress',
                'task_id': task_id,
                'progress': progress,
                'total': total_channels,
                'status': 'running',
                'message': f'Updated {updated_count} channel names...',
                'updated_count': updated_count
            })

        # Send completion notification
        send_websocket_update('updates', 'update', {
            'type': 'epg_name_setting_progress',
            'task_id': task_id,
            'progress': total_channels,
            'total': total_channels,
            'status': 'completed',
            'message': f'Successfully updated {updated_count} channel names from EPG data',
            'updated_count': updated_count,
            'error_count': len(errors),
            'errors': errors
        })

        logger.info(f"EPG name setting task completed. Updated {updated_count} channels")
        return {
            'status': 'completed',
            'updated_count': updated_count,
            'error_count': len(errors),
            'errors': errors
        }

    except Exception as e:
        logger.error(f"EPG name setting task failed: {e}")
        send_websocket_update('updates', 'update', {
            'type': 'epg_name_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'failed',
            'message': f'Task failed: {str(e)}',
            'error': str(e)
        })
        raise


@shared_task(bind=True)
def set_channels_logos_from_epg(self, channel_ids=None, epg_source_id=None):
    """
    Celery task to set channel logos from EPG data.

    Accepts either an explicit channel_ids list or an epg_source_id to target
    all channels mapped to that source.
    """
    from core.utils import send_websocket_update
    from .utils import (
        EPG_LOGO_APPLY_BATCH_SIZE,
        EPG_LOGO_APPLY_MAX_ERRORS,
        apply_logos_from_epg_icon_url,
        channels_with_epg_icon_queryset,
    )

    task_id = self.request.id
    updated_count = 0
    created_logos_count = 0
    errors = []
    total_channels = 0
    batch_size = EPG_LOGO_APPLY_BATCH_SIZE

    try:
        if epg_source_id:
            channels_qs = channels_with_epg_icon_queryset(epg_source_id=epg_source_id)
            total_channels = channels_qs.count()
            logger.info(
                f"Starting EPG logo setting task for {total_channels} channels "
                f"(source {epg_source_id})"
            )

            send_websocket_update('updates', 'update', {
                'type': 'epg_logo_setting_progress',
                'task_id': task_id,
                'progress': 0,
                'total': total_channels,
                'status': 'running',
                'message': 'Starting EPG logo setting...'
            })

            processed = 0
            pending_ids = []
            for channel_id in channels_qs.order_by('id').values_list('id', flat=True).iterator(
                chunk_size=batch_size,
            ):
                pending_ids.append(channel_id)
                if len(pending_ids) < batch_size:
                    continue

                batch = Channel.objects.filter(
                    id__in=pending_ids,
                ).select_related('epg_data', 'logo')
                batch_stats = apply_logos_from_epg_icon_url(batch)
                updated_count += batch_stats['updated_count']
                created_logos_count += batch_stats['created_logos_count']
                remaining = EPG_LOGO_APPLY_MAX_ERRORS - len(errors)
                if remaining > 0:
                    errors.extend(batch_stats['errors'][:remaining])

                processed += len(pending_ids)
                pending_ids = []
                send_websocket_update('updates', 'update', {
                    'type': 'epg_logo_setting_progress',
                    'task_id': task_id,
                    'progress': processed,
                    'total': total_channels,
                    'status': 'running',
                    'message': (
                        f'Updated {updated_count} channel logos, '
                        f'created {created_logos_count} new logos...'
                    ),
                    'updated_count': updated_count,
                    'created_logos_count': created_logos_count,
                })

            if pending_ids:
                batch = Channel.objects.filter(
                    id__in=pending_ids,
                ).select_related('epg_data', 'logo')
                batch_stats = apply_logos_from_epg_icon_url(batch)
                updated_count += batch_stats['updated_count']
                created_logos_count += batch_stats['created_logos_count']
                remaining = EPG_LOGO_APPLY_MAX_ERRORS - len(errors)
                if remaining > 0:
                    errors.extend(batch_stats['errors'][:remaining])
                processed += len(pending_ids)

        elif channel_ids:
            total_channels = len(channel_ids)
            logger.info(f"Starting EPG logo setting task for {total_channels} channels")

            send_websocket_update('updates', 'update', {
                'type': 'epg_logo_setting_progress',
                'task_id': task_id,
                'progress': 0,
                'total': total_channels,
                'status': 'running',
                'message': 'Starting EPG logo setting...'
            })

            for i in range(0, total_channels, batch_size):
                batch_ids = channel_ids[i:i + batch_size]
                channels = Channel.objects.filter(
                    id__in=batch_ids,
                ).select_related('epg_data', 'logo')

                batch_stats = apply_logos_from_epg_icon_url(channels)
                updated_count += batch_stats['updated_count']
                created_logos_count += batch_stats['created_logos_count']
                remaining = EPG_LOGO_APPLY_MAX_ERRORS - len(errors)
                if remaining > 0:
                    errors.extend(batch_stats['errors'][:remaining])

                progress = min(i + batch_size, total_channels)
                send_websocket_update('updates', 'update', {
                    'type': 'epg_logo_setting_progress',
                    'task_id': task_id,
                    'progress': progress,
                    'total': total_channels,
                    'status': 'running',
                    'message': (
                        f'Updated {updated_count} channel logos, '
                        f'created {created_logos_count} new logos...'
                    ),
                    'updated_count': updated_count,
                    'created_logos_count': created_logos_count,
                })
        else:
            raise ValueError("channel_ids or epg_source_id is required")

        # Send completion notification
        send_websocket_update('updates', 'update', {
            'type': 'epg_logo_setting_progress',
            'task_id': task_id,
            'progress': total_channels,
            'total': total_channels,
            'status': 'completed',
            'message': f'Successfully updated {updated_count} channel logos and created {created_logos_count} new logos from EPG data',
            'updated_count': updated_count,
            'created_logos_count': created_logos_count,
            'error_count': len(errors),
            'errors': errors
        })

        logger.info(f"EPG logo setting task completed. Updated {updated_count} channels, created {created_logos_count} logos")
        return {
            'status': 'completed',
            'updated_count': updated_count,
            'created_logos_count': created_logos_count,
            'error_count': len(errors),
            'errors': errors
        }

    except Exception as e:
        logger.error(f"EPG logo setting task failed: {e}")
        send_websocket_update('updates', 'update', {
            'type': 'epg_logo_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'failed',
            'message': f'Task failed: {str(e)}',
            'error': str(e)
        })
        raise


@shared_task(bind=True)
def set_channels_tvg_ids_from_epg(self, channel_ids):
    """
    Celery task to set channel TVG-IDs from EPG data for multiple channels
    """
    from core.utils import send_websocket_update

    task_id = self.request.id
    total_channels = len(channel_ids)
    updated_count = 0
    errors = []

    try:
        logger.info(f"Starting EPG TVG-ID setting task for {total_channels} channels")

        # Send initial progress
        send_websocket_update('updates', 'update', {
            'type': 'epg_tvg_id_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'running',
            'message': 'Starting EPG TVG-ID setting...'
        })

        batch_size = 100
        for i in range(0, total_channels, batch_size):
            batch_ids = channel_ids[i:i + batch_size]
            batch_updates = []

            # Get channels and their EPG data
            channels = Channel.objects.filter(id__in=batch_ids).select_related('epg_data')

            for channel in channels:
                try:
                    if channel.epg_data and channel.epg_data.tvg_id:
                        if channel.tvg_id != channel.epg_data.tvg_id:
                            channel.tvg_id = channel.epg_data.tvg_id
                            batch_updates.append(channel)
                            updated_count += 1
                except Exception as e:
                    errors.append(f"Channel {channel.id}: {str(e)}")
                    logger.error(f"Error processing channel {channel.id}: {e}")

            # Bulk update the batch
            if batch_updates:
                Channel.objects.bulk_update(batch_updates, ['tvg_id'])

            # Send progress update
            progress = min(i + batch_size, total_channels)
            send_websocket_update('updates', 'update', {
                'type': 'epg_tvg_id_setting_progress',
                'task_id': task_id,
                'progress': progress,
                'total': total_channels,
                'status': 'running',
                'message': f'Updated {updated_count} channel TVG-IDs...',
                'updated_count': updated_count
            })

        # Send completion notification
        send_websocket_update('updates', 'update', {
            'type': 'epg_tvg_id_setting_progress',
            'task_id': task_id,
            'progress': total_channels,
            'total': total_channels,
            'status': 'completed',
            'message': f'Successfully updated {updated_count} channel TVG-IDs from EPG data',
            'updated_count': updated_count,
            'error_count': len(errors),
            'errors': errors
        })

        logger.info(f"EPG TVG-ID setting task completed. Updated {updated_count} channels")
        return {
            'status': 'completed',
            'updated_count': updated_count,
            'error_count': len(errors),
            'errors': errors
        }

    except Exception as e:
        logger.error(f"EPG TVG-ID setting task failed: {e}")
        send_websocket_update('updates', 'update', {
            'type': 'epg_tvg_id_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'failed',
            'message': f'Task failed: {str(e)}',
            'error': str(e)
        })
        raise
