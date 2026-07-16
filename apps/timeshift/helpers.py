"""URL builders and timestamp helpers for XC catch-up."""

import logging
import math
import re
import time
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from apps.timeshift.redis_keys import TimeshiftRedisKeys

logger = logging.getLogger(__name__)

# Credentials for the profile whose pool slot was reserved (not raw account fields).
TimeshiftCredentials = namedtuple(
    "TimeshiftCredentials", ("server_url", "username", "password")
)

DEFAULT_DURATION_MINUTES = 120
# Extra minutes added to client/EPG programme length when asking the provider.
# IPTV archives commonly lag live by about 30 seconds to 2 minutes, so a bare
# programme length tends to include the previous show's tail and clip the end.
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
        Programme length plus ``DURATION_BUFFER_MINUTES`` (provider archive lag),
        capped at ``MAX_DURATION_MINUTES``, or ``DEFAULT_DURATION_MINUTES`` when
        EPG lookup fails.
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


def client_duration_to_window(value):
    """Convert a client-supplied programme length (minutes) to an archive window.

    Args:
        value: Raw client hint (str/int). PATH XC duration segment, QUERY
            ``duration=``, or the native session's stored ``duration``.

    Returns:
        Minutes to request from the provider (client length +
        ``DURATION_BUFFER_MINUTES``, capped), or ``None`` when the hint is
        missing or not a usable positive integer.

    The buffer matches the EPG path: clients usually send exact guide length
    (for example ``.../60/.../123.ts`` for a 60-minute show), but provider
    archives lag live, so requesting that bare length clips the end.
    """
    if value is None:
        return None
    try:
        minutes = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    return min(minutes + DURATION_BUFFER_MINUTES, MAX_DURATION_MINUTES)


def resolve_catchup_duration(channel, timestamp_str, client_hint=None):
    """Pick the catch-up archive window in minutes.

    Preference order: a sane client-supplied hint, then the EPG programme
    length, then ``DEFAULT_DURATION_MINUTES``.
    """
    window = client_duration_to_window(client_hint)
    if window is not None:
        return window
    return get_programme_duration(channel, timestamp_str)


def get_programme_info(channel, timestamp_str, position_secs=None):
    """Return EPG metadata for the programme airing at *timestamp_str*.

    When ``position_secs`` is set (playhead within the archive, relative to the
    programme that contains ``timestamp_str``), and that playhead is at or past
    the programme's end, resolve the guide entry at the playhead instead. That
    keeps catch-up stats cards on the show the viewer has actually reached when
    they keep watching into the provider buffer / next programme.
    """
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

        if position_secs is not None:
            try:
                offset = max(0.0, float(position_secs))
            except (TypeError, ValueError):
                offset = 0.0
            playhead = programme.start_time + timedelta(seconds=offset)
            if playhead >= programme.end_time:
                advanced = channel.epg_data.programs.filter(
                    start_time__lte=playhead, end_time__gt=playhead
                ).first()
                if advanced is not None:
                    programme = advanced

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
    ``programme_start``. Optional ``position_secs`` (playhead within the
    archive, relative to the programme containing ``programme_start``)
    advances the returned programme when past that show's end. When omitted,
    an estimate is taken from the session's Redis stats metadata when present.
    """
    from apps.channels.models import Channel
    from apps.timeshift.stats import (
        _client_paused,
        _decode_hash,
        compute_playback_position_secs,
        find_stats_channel_for_session,
    )
    from core.utils import RedisClient

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

    redis_client = RedisClient.get_client()
    results = []
    for session in valid:
        channel_uuid = str(session["channel_uuid"])
        programme_start = session["programme_start"]
        channel = channels_by_uuid.get(channel_uuid)
        position_secs = session.get("position_secs")
        if position_secs is not None:
            try:
                position_secs = float(position_secs)
            except (TypeError, ValueError):
                position_secs = None

        # Resolve the guide entry for the URL first so Redis playhead math has
        # an EPG start; then re-resolve with position to advance past the end.
        info = get_programme_info(channel, programme_start) if channel else None
        if position_secs is None and info is not None and redis_client is not None:
            position_secs = _position_secs_from_stats(
                redis_client,
                session_id=session["session_id"],
                programme_start=programme_start,
                epg_start_iso=info["start_time"],
                compute_playback_position_secs=compute_playback_position_secs,
                find_stats_channel_for_session=find_stats_channel_for_session,
                client_paused=_client_paused,
                decode_hash=_decode_hash,
            )
        if channel is not None and position_secs is not None:
            advanced = get_programme_info(
                channel, programme_start, position_secs=position_secs,
            )
            if advanced is not None:
                info = advanced

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


def _position_secs_from_stats(
    redis_client,
    *,
    session_id,
    programme_start,
    epg_start_iso,
    compute_playback_position_secs,
    find_stats_channel_for_session,
    client_paused,
    decode_hash,
):
    """Best-effort uncapped playhead from timeshift stats Redis metadata."""
    try:
        stats_channel_id = find_stats_channel_for_session(redis_client, session_id)
        if not stats_channel_id:
            return None
        client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, session_id)
        client_data = decode_hash(redis_client.hgetall(client_key))
        if not client_data:
            return None
        playback_base_raw = client_data.get("playback_base_secs")
        playback_base_secs = None
        if playback_base_raw not in (None, ""):
            try:
                playback_base_secs = float(playback_base_raw)
            except (TypeError, ValueError):
                playback_base_secs = None
        return compute_playback_position_secs(
            programme_start,
            epg_start_iso,
            client_data.get("position_anchor_at"),
            time.time(),
            duration_secs=None,
            playback_base_secs=playback_base_secs,
            paused=client_paused(client_data.get("paused")),
        )
    except Exception:
        return None


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


def programme_age_days(timestamp_str, *, now=None):
    """Archive depth in whole days needed to cover a catch-up start timestamp.

    Returns:
        ``None`` if the timestamp cannot be parsed, ``0`` if start is at/after
        *now*, otherwise ``ceil(elapsed / 86400)`` (at least 1).
    """
    dt = parse_catchup_timestamp(timestamp_str)
    if dt is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    elif getattr(now, "tzinfo", None) is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    elapsed = (now - dt).total_seconds()
    if elapsed <= 0:
        return 0
    return max(1, math.ceil(elapsed / 86400.0))


def order_catchup_streams_for_timestamp(streams, timestamp_str, *, now=None):
    """Prefer streams whose ``catchup_days`` cover the programme age.

    Relative channel order is preserved within the preferred and fallback
    groups. Streams with unknown/zero ``catchup_days`` stay preferred so
    incomplete provider metadata does not skip a possible server. Unparseable
    timestamps leave the input order unchanged.
    """
    age = programme_age_days(timestamp_str, now=now)
    if age is None:
        return list(streams)

    preferred = []
    fallback = []
    for stream in streams:
        raw = getattr(stream, "catchup_days", None)
        try:
            days = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            days = 0
        if days <= 0 or days >= age:
            preferred.append(stream)
        else:
            fallback.append(stream)
    return preferred + fallback
