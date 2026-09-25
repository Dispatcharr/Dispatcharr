"""
Shared EPG utilities.

Season/episode extraction, original-air-date helpers, WebSocket progress updates,
and SD poster proxy URL helpers live here so serializers, XMLTV output, and tasks
can import without circular dependencies.
"""

import gc
import hashlib
import re
from datetime import timedelta

from django.db.models import Max, Q
from django.utils import timezone as dj_timezone

from core.utils import send_websocket_update

# Retention floor/ceiling for ProgramData pruning (see epg_retention_cutoffs).
# One day so "what aired earlier today" survives a refresh even on plain live
# channels; capped at 30 so a channel's own catchup_days can't be set high
# enough to keep effectively-unbounded guide history.
DEFAULT_EPG_RETENTION_DAYS = 1
MAX_EPG_RETENTION_DAYS = 30


def epg_retention_cutoffs(epg_ids, *, now=None):
    """
    Map each epg_id to the oldest ProgramData.end_time worth keeping.

    A programme past its epg's cutoff is safe to prune on the next refresh:
    no channel's catchup_days can reach back far enough to ever request it
    again. The cutoff is the largest catchup_days among catchup-enabled
    channels mapped to that epg, floored at DEFAULT_EPG_RETENTION_DAYS and
    capped at MAX_EPG_RETENTION_DAYS; an epg with no catchup-enabled channel
    still gets the floor, so non-catchup channels keep a rolling one-day
    guide history too.

    A channel's effective epg is its own Channel.epg_data, unless a
    ChannelOverride redirects it elsewhere -- ChannelOverride has no
    is_catchup/catchup_days of its own, so the base Channel's catchup fields
    still apply either way. Both paths are checked so an override-only
    mapping (which bulk parsing already treats as mapped, see
    _epg_ids_mapped_to_channels) doesn't silently fall back to the
    one-day floor for a channel that actually wants more.
    """
    from apps.channels.models import Channel

    epg_ids = list(epg_ids)
    if not epg_ids:
        return {}

    if now is None:
        now = dj_timezone.now()

    max_catchup_days = {}

    def _merge_max(rows):
        for epg_id, days in rows:
            if days is None:
                continue
            if days > max_catchup_days.get(epg_id, -1):
                max_catchup_days[epg_id] = days

    _merge_max(
        Channel.objects.filter(epg_data_id__in=epg_ids, is_catchup=True)
        .filter(Q(override__isnull=True) | Q(override__epg_data_id__isnull=True))
        .values("epg_data_id")
        .annotate(days=Max("catchup_days"))
        .values_list("epg_data_id", "days")
    )
    _merge_max(
        Channel.objects.filter(override__epg_data_id__in=epg_ids, is_catchup=True)
        .values("override__epg_data_id")
        .annotate(days=Max("catchup_days"))
        .values_list("override__epg_data_id", "days")
    )

    cutoffs = {}
    for epg_id in epg_ids:
        days = max_catchup_days.get(epg_id) or 0
        days = max(DEFAULT_EPG_RETENTION_DAYS, min(days, MAX_EPG_RETENTION_DAYS))
        cutoffs[epg_id] = now - timedelta(days=days)
    return cutoffs


# Matches patterns like "S12 E6", "S3E21", "S8 E8 P2/2"
_ONSCREEN_RE = re.compile(r'S(\d+)\s*E(\d+)', re.IGNORECASE)

# Ordered patterns for extracting season/episode from the start of description text.
# Only used as a fallback when <episode-num> XML elements don't provide S/E.
_DESC_SE_PATTERNS = [
    # S01E01, S01 E01, S1E1, S1 E1
    re.compile(r'^[\s\-:]*S(\d+)\s*E(\d+)[\s\-:.]*', re.IGNORECASE),
    # Season 1 Episode 1, Season1 Episode1, Season1Episode1
    re.compile(r'^[\s\-:]*Season\s*(\d+)\s*Episode\s*(\d+)[\s\-:.]*', re.IGNORECASE),
    # 1x01 format (requires 2+ digit episode to avoid false positives)
    re.compile(r'^[\s\-:]*(\d+)x(\d{2,})[\s\-:.]*'),
]

