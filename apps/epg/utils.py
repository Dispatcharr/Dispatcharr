"""
Shared EPG utilities — season/episode extraction.

These live here (rather than in serializers.py or tasks.py) to avoid circular imports:
serializers → tasks and channels/tasks → serializers both need these functions.
"""

import re

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
