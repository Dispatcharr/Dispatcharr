"""URL builders and timestamp helpers for XC catch-up."""

import logging
import re
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

# Wall-clock shapes seen from XC catch-up clients. Compiled once.
_CATCHUP_WALL_CLOCK_RE = re.compile(
    r"^"
    r"(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?P<dtsep>[:_]| )"
    r"(?P<hour>\d{2})"
    r"(?P<hmsep>[-:])"
    r"(?P<minute>\d{2})"
    r"(?:"
    r":"
    r"(?P<second>\d{2})"
    r")?"
    r"$"
)


def normalize_catchup_timestamp_input(timestamp_str):
    """Map a client catch-up timestamp to an ISO-8601 string for ``fromisoformat``.

    Supported inputs:
        - ``YYYY-MM-DD:HH-MM`` (XC colon-dash)
        - ``YYYY-MM-DD_HH-MM`` (XC underscore)
        - ``YYYY-MM-DD:HH:MM[:SS]`` (XC colon time in catch-up URLs)
        - ``YYYY-MM-DD HH:MM[:SS]`` (EPG / SQL datetime)
        - ISO-8601 UTC (``2026-07-09T14:00:00Z`` or with offset)
        - Unix epoch seconds (10 digits) or milliseconds (13 digits)

    Returns:
        An ISO-8601 date-time string (``YYYY-MM-DDTHH:MM:SS``), or None if
        the value does not match a known catch-up shape.
    """
    if timestamp_str is None:
        return None
    if not isinstance(timestamp_str, str):
        timestamp_str = str(timestamp_str)
    value = timestamp_str.strip()
    if not value:
        return None

    if value.isdigit():
        length = len(value)
        if length == 10:
            dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
            return dt.replace(tzinfo=None).isoformat(timespec="seconds")
        if length == 13:
            dt = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
            return dt.replace(tzinfo=None).isoformat(timespec="seconds")
        return None

    if "T" in value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            return None

    match = _CATCHUP_WALL_CLOCK_RE.match(value)
    if not match:
        return None

    parts = match.groupdict()
    second = parts["second"] or "00"
    return f"{parts['date']}T{parts['hour']}:{parts['minute']}:{second}"


def parse_catchup_timestamp(timestamp_str):
    """Parse a catch-up timestamp string into a naive UTC wall-clock datetime.

    See ``normalize_catchup_timestamp_input`` for supported input shapes.

    Returns:
        A naive datetime on success, or None.
    """
    iso_value = normalize_catchup_timestamp_input(timestamp_str)
    if iso_value is None:
        if timestamp_str is not None and str(timestamp_str).strip():
            logger.debug(
                "Timeshift: unrecognised catch-up timestamp: %r", timestamp_str
            )
        return None
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        logger.debug(
            "Timeshift: invalid catch-up timestamp after normalize: %r -> %r",
            timestamp_str,
            iso_value,
        )
        return None


def _reshape_timestamp(timestamp, strftime_fmt, label):
    dt = parse_catchup_timestamp(timestamp)
    if dt is None:
        logger.error(
            "Timeshift %s reshape failed for %r: unrecognised format", label, timestamp
        )
        return timestamp
    return dt.strftime(strftime_fmt)


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


def get_programme_info(channel, timestamp_str):
    """Return EPG metadata for the programme airing at *timestamp_str*."""
    try:
        dt = parse_catchup_timestamp(timestamp_str)
        if dt is None:
            return None
        dt = dt.replace(tzinfo=timezone.utc)
        if not channel or not getattr(channel, "epg_data", None):
            return None

        programme = channel.epg_data.programs.filter(
            start_time__lte=dt, end_time__gt=dt
        ).first()
        if not programme:
            return None

        duration_seconds = (programme.end_time - programme.start_time).total_seconds()
        return {
            "title": programme.title,
            "sub_title": programme.sub_title or "",
            "description": programme.description or "",
            "start_time": programme.start_time.isoformat(),
            "end_time": programme.end_time.isoformat(),
            "duration_secs": int(duration_seconds),
        }
    except Exception:
        return None


def get_catchup_programmes_for_sessions(sessions):
    """Resolve EPG metadata for catch-up stats cards (batch, on demand).

    Each session dict needs ``session_id``, ``channel_uuid``, and
    ``programme_start``. Called by the frontend when active sessions or seek
    position change, not on every stats poll.
    """
    from apps.channels.models import Channel

    if not sessions:
        return []

    valid = [
        s for s in sessions
        if s.get("channel_uuid") and s.get("programme_start") and s.get("session_id")
    ]
    if not valid:
        return []

    valid = valid[:50]
    uuids = list({str(s["channel_uuid"]) for s in valid})
    channels_by_uuid = {
        str(ch.uuid): ch
        for ch in Channel.objects.filter(uuid__in=uuids).select_related("epg_data")
    }

    results = []
    for session in valid:
        channel_uuid = str(session["channel_uuid"])
        programme_start = session["programme_start"]
        channel = channels_by_uuid.get(channel_uuid)
        info = get_programme_info(channel, programme_start) if channel else None
        entry = {
            "session_id": session["session_id"],
            "channel_uuid": channel_uuid,
            "programme_start": programme_start,
        }
        if info:
            entry.update({
                "title": info["title"],
                "sub_title": info.get("sub_title", ""),
                "description": info.get("description", ""),
                "start_time": info["start_time"],
                "end_time": info["end_time"],
                "duration_secs": info["duration_secs"],
            })
        results.append(entry)
    return results


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
    dt = parse_catchup_timestamp(timestamp)
    if dt is None:
        colon_dash_ts = timestamp
        underscore_ts = timestamp
        colon_seconds_ts = timestamp
        sql_ts = timestamp
    else:
        colon_dash_ts = dt.strftime("%Y-%m-%d:%H-%M")
        underscore_ts = dt.strftime("%Y-%m-%d_%H-%M")
        colon_seconds_ts = dt.strftime("%Y-%m-%d:%H:%M:%S")
        sql_ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    return [
        build_timeshift_url_format_b(creds, stream_id, colon_dash_ts, duration_minutes),
        build_timeshift_url_format_b(creds, stream_id, underscore_ts, duration_minutes),
        build_timeshift_url_format_b(creds, stream_id, colon_seconds_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, underscore_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, sql_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, colon_dash_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, colon_seconds_ts, duration_minutes),
    ]


def format_timestamp_as_colon_dash(timestamp):
    """Reshape to ``YYYY-MM-DD:HH-MM`` without timezone conversion."""
    return _reshape_timestamp(timestamp, "%Y-%m-%d:%H-%M", "colon-dash")


def format_timestamp_as_colon_seconds(timestamp):
    """Reshape to ``YYYY-MM-DD:HH:MM:SS`` without timezone conversion."""
    return _reshape_timestamp(timestamp, "%Y-%m-%d:%H:%M:%S", "colon-seconds")


def format_timestamp_as_underscore(timestamp):
    """Reshape to ``YYYY-MM-DD_HH-MM`` without timezone conversion."""
    return _reshape_timestamp(timestamp, "%Y-%m-%d_%H-%M", "underscore")


def format_timestamp_as_sql_datetime(timestamp):
    """Reshape to ``YYYY-MM-DD HH:MM:SS`` without timezone conversion."""
    return _reshape_timestamp(timestamp, "%Y-%m-%d %H:%M:%S", "SQL")
