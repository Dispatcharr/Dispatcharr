# apps/channels/tasks.py
import logging
import os
import select
import re
import requests
import time
import json
import subprocess
from datetime import datetime, timedelta
import gc

from celery import shared_task
from django.utils.text import slugify

from apps.channels.models import Channel
from apps.epg.models import EPGData
from core.models import CoreSettings

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import tempfile
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Words we remove to help with fuzzy + embedding matching
COMMON_EXTRANEOUS_WORDS = [
    "tv", "channel", "network", "television",
    "east", "west", "hd", "uhd", "24/7",
    "1080p", "720p", "540p", "480p",
    "film", "movie", "movies"
]

def normalize_name(name: str) -> str:
    """
    A more aggressive normalization that:
      - Lowercases
      - Removes bracketed/parenthesized text
      - Removes punctuation
      - Strips extraneous words
      - Collapses extra spaces
    """
    if not name:
        return ""

    norm = name.lower()
    norm = re.sub(r"\[.*?\]", "", norm)
    norm = re.sub(r"\(.*?\)", "", norm)
    norm = re.sub(r"[^\w\s]", "", norm)
    tokens = norm.split()
    tokens = [t for t in tokens if t not in COMMON_EXTRANEOUS_WORDS]
    norm = " ".join(tokens).strip()
    return norm

