"""
Shared EPG utilities.

Season/episode extraction, WebSocket progress updates, and SD poster proxy URL
helpers live here so serializers, XMLTV output, and tasks can import without
circular dependencies.
"""

import gc
import hashlib
import re

from core.utils import send_websocket_update

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