_SD_POSTER_CACHE_BUST_LEN = 12


def sd_poster_cache_bust(sd_icon_url):
    """
    Short content hash of an SD poster URI for nginx cache busting.

    Same URI keeps the same ``v`` (long-lived nginx cache). A new artwork URI
    after refresh gets a new ``v`` so clients do not keep stale bytes.
    """
    if not sd_icon_url:
        return ''
    return hashlib.sha256(sd_icon_url.encode('utf-8')).hexdigest()[:_SD_POSTER_CACHE_BUST_LEN]


def sd_poster_proxy_path(program_id, sd_icon_url):
    """
    Relative proxy path for a program poster.

    Includes ``?v=`` when ``sd_icon_url`` is set so nginx cache keys change with
    the upstream SD URI. The poster endpoint ignores ``v``; nginx keys on full URI.
    """
    path = f'/api/epg/programs/{program_id}/poster/'
    bust = sd_poster_cache_bust(sd_icon_url)
    if not bust:
        return path
    return f'{path}?v={bust}'


def extract_season_episode_from_description(desc):
    """
    Extract season/episode from the beginning of description text.
    Returns (season, episode, cleaned_desc).
    Returns (None, None, desc) if no pattern matches.
    """
    if not desc:
        return None, None, desc
    for pattern in _DESC_SE_PATTERNS:
        match = pattern.match(desc)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            cleaned = desc[match.end():].strip()
            return season, episode, cleaned
    return None, None, desc


def extract_season_episode(cp, description=None):
    """Extract season/episode from custom_properties with onscreen_episode and description fallbacks."""
    season = cp.get('season')
    episode = cp.get('episode')
    if (season is None or episode is None) and cp.get('onscreen_episode'):
        match = _ONSCREEN_RE.search(cp['onscreen_episode'])
        if match:
            if season is None:
                season = int(match.group(1))
            if episode is None:
                episode = int(match.group(2))
    # Third fallback: extract S/E from description text
    if (season is None or episode is None) and description:
        d_season, d_episode, _ = extract_season_episode_from_description(description)
        if season is None:
            season = d_season
        if episode is None:
            episode = d_episode
    return season, episode


def fill_original_air_date_if_missing(custom_props, candidate):
    """
    Set previously_shown_details.start from candidate when that field is absent.

    Mutates and returns ``custom_props`` for convenience. Callers may ignore the
    return value and rely on the in-place update.

    Used for Gracenote-style episode-num system="original-air-date" and Schedules
    Direct originalAirDate. Does not use XMLTV <date>, which is production /
    copyright date per the DTD, not original air date.
    """
    if not isinstance(custom_props, dict) or candidate is None:
        return custom_props

    try:
        value = str(candidate).strip()
    except Exception:
        return custom_props
    if not value:
        return custom_props

    details = custom_props.get('previously_shown_details')
    if isinstance(details, dict) and details.get('start'):
        return custom_props

    if isinstance(details, dict):
        updated = dict(details)
    else:
        updated = {}
    updated['start'] = value
    custom_props['previously_shown_details'] = updated
    return custom_props


def send_epg_update(source_id, action, progress, **kwargs):
    """Send WebSocket update about EPG download/parsing progress."""
    data = {
        "progress": progress,
        "type": "epg_refresh",
        "source": source_id,
        "action": action,
    }
    data.update(kwargs)

    # High-frequency program parsing needs more aggressive memory management
    collect_garbage = action == "parsing_programs" and progress % 10 == 0
    send_websocket_update('updates', 'update', data, collect_garbage=collect_garbage)

    data = None

    if action == "parsing_programs" and progress % 50 == 0:
        gc.collect()