@shared_task
def match_epg_channels():
    """
    Goes through all Channels and tries to find a matching EPGData row by:
      1) If channel.tvg_id is valid in EPGData, skip.
      2) If channel has a tvg_id but not found in EPGData, attempt direct EPGData lookup.
      3) Otherwise, perform name-based fuzzy matching with optional region-based bonus.
      4) If a match is found, we set channel.tvg_id
      5) Summarize and log results.
    """
    try:
        logger.info("Starting EPG matching logic...")

        # Attempt to retrieve a "preferred-region" if configured
        try:
            region_obj = CoreSettings.objects.get(key="preferred-region")
            region_code = region_obj.value.strip().lower()
        except CoreSettings.DoesNotExist:
            region_code = None

        matched_channels = []
        channels_to_update = []

        # Get channels that don't have EPG data assigned
        channels_without_epg = Channel.objects.filter(epg_data__isnull=True)
        logger.info(f"Found {channels_without_epg.count()} channels without EPG data")

        channels_json = []
        for channel in channels_without_epg:
            # Normalize TVG ID - strip whitespace and convert to lowercase
            normalized_tvg_id = channel.tvg_id.strip().lower() if channel.tvg_id else ""
            if normalized_tvg_id:
                logger.info(f"Processing channel {channel.id} '{channel.name}' with TVG ID='{normalized_tvg_id}'")

            channels_json.append({
                "id": channel.id,
                "name": channel.name,
                "tvg_id": normalized_tvg_id,  # Use normalized TVG ID
                "original_tvg_id": channel.tvg_id,  # Keep original for reference
                "fallback_name": normalized_tvg_id if normalized_tvg_id else channel.name,
                "norm_chan": normalize_name(normalized_tvg_id if normalized_tvg_id else channel.name)
            })

        # Similarly normalize EPG data TVG IDs
        epg_json = []
        for epg in EPGData.objects.all():
            normalized_tvg_id = epg.tvg_id.strip().lower() if epg.tvg_id else ""
            epg_json.append({
                'id': epg.id,
                'tvg_id': normalized_tvg_id,  # Use normalized TVG ID
                'original_tvg_id': epg.tvg_id,  # Keep original for reference
                'name': epg.name,
                'norm_name': normalize_name(epg.name),
                'epg_source_id': epg.epg_source.id if epg.epg_source else None,
            })

        # Log available EPG data TVG IDs for debugging
        unique_epg_tvg_ids = set(e['tvg_id'] for e in epg_json if e['tvg_id'])
        logger.info(f"Available EPG TVG IDs: {', '.join(sorted(unique_epg_tvg_ids))}")

        payload = {
            "channels": channels_json,
            "epg_data": epg_json,
            "region_code": region_code,
        }

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(json.dumps(payload).encode('utf-8'))
            temp_file_path = temp_file.name

        # After writing to the file but before subprocess
        # Explicitly delete the large data structures
        del payload
        gc.collect()

        process = subprocess.Popen(
            ['python', '/app/scripts/epg_match.py', temp_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout = ''
        block_size = 1024

        while True:
            # Monitor stdout and stderr for readability
            readable, _, _ = select.select([process.stdout, process.stderr], [], [], 1) # timeout of 1 second

            if not readable: # timeout expired
                if process.poll() is not None: # check if process finished
                    break
                else: # process still running, continue
                    continue

            for stream in readable:
                if stream == process.stdout:
                    stdout += stream.read(block_size)
                elif stream == process.stderr:
                    error = stream.readline()
                    if error:
                        logger.info(error.strip())

            if process.poll() is not None:
                break

        process.wait()
        os.remove(temp_file_path)

        if process.returncode != 0:
            return f"Failed to process EPG matching"

        result = json.loads(stdout)
        # This returns lists of dicts, not model objects
        channels_to_update_dicts = result["channels_to_update"]
        matched_channels = result["matched_channels"]

        # Explicitly clean up large objects
        del stdout, result
        gc.collect()

        # Convert your dict-based 'channels_to_update' into real Channel objects
        if channels_to_update_dicts:
            # Extract IDs of the channels that need updates
            channel_ids = [d["id"] for d in channels_to_update_dicts]

            # Fetch them from DB
            channels_qs = Channel.objects.filter(id__in=channel_ids)
            channels_list = list(channels_qs)

            # Build a map from channel_id -> epg_data_id (or whatever fields you need)
            epg_mapping = {
                d["id"]: d["epg_data_id"] for d in channels_to_update_dicts
            }

            # Populate each Channel object with the updated epg_data_id
            for channel_obj in channels_list:
                # The script sets 'epg_data_id' in the returned dict
                # We either assign directly, or fetch the EPGData instance if needed.
                channel_obj.epg_data_id = epg_mapping.get(channel_obj.id)

            # Now we have real model objects, so bulk_update will work
            Channel.objects.bulk_update(channels_list, ["epg_data"])

        total_matched = len(matched_channels)
        if total_matched:
            logger.info(f"Match Summary: {total_matched} channel(s) matched.")
            for (cid, cname, tvg) in matched_channels:
                logger.info(f"  - Channel ID={cid}, Name='{cname}' => tvg_id='{tvg}'")
        else:
            logger.info("No new channels were matched.")

        logger.info("Finished EPG matching logic.")

        # Send update with additional information for refreshing UI
        channel_layer = get_channel_layer()
        associations = [
            {"channel_id": chan["id"], "epg_data_id": chan["epg_data_id"]}
            for chan in channels_to_update_dicts
        ]

        async_to_sync(channel_layer.group_send)(
            'updates',
            {
                'type': 'update',
                "data": {
                    "success": True,
                    "type": "epg_match",
                    "refresh_channels": True,  # Flag to tell frontend to refresh channels
                    "matches_count": total_matched,
                    "message": f"EPG matching complete: {total_matched} channel(s) matched",
                    "associations": associations  # Add the associations data
                }
            }
        )

        return f"Done. Matched {total_matched} channel(s)."
    finally:
        # Final cleanup
        gc.collect()
        # Use our standardized cleanup function for more thorough memory management
        from core.utils import cleanup_memory
        cleanup_memory(log_usage=True, force_collection=True)


def evaluate_series_rules_impl(tvg_id: str | None = None):
    """Synchronous implementation of series rule evaluation; returns details for debugging."""
    from django.utils import timezone
    from apps.channels.models import Recording, Channel
    from apps.epg.models import EPGData, ProgramData

    rules = CoreSettings.get_dvr_series_rules()
    result = {"scheduled": 0, "details": []}
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

    # Preload existing recordings' program ids to avoid duplicates
    existing_program_ids = set()
    for rec in Recording.objects.all().only("custom_properties"):
        try:
            pid = rec.custom_properties.get("program", {}).get("id") if rec.custom_properties else None
            if pid is not None:
                # Normalize to string for consistent comparisons
                existing_program_ids.add(str(pid))
        except Exception:
            continue

    for rule in rules:
        rv_tvg = str(rule.get("tvg_id") or "").strip()
        mode = (rule.get("mode") or "all").lower()
        series_title = (rule.get("title") or "").strip()
        norm_series = normalize_name(series_title) if series_title else None
        if not rv_tvg:
            result["details"].append({"tvg_id": rv_tvg, "status": "invalid_rule"})
            continue

        epg = EPGData.objects.filter(tvg_id=rv_tvg).first()
        if not epg:
            result["details"].append({"tvg_id": rv_tvg, "status": "no_epg_match"})
            continue

        programs_qs = ProgramData.objects.filter(
                epg=epg,
                start_time__gte=now,
                start_time__lte=horizon,
            )
        if series_title:
            programs_qs = programs_qs.filter(title__iexact=series_title)
        programs = list(programs_qs.order_by("start_time"))
        # Fallback: if no direct matches and we have a title, try normalized comparison in Python
        if series_title and not programs:
            all_progs = ProgramData.objects.filter(
                epg=epg,
                start_time__gte=now,
                start_time__lte=horizon,
            ).only("id", "title", "start_time", "end_time", "custom_properties", "tvg_id")
            programs = [p for p in all_progs if normalize_name(p.title) == norm_series]

        channel = Channel.objects.filter(epg_data=epg).order_by("channel_number").first()
        if not channel:
            result["details"].append({"tvg_id": rv_tvg, "status": "no_channel_for_epg"})
            continue

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
                # Skip if already scheduled by program id
                if str(prog.id) in existing_program_ids:
                    continue
                # Extra guard: skip if a recording exists for the same channel + timeslot
                try:
                    from django.db.models import Q
                    if Recording.objects.filter(
                        channel=channel,
                        start_time=prog.start_time,
                        end_time=prog.end_time,
                    ).filter(Q(custom_properties__program__id=prog.id) | Q(custom_properties__program__title=prog.title)).exists():
                        continue
                except Exception:
                    continue  # already scheduled/recorded

                rec = Recording.objects.create(
                    channel=channel,
                    start_time=prog.start_time,
                    end_time=prog.end_time,
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
                existing_program_ids.add(str(prog.id))
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
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'updates',
            {'type': 'update', 'data': {"success": True, "type": "recordings_refreshed", "scheduled": result["scheduled"]}},
        )
    except Exception:
        pass

    return result


@shared_task
def evaluate_series_rules(tvg_id: str | None = None):
    return evaluate_series_rules_impl(tvg_id)


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


def _build_output_paths(channel, program, start_time, end_time):
    """
    Build (final_path, temp_ts_path, final_filename) using DVR templates.
    """
    from core.models import CoreSettings
    # Root for DVR recordings: fixed to /app/data inside the container
    library_root = '/app/data'

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
    # structure their library under /app/data as desired.
    if not rel_path.lower().endswith('.mkv'):
        rel_path = f"{rel_path}.mkv"

    # Normalize path (strip ./)
    if rel_path.startswith('./'):
        rel_path = rel_path[2:]
    final_path = rel_path if rel_path.startswith('/') else os.path.join(library_root, rel_path)
    final_path = os.path.normpath(final_path)
    # Ensure directory exists
    os.makedirs(os.path.dirname(final_path), exist_ok=True)

    # Derive temp TS path in same directory
    base_no_ext = os.path.splitext(os.path.basename(final_path))[0]
    temp_ts_path = os.path.join(os.path.dirname(final_path), f"{base_no_ext}.ts")
    return final_path, temp_ts_path, os.path.basename(final_path)


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
    channel = Channel.objects.get(id=channel_id)

    start_time = datetime.fromisoformat(start_time_str)
    end_time = datetime.fromisoformat(end_time_str)

    duration_seconds = int((end_time - start_time).total_seconds())
    # Build output paths from templates
    # We need program info; will refine after we load Recording cp below
    filename = None
    final_path = None
    temp_ts_path = None

    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        "updates",
        {
            "type": "update",
            "data": {"success": True, "type": "recording_started", "channel": channel.name}
        },
    )

    logger.info(f"Starting recording for channel {channel.name}")

    # Try to resolve the Recording row up front
    recording_obj = None
    try:
        from .models import Recording, Logo
        recording_obj = Recording.objects.get(id=recording_id)
        # Prime custom_properties with file info/status
        cp = recording_obj.custom_properties or {}
        cp.update({
            "status": "recording",
            "started_at": str(datetime.now()),
        })
        # Provide a predictable playback URL for the frontend
        cp["file_url"] = f"/api/channels/recordings/{recording_id}/file/"
        cp["output_file_url"] = cp["file_url"]

        # Determine program info (may include id for deeper details)
        program = cp.get("program") or {}
        final_path, temp_ts_path, filename = _build_output_paths(channel, program, start_time, end_time)
        cp["file_name"] = filename
        cp["file_path"] = final_path
        cp["_temp_file_path"] = temp_ts_path

        # Resolve poster the same way VODs do:
        # 1) Prefer image(s) from EPG Program custom_properties (images/icon)
        # 2) Otherwise reuse an existing VOD logo matching title (Movie/Series)
        # 3) Otherwise save any direct poster URL from provided program fields
        program = (cp.get("program") or {}) if isinstance(cp, dict) else {}

        def pick_best_image_from_epg_props(epg_props):
            try:
                images = epg_props.get("images") or []
                if not isinstance(images, list):
                    return None
                # Prefer poster/cover and larger sizes
                size_order = {"xxl": 6, "xl": 5, "l": 4, "m": 3, "s": 2, "xs": 1}
                def score(img):
                    t = (img.get("type") or "").lower()
                    size = (img.get("size") or "").lower()
                    return (
                        2 if t in ("poster", "cover") else 1,
                        size_order.get(size, 0)
                    )
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

        poster_logo_id = None
        poster_url = None

        # Try EPG Program custom_properties by ID
        try:
            from apps.epg.models import ProgramData
            prog_id = program.get("id")
            if prog_id:
                epg_program = ProgramData.objects.filter(id=prog_id).only("custom_properties").first()
                if epg_program and epg_program.custom_properties:
                    epg_props = epg_program.custom_properties or {}
                    poster_url = pick_best_image_from_epg_props(epg_props)
                    if not poster_url:
                        icon = epg_props.get("icon")
                        if isinstance(icon, str) and icon:
                            poster_url = icon
        except Exception as e:
            logger.debug(f"EPG image lookup failed: {e}")

        # Fallback: reuse VOD Logo by matching title
        if not poster_url and not poster_logo_id:
            try:
                from apps.vod.models import Movie, Series
                title = program.get("title") or channel.name
                vod_logo = None
                movie = Movie.objects.filter(name__iexact=title).select_related("logo").first()
                if movie and movie.logo:
                    vod_logo = movie.logo
                if not vod_logo:
                    series = Series.objects.filter(name__iexact=title).select_related("logo").first()
                    if series and series.logo:
                        vod_logo = series.logo
                if vod_logo:
                    poster_logo_id = vod_logo.id
            except Exception as e:
                logger.debug(f"VOD logo fallback failed: {e}")

        # External metadata lookups (TMDB/OMDb) when EPG/VOD didn't provide an image
        if not poster_url and not poster_logo_id:
            try:
                tmdb_key = os.environ.get('TMDB_API_KEY')
                omdb_key = os.environ.get('OMDB_API_KEY')
                title = (program.get('title') or channel.name or '').strip()
                year = None
                imdb_id = None

                # Try to derive year and imdb from EPG program custom_properties
                try:
                    from apps.epg.models import ProgramData
                    prog_id = program.get('id')
                    epg_program = ProgramData.objects.filter(id=prog_id).only('custom_properties').first() if prog_id else None
                    if epg_program and epg_program.custom_properties:
                        d = epg_program.custom_properties.get('date')
                        if d and len(str(d)) >= 4:
                            year = str(d)[:4]
                        imdb_id = epg_program.custom_properties.get('imdb.com_id') or imdb_id
                except Exception:
                    pass

                # TMDB: by IMDb ID
                if not poster_url and tmdb_key and imdb_id:
                    try:
                        url = f"https://api.themoviedb.org/3/find/{quote(imdb_id)}?api_key={tmdb_key}&external_source=imdb_id"
                        resp = requests.get(url, timeout=5)
                        if resp.ok:
                            data = resp.json() or {}
                            picks = []
                            for k in ('movie_results', 'tv_results', 'tv_episode_results', 'tv_season_results'):
                                lst = data.get(k) or []
                                picks.extend(lst)
                            poster_path = None
                            for item in picks:
                                if item.get('poster_path'):
                                    poster_path = item['poster_path']
                                    break
                            if poster_path:
                                poster_url = f"https://image.tmdb.org/t/p/w780{poster_path}"
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
            except Exception as e:
                logger.debug(f"External poster lookup failed: {e}")

        # Keyless fallback providers (no API keys required)
        if not poster_url and not poster_logo_id:
            try:
                title = (program.get('title') or channel.name or '').strip()
                if title:
                    # 1) TVMaze (TV shows) - singlesearch by title
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

                    # 2) iTunes Search API (movies or tv shows)
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
                                            # Scale up to 600x600 by convention
                                            poster_url = art.replace('100x100', '600x600')
                                            break
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Keyless poster lookup failed: {e}")

        # Last: check direct fields on provided program object
        if not poster_url and not poster_logo_id:
            for key in ("poster", "cover", "cover_big", "image", "icon"):
                val = program.get(key)
                if isinstance(val, dict):
                    candidate = val.get("url")
                    if candidate:
                        poster_url = candidate
                        break
                elif isinstance(val, str) and val:
                    poster_url = val
                    break

        # Create or assign Logo
        if not poster_logo_id and poster_url and len(poster_url) <= 1000:
            try:
                logo, _ = Logo.objects.get_or_create(url=poster_url, defaults={"name": program.get("title") or channel.name})
                poster_logo_id = logo.id
            except Exception as e:
                logger.debug(f"Unable to persist poster to Logo: {e}")

        if poster_logo_id:
            cp["poster_logo_id"] = poster_logo_id
        if poster_url and "poster_url" not in cp:
            cp["poster_url"] = poster_url

        # Ensure destination exists so it's visible immediately
        try:
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            if not os.path.exists(final_path):
                open(final_path, 'ab').close()
        except Exception:
            pass

        recording_obj.custom_properties = cp
        recording_obj.save(update_fields=["custom_properties"])
    except Exception as e:
        logger.debug(f"Unable to prime Recording metadata: {e}")
    interrupted = False
    interrupted_reason = None
    bytes_written = 0

    from requests.exceptions import ReadTimeout, ConnectionError as ReqConnectionError, ChunkedEncodingError

    # Determine internal base URL(s) for TS streaming
    # Prefer explicit override, then try common ports for debug and docker
    explicit = os.environ.get('DISPATCHARR_INTERNAL_TS_BASE_URL')
    is_dev = (os.environ.get('DISPATCHARR_ENV', '').lower() == 'dev') or \
             (os.environ.get('DISPATCHARR_DEBUG', '').lower() == 'true') or \
             (os.environ.get('REDIS_HOST', 'redis') in ('localhost', '127.0.0.1'))
    candidates = []
    if explicit:
        candidates.append(explicit)
    # Prefer environment variable for internal API base
    internal_api_base = os.environ.get('DISPATCHARR_INTERNAL_API_BASE')
    if internal_api_base:
        candidates.append(internal_api_base)
    # Use service name for Docker by default
    candidates.append('http://dispatcharr:9191')
    # Optionally add dev/debug ports if in dev mode
    if is_dev:
        candidates.extend([
            f"http://{os.environ.get('DISPATCHARR_HOST', '127.0.0.1')}:5656",
            f"http://{os.environ.get('DISPATCHARR_HOST', '127.0.0.1')}:9191"
        ])
    # Fallback to localhost as last resort
    candidates.extend([
        'http://localhost:5656',
        'http://localhost:9191'
    ])

    chosen_base = None
    last_error = None
    bytes_written = 0
    interrupted = False
    interrupted_reason = None

    # We'll attempt each base until we receive some data
    for base in candidates:
        try:
            test_url = f"{base.rstrip('/')}/proxy/ts/stream/{channel.uuid}"
            logger.info(f"DVR: trying TS base {base} -> {test_url}")

            with requests.get(
                test_url,
                headers={
                    'User-Agent': 'Dispatcharr-DVR',
                },
                stream=True,
                timeout=(10, 15),
            ) as response:
                response.raise_for_status()

                # Open the file and start copying; if we get any data within a short window, accept this base
                got_any_data = False
                test_window = 3.0  # seconds to detect first bytes
                window_start = time.time()

                with open(temp_ts_path, 'wb') as file:
                    started_at = time.time()
                    for chunk in response.iter_content(chunk_size=8192):
                        if not chunk:
                            # keep-alives may be empty; continue
                            if not got_any_data and (time.time() - window_start) > test_window:
                                break
                            continue
                        # We have data
                        got_any_data = True
                        chosen_base = base
                        # Fall through to full recording loop using this same response/connection
                        file.write(chunk)
                        bytes_written += len(chunk)
                        elapsed = time.time() - started_at
                        if elapsed > duration_seconds:
                            break
                        # Continue draining the stream
                        for chunk2 in response.iter_content(chunk_size=8192):
                            if not chunk2:
                                continue
                            file.write(chunk2)
                            bytes_written += len(chunk2)
                            elapsed = time.time() - started_at
                            if elapsed > duration_seconds:
                                break
                        break  # exit outer for-loop once we switched to full drain

                # If we wrote any bytes, treat as success and stop trying candidates
                if bytes_written > 0:
                    logger.info(f"DVR: selected TS base {base}; wrote initial {bytes_written} bytes")
                    break
                else:
                    last_error = f"no_data_from_{base}"
                    logger.warning(f"DVR: no data received from {base} within {test_window}s, trying next base")
                    # Clean up empty temp file
                    try:
                        if os.path.exists(temp_ts_path) and os.path.getsize(temp_ts_path) == 0:
                            os.remove(temp_ts_path)
                    except Exception:
                        pass
        except Exception as e:
            last_error = str(e)
            logger.warning(f"DVR: attempt failed for base {base}: {e}")

    if chosen_base is None and bytes_written == 0:
        interrupted = True
        interrupted_reason = f"no_stream_data: {last_error or 'all_bases_failed'}"
    else:
        # If we ended before reaching planned duration, record reason
        actual_elapsed = 0
        try:
            actual_elapsed = os.path.getsize(temp_ts_path) and (duration_seconds)  # Best effort; we streamed until duration or disconnect above
        except Exception:
            pass
        # We cannot compute accurate elapsed here; fine to leave as is
        pass

    # If no bytes were written at all, mark detail
    if bytes_written == 0 and not interrupted:
        interrupted = True
        interrupted_reason = f"no_stream_data: {last_error or 'unknown'}"

        # Update DB status immediately so the UI reflects the change on the event below
        try:
            if recording_obj is None:
                from .models import Recording
                recording_obj = Recording.objects.get(id=recording_id)
            cp_now = recording_obj.custom_properties or {}
            cp_now.update({
                "status": "interrupted" if interrupted else "completed",
                "ended_at": str(datetime.now()),
                "file_name": filename or cp_now.get("file_name"),
                "file_path": final_path or cp_now.get("file_path"),
            })
            if interrupted and interrupted_reason:
                cp_now["interrupted_reason"] = interrupted_reason
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

    # Remux TS to MKV container
    remux_success = False
    try:
        if temp_ts_path and os.path.exists(temp_ts_path):
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_ts_path, "-c", "copy", final_path
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            remux_success = os.path.exists(final_path)
            # Clean up temp file on success
            if remux_success:
                try:
                    os.remove(temp_ts_path)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"MKV remux failed: {e}")

    # Persist final metadata to Recording (status, ended_at, and stream stats if available)
    try:
        if recording_obj is None:
            from .models import Recording
            recording_obj = Recording.objects.get(id=recording_id)

        cp = recording_obj.custom_properties or {}
        cp.update({
            "ended_at": str(datetime.now()),
        })
        if interrupted:
            cp["status"] = "interrupted"
            if interrupted_reason:
                cp["interrupted_reason"] = interrupted_reason
        else:
            cp["status"] = "completed"
        cp["bytes_written"] = bytes_written
        cp["remux_success"] = remux_success

        # Try to get stream stats from TS proxy Redis metadata
        try:
            from core.utils import RedisClient
            from apps.proxy.ts_proxy.redis_keys import RedisKeys
            from apps.proxy.ts_proxy.constants import ChannelMetadataField

            r = RedisClient.get_client()
            if r is not None:
                metadata_key = RedisKeys.channel_metadata(str(channel.uuid))
                md = r.hgetall(metadata_key)
                if md:
                    def _gv(bkey):
                        return md.get(bkey.encode('utf-8'))

                    def _d(bkey, cast=str):
                        v = _gv(bkey)
                        try:
                            if v is None:
                                return None
                            s = v.decode('utf-8')
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

        recording_obj.custom_properties = cp
        recording_obj.save(update_fields=["custom_properties"])
    except Exception as e:
        logger.debug(f"Unable to finalize Recording metadata: {e}")

    # Optionally run comskip post-process
    try:
        from core.models import CoreSettings
        if CoreSettings.get_dvr_comskip_enabled():
            comskip_process_recording.delay(recording_id)
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
        from .signals import schedule_recording_task

        redis = RedisClient.get_client()
        if redis:
            lock_key = "dvr:recover_lock"
            # Set lock with 60s TTL; only first winner proceeds
            if not redis.set(lock_key, "1", ex=60, nx=True):
                return "Recovery already in progress"

        now = timezone.now()

        # Resume in-window recordings
        active = Recording.objects.filter(start_time__lte=now, end_time__gt=now)
        for rec in active:
            try:
                cp = rec.custom_properties or {}
                # Mark interrupted due to restart; will flip to 'recording' when task starts
                cp["status"] = "interrupted"
                cp["interrupted_reason"] = "server_restarted"
                rec.custom_properties = cp
                rec.save(update_fields=["custom_properties"])

                # Start recording for remaining window
                run_recording.apply_async(
                    args=[rec.id, rec.channel_id, str(now), str(rec.end_time)], eta=now
                )
            except Exception as e:
                logger.warning(f"Failed to resume recording {rec.id}: {e}")

        # Ensure future recordings are scheduled
        upcoming = Recording.objects.filter(start_time__gt=now, end_time__gt=now)
        for rec in upcoming:
            try:
                # Schedule task at start_time
                task_id = schedule_recording_task(rec)
                if task_id:
                    rec.task_id = task_id
                    rec.save(update_fields=["task_id"])
            except Exception as e:
                logger.warning(f"Failed to schedule recording {rec.id}: {e}")

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

    cp = rec.custom_properties or {}
    file_path = (cp or {}).get("file_path")
    if not file_path or not os.path.exists(file_path):
        return "no_file"

    if isinstance(cp.get("comskip"), dict) and cp["comskip"].get("status") == "completed":
        return "already_processed"

    comskip_bin = shutil.which("comskip")
    if not comskip_bin:
        cp["comskip"] = {"status": "skipped", "reason": "comskip_not_installed"}
        rec.custom_properties = cp
        rec.save(update_fields=["custom_properties"])
        _ws('skipped', {"reason": "comskip_not_installed"})
        return "comskip_missing"

    base, _ = os.path.splitext(file_path)
    edl_path = f"{base}.edl"

    # Notify start
    _ws('started', {"title": (cp.get('program') or {}).get('title') or os.path.basename(file_path)})

    try:
        cmd = [comskip_bin, "--output", os.path.dirname(file_path)]
        # Prefer system ini if present to squelch warning and get sane defaults
        for ini_path in ("/etc/comskip/comskip.ini", "/app/docker/comskip.ini"):
            if os.path.exists(ini_path):
                cmd.extend([f"--ini={ini_path}"])
                break
        cmd.append(file_path)
        subprocess.run(cmd, check=True)
    except Exception as e:
        cp["comskip"] = {"status": "error", "reason": f"comskip_failed: {e}"}
        rec.custom_properties = cp
        rec.save(update_fields=["custom_properties"])
        _ws('error', {"reason": str(e)})
        return "comskip_failed"

    if not os.path.exists(edl_path):
        cp["comskip"] = {"status": "error", "reason": "edl_not_found"}
        rec.custom_properties = cp
        rec.save(update_fields=["custom_properties"])
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
        rec.custom_properties = cp
        rec.save(update_fields=["custom_properties"])
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
        cp["comskip"] = {"status": "completed", "skipped": True, "edl": os.path.basename(edl_path)}
        rec.custom_properties = cp
        rec.save(update_fields=["custom_properties"])
        _ws('skipped', {"reason": "no_commercials", "commercials": 0})
        return "no_commercials"

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
                lf.write(f"file '{pth}'\n")

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

        cp["comskip"] = {
            "status": "completed",
            "edl": os.path.basename(edl_path),
            "segments_kept": len(parts),
            "commercials": len(commercials),
        }
        rec.custom_properties = cp
        rec.save(update_fields=["custom_properties"])
        _ws('completed', {"commercials": len(commercials), "segments_kept": len(parts)})
        return "ok"
    except Exception as e:
        cp["comskip"] = {"status": "error", "reason": str(e)}
        rec.custom_properties = cp
        rec.save(update_fields=["custom_properties"])
        _ws('error', {"reason": str(e)})
        return f"error:{e}"
