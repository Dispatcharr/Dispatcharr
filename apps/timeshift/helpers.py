"""URL builders, timestamp conversion and Range helpers for XC catch-up."""

import logging
import re
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_DURATION_MINUTES = 120
DURATION_BUFFER_MINUTES = 5
MAX_DURATION_MINUTES = 480
RANGE_HEADER_RE = re.compile(r"^bytes=(\d+)-")

PROVIDER_ARCHIVE_CACHE_TTL_SECONDS = 300
MAX_AUTO_PREV_DAYS = 30
_ARCHIVE_DAYS_CACHE_KEY = "timeshift:provider_archive_days_capped"


def _scan_provider_archive_days():
    from apps.channels.models import Stream

    max_days = 0
    # tv_archive can be stored as int or string in custom_properties depending
    # on which version of the M3U importer wrote it; iterate and coerce.
    candidates = (
        Stream.objects.filter(m3u_account__account_type="XC")
        .exclude(custom_properties__isnull=True)
        .values_list("custom_properties", flat=True)
    )
    for props in candidates:
        try:
            if not int((props or {}).get("tv_archive", 0) or 0):
                continue
            value = int((props or {}).get("tv_archive_duration", 0) or 0)
        except (TypeError, ValueError):
            continue
        if value > max_days:
            max_days = value

    return min(max_days, MAX_AUTO_PREV_DAYS)


def compute_provider_archive_days_capped():
    """Scan XC streams for the maximum tv_archive_duration (capped, cached).

    Returns 0 when no XC stream advertises catch-up. Cached for 5 minutes via
    Django's cache framework to avoid re-scanning on every XMLTV request.
    """
    return cache.get_or_set(
        _ARCHIVE_DAYS_CACHE_KEY,
        _scan_provider_archive_days,
        PROVIDER_ARCHIVE_CACHE_TTL_SECONDS,
    )


def get_programme_duration(channel, timestamp_str):
    """Return the duration in minutes of the EPG programme starting at timestamp_str.

    Falls back to DEFAULT_DURATION_MINUTES when no programme matches.
    timestamp_str is in the format YYYY-MM-DD:HH-MM in the provider's local time
    (already converted by the caller).
    """
    try:
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d:%H-%M")
        if not channel.epg_data:
            return DEFAULT_DURATION_MINUTES

        programme = channel.epg_data.programs.filter(
            start_time__lte=dt, end_time__gt=dt
        ).first()
        if not programme:
            return DEFAULT_DURATION_MINUTES

        duration_seconds = (programme.end_time - programme.start_time).total_seconds()
        duration_minutes = int(duration_seconds / 60) + DURATION_BUFFER_MINUTES
        return min(duration_minutes, MAX_DURATION_MINUTES)
    except Exception:
        return DEFAULT_DURATION_MINUTES


def build_timeshift_url_format_a(m3u_account, stream_id, timestamp, duration_minutes):
    """Format A: /streaming/timeshift.php?username=&password=&stream=&start=&duration="""
    return (
        f"{m3u_account.server_url.rstrip('/')}/streaming/timeshift.php"
        f"?username={m3u_account.username}"
        f"&password={m3u_account.password}"
        f"&stream={stream_id}"
        f"&start={timestamp}"
        f"&duration={duration_minutes}"
    )


def build_timeshift_url_format_b(m3u_account, stream_id, timestamp, duration_minutes):
    """Format B: /timeshift/{user}/{pass}/{duration}/{timestamp}/{stream_id}.ts"""
    return (
        f"{m3u_account.server_url.rstrip('/')}/timeshift"
        f"/{m3u_account.username}"
        f"/{m3u_account.password}"
        f"/{duration_minutes}"
        f"/{timestamp}"
        f"/{stream_id}.ts"
    )


def convert_timestamp_to_local(timestamp, timezone_str):
    """Convert a UTC YYYY-MM-DD:HH-MM timestamp into the provider's local zone.

    XC providers typically expect their own local time. The EPG / IPTV clients
    deal in UTC.
    """
    try:
        utc_time = datetime.strptime(timestamp, "%Y-%m-%d:%H-%M").replace(tzinfo=dt_timezone.utc)
        local_time = utc_time.astimezone(ZoneInfo(timezone_str))
        return local_time.strftime("%Y-%m-%d:%H-%M")
    except Exception as e:
        logger.error("Timeshift timestamp conversion failed for %r in %s: %s", timestamp, timezone_str, e)
        return timestamp


def parse_range_start(range_header):
    """Extract the byte start of a Range header (`bytes=N-...`).

    Returns 0 when the header is absent or malformed.
    """
    if not range_header:
        return 0
    match = RANGE_HEADER_RE.match(range_header.strip())
    if not match:
        return 0
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return 0
