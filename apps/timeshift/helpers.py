"""URL builders and timestamp helpers for XC catch-up."""

import logging
from collections import namedtuple
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Credentials for the profile whose pool slot was reserved (not raw account fields).
TimeshiftCredentials = namedtuple(
    "TimeshiftCredentials", ("server_url", "username", "password")
)

DEFAULT_DURATION_MINUTES = 120
DURATION_BUFFER_MINUTES = 5
MAX_DURATION_MINUTES = 480


def parse_catchup_timestamp(timestamp_str):
    """Parse a catch-up timestamp string.

    Args:
        timestamp_str: ``YYYY-MM-DD:HH-MM`` (iPlayTV/TiviMate) or
            ``YYYY-MM-DD_HH-MM`` (XC underscore form).

    Returns:
        A naive datetime on success, or None.
    """
    for fmt in ("%Y-%m-%d:%H-%M", "%Y-%m-%d_%H-%M"):
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue
    return None


def convert_timestamp_to_provider_tz(timestamp_str, provider_tz_name):
    """Convert a UTC catch-up timestamp to the provider's local zone.

    Args:
        timestamp_str: UTC wall-clock in ``YYYY-MM-DD:HH-MM`` or underscore form.
        provider_tz_name: IANA zone from the provider's ``server_info.timezone``
            (e.g. ``Europe/Brussels``). Falsy, ``UTC``, or unknown: no conversion.

    Returns:
        ``YYYY-MM-DD:HH-MM`` in the provider zone, or the input unchanged on skip/failure.
    """
    if not provider_tz_name or provider_tz_name == "UTC":
        return timestamp_str
    dt = parse_catchup_timestamp(timestamp_str)
    if dt is None:
        return timestamp_str
    try:
        target = ZoneInfo(provider_tz_name)
    except Exception:
        logger.warning(
            "Timeshift: unknown provider timezone %r, no conversion applied",
            provider_tz_name,
        )
        return timestamp_str
    # timezone.utc, not ZoneInfo("UTC"): avoids mis-set Docker /etc/timezone.
    local_dt = dt.replace(tzinfo=timezone.utc).astimezone(target)
    return local_dt.strftime("%Y-%m-%d:%H-%M")


def get_programme_duration(channel, timestamp_str):
    """Look up catch-up duration in minutes from EPG.

    Args:
        channel: Channel with optional ``epg_data`` relation loaded.
        timestamp_str: Programme start in UTC (same shape as the client URL).

    Returns:
        Programme length plus a small buffer, capped at ``MAX_DURATION_MINUTES``,
        or ``DEFAULT_DURATION_MINUTES`` when EPG lookup fails.
    """
    try:
        dt = parse_catchup_timestamp(timestamp_str)
        if dt is None:
            return DEFAULT_DURATION_MINUTES
        # EPG times are timezone-aware; parsed value must be too.
        dt = dt.replace(tzinfo=timezone.utc)
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


def build_timeshift_url_format_a(creds, stream_id, timestamp, duration_minutes):
    """QUERY layout: ``/streaming/timeshift.php?username=...&start=...``"""
    return (
        f"{creds.server_url.rstrip('/')}/streaming/timeshift.php"
        f"?username={quote(str(creds.username), safe='')}"
        f"&password={quote(str(creds.password), safe='')}"
        f"&stream={stream_id}"
        f"&start={timestamp}"
        f"&duration={duration_minutes}"
    )


def build_timeshift_url_format_b(creds, stream_id, timestamp, duration_minutes):
    """PATH layout: ``/timeshift/{user}/{pass}/{dur}/{start}/{id}.ts``"""
    return (
        f"{creds.server_url.rstrip('/')}/timeshift"
        f"/{quote(str(creds.username), safe='')}"
        f"/{quote(str(creds.password), safe='')}"
        f"/{duration_minutes}"
        f"/{timestamp}"
        f"/{stream_id}.ts"
    )


def build_timeshift_candidate_urls(creds, stream_id, timestamp, duration_minutes):
    """Build ordered upstream URL candidates (PATH forms first, QUERY last).

    Args:
        creds: ``TimeshiftCredentials`` for the reserved profile.
        stream_id: Provider stream id from the catch-up stream's custom properties.
        timestamp: Already converted to the serving provider's local zone.
        duration_minutes: Archive window length passed to the provider.

    Returns:
        List of URL strings to try in order. QUERY forms are last because some
        providers return live TV even when ``start`` is set.
    """
    underscore_ts = format_timestamp_as_underscore(timestamp)
    sql_ts = format_timestamp_as_sql_datetime(timestamp)
    return [
        build_timeshift_url_format_b(creds, stream_id, timestamp, duration_minutes),
        build_timeshift_url_format_b(creds, stream_id, underscore_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, underscore_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, sql_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, timestamp, duration_minutes),
    ]


def format_timestamp_as_underscore(timestamp):
    """Reshape to ``YYYY-MM-DD_HH-MM`` without timezone conversion."""
    dt = parse_catchup_timestamp(timestamp)
    if dt is None:
        logger.error("Timeshift underscore reshape failed for %r: unrecognised format", timestamp)
        return timestamp
    return dt.strftime("%Y-%m-%d_%H-%M")


def format_timestamp_as_sql_datetime(timestamp):
    """Reshape to ``YYYY-MM-DD HH:MM:SS`` without timezone conversion."""
    dt = parse_catchup_timestamp(timestamp)
    if dt is None:
        logger.error("Timeshift SQL timestamp reshape failed for %r: unrecognised format", timestamp)
        return timestamp
    return dt.strftime("%Y-%m-%d %H:%M:%S")