def _resolve_poster_for_program(channel_name, program):
    """Internal helper that attempts to resolve a poster URL and/or Logo id.
    Returns (poster_logo_id, poster_url) where either may be None.
    """
    poster_logo_id = None
    poster_url = None

    # Try EPG Program images first
    try:
        from apps.epg.models import ProgramData
        prog_id = program.get("id") if isinstance(program, dict) else None
        if prog_id:
            epg_program = ProgramData.objects.filter(id=prog_id).only("custom_properties").first()
            if epg_program and epg_program.custom_properties:
                epg_props = epg_program.custom_properties or {}

                def pick_best_image_from_epg_props(epg_props):
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

                poster_url = pick_best_image_from_epg_props(epg_props)
                if not poster_url:
                    icon = epg_props.get("icon")
                    if isinstance(icon, str) and icon:
                        poster_url = icon
    except Exception:
        pass

    # VOD logo fallback by title
    if not poster_url and not poster_logo_id:
        try:
            from apps.vod.models import Movie, Series
            title = (program.get("title") if isinstance(program, dict) else None) or channel_name
            vod_logo = None
            movie = Movie.objects.filter(name__iexact=title).select_related("logo").first()
            if movie and movie.logo:
                vod_logo = movie.logo
            if not vod_logo:
                series = Series.objects.filter(name__iexact=title).select_related("logo").first()
                if series and series.logo:
                    vod_logo = series.logo
            if vod_logo:
                poster_logo_id = vod_logo.id
        except Exception:
            pass

    # Keyless providers (TVMaze & iTunes)
    if not poster_url and not poster_logo_id:
        try:
            title = (program.get('title') if isinstance(program, dict) else None) or channel_name
            if title:
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

    # Fallback: search existing Logo entries by name if we still have nothing
    if not poster_logo_id and not poster_url:
        try:
            from .models import Logo
            title = (program.get("title") if isinstance(program, dict) else None) or channel_name
            existing = Logo.objects.filter(name__iexact=title).first()
            if existing:
                poster_logo_id = existing.id
                poster_url = existing.url
        except Exception:
            pass

    # Save to Logo if URL available
    if not poster_logo_id and poster_url and len(poster_url) <= 1000:
        try:
            from .models import Logo
            logo, _ = Logo.objects.get_or_create(url=poster_url, defaults={"name": (program.get("title") if isinstance(program, dict) else None) or channel_name})
            poster_logo_id = logo.id
        except Exception:
            pass

    return poster_logo_id, poster_url


@shared_task
def prefetch_recording_artwork(recording_id):
    """Prefetch poster info for a scheduled recording so the UI can show art in Upcoming."""
    try:
        from .models import Recording
        rec = Recording.objects.get(id=recording_id)
        cp = rec.custom_properties or {}
        program = cp.get("program") or {}
        poster_logo_id, poster_url = _resolve_poster_for_program(rec.channel.name, program)
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
            rec.custom_properties = cp
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
