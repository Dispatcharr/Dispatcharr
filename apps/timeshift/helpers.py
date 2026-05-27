"""URL builders + timestamp conversion + archive-days probe for XC catch-up."""

import logging
from datetime import datetime, timezone

from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_DURATION_MINUTES = 120
DURATION_BUFFER_MINUTES = 5
MAX_DURATION_MINUTES = 480

PROVIDER_ARCHIVE_CACHE_TTL_SECONDS = 300
MAX_AUTO_PREV_DAYS = 30


def compute_provider_archive_days_capped():
    """Largest `catchup_days` across all XC streams with catch-up (capped, cached).

    Uses the denormalized ``Stream.catchup_days`` field instead of iterating
    JSON blobs — one aggregate query, no Python loop.
    Returns 0 when no XC stream advertises catch-up.
    """
    def _scan():
        from apps.channels.models import Stream
        from django.db.models import Max

        result = (
            Stream.objects.filter(
                m3u_account__account_type="XC",
                is_catchup=True,
            )
            .aggregate(max_days=Max("catchup_days"))
        )
        return min(result["max_days"] or 0, MAX_AUTO_PREV_DAYS)

    return cache.get_or_set(
        "timeshift:provider_archive_days_capped",
        _scan,
        PROVIDER_ARCHIVE_CACHE_TTL_SECONDS,
    )


def _parse_timestamp(timestamp_str):
    """Parse a timestamp string into a datetime, accepting colon-dash or underscore shapes.

    Accepts: ``YYYY-MM-DD:HH-MM`` (iPlayTV/TiviMate native),
             ``YYYY-MM-DD_HH-MM`` (XC underscore shape).
    Returns None on failure.
    """
    for fmt in ("%Y-%m-%d:%H-%M", "%Y-%m-%d_%H-%M"):
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue
    return None


def get_programme_duration(channel, timestamp_str):
    """Duration in minutes of the EPG programme starting at `timestamp_str`.

    `timestamp_str` is `YYYY-MM-DD:HH-MM` or `YYYY-MM-DD_HH-MM` in UTC
    (passed through from the client URL unchanged — no timezone conversion).
    Falls back to a 120-minute default if EPG lookup fails.
    """
    try:
        dt = _parse_timestamp(timestamp_str)
        if dt is None:
            return DEFAULT_DURATION_MINUTES
        # EPG start_time/end_time are timezone-aware (USE_TZ=True), so the
        # parsed datetime must also be aware to avoid a TypeError in the ORM
        # filter.  The timestamp is already in UTC (derived from the EPG epoch).
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


def build_timeshift_url_format_a(m3u_account, stream_id, timestamp, duration_minutes):
    """Format A: `/streaming/timeshift.php?username=&password=&stream=&start=&duration=`."""
    return (
        f"{m3u_account.server_url.rstrip('/')}/streaming/timeshift.php"
        f"?username={m3u_account.username}"
        f"&password={m3u_account.password}"
        f"&stream={stream_id}"
        f"&start={timestamp}"
        f"&duration={duration_minutes}"
    )


def build_timeshift_url_format_b(m3u_account, stream_id, timestamp, duration_minutes):
    """Format B: `/timeshift/{user}/{pass}/{duration}/{timestamp}/{stream_id}.ts`."""
    return (
        f"{m3u_account.server_url.rstrip('/')}/timeshift"
        f"/{m3u_account.username}"
        f"/{m3u_account.password}"
        f"/{duration_minutes}"
        f"/{timestamp}"
        f"/{stream_id}.ts"
    )


def format_timestamp_as_underscore(timestamp):
    """Reshape ``YYYY-MM-DD:HH-MM`` to ``YYYY-MM-DD_HH-MM`` without any
    timezone conversion.

    Many XC servers use the underscore shape as their
    canonical catch-up URL format, especially for recently-indexed archives
    (< 5–6 hours old). The colon-dash and SQL shapes only resolve against the
    legacy catch-up parser, which covers archives older than roughly half a day.

    Do NOT add timezone conversion here — see ``format_timestamp_as_sql_datetime``
    docstring for the full history.
    """
    dt = _parse_timestamp(timestamp)
    if dt is None:
        logger.error("Timeshift underscore reshape failed for %r: unrecognised format", timestamp)
        return timestamp
    return dt.strftime("%Y-%m-%d_%H-%M")


def format_timestamp_as_sql_datetime(timestamp):
    """Reshape ``YYYY-MM-DD:HH-MM`` (or underscore variant) to ``YYYY-MM-DD HH:MM:SS``
    without any timezone conversion.

    Some XC servers refuse the dash-only shape for archives whose recording
    is still being finalised and only resolve the SQL-datetime shape. This
    function changes only the format — the timestamp value stays in whatever
    zone the caller supplied (typically UTC, since clients derive it from the
    UTC epoch in the EPG data).

    Do NOT add timezone conversion here — that was the root cause of the
    "wrong programme plays" bug (plugin v1.1.4 → v1.2.6 history).
    """
    dt = _parse_timestamp(timestamp)
    if dt is None:
        logger.error("Timeshift SQL timestamp reshape failed for %r: unrecognised format", timestamp)
        return timestamp
    return dt.strftime("%Y-%m-%d %H:%M:%S")
