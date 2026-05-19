"""URL builders + timestamp conversion + archive-days probe for XC catch-up."""

import logging
from datetime import datetime

from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_DURATION_MINUTES = 120
DURATION_BUFFER_MINUTES = 5
MAX_DURATION_MINUTES = 480

PROVIDER_ARCHIVE_CACHE_TTL_SECONDS = 300
MAX_AUTO_PREV_DAYS = 30


def compute_provider_archive_days_capped():
    """Largest `tv_archive_duration` advertised by any XC stream (capped, cached).

    Returns 0 when no XC stream advertises catch-up.
    """
    def _scan():
        from apps.channels.models import Stream

        max_days = 0
        for props in (
            Stream.objects.filter(m3u_account__account_type="XC")
            .exclude(custom_properties__isnull=True)
            .values_list("custom_properties", flat=True)
        ):
            try:
                if not int((props or {}).get("tv_archive", 0) or 0):
                    continue
                value = int((props or {}).get("tv_archive_duration", 0) or 0)
            except (TypeError, ValueError):
                continue
            if value > max_days:
                max_days = value
        return min(max_days, MAX_AUTO_PREV_DAYS)

    return cache.get_or_set(
        "timeshift:provider_archive_days_capped",
        _scan,
        PROVIDER_ARCHIVE_CACHE_TTL_SECONDS,
    )


def get_programme_duration(channel, timestamp_str):
    """Duration in minutes of the EPG programme starting at `timestamp_str`.

    `timestamp_str` is `YYYY-MM-DD:HH-MM` in UTC (passed through from the
    client URL unchanged — no timezone conversion). Falls back to a
    120-minute default if EPG lookup fails.
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


def format_timestamp_as_sql_datetime(timestamp):
    """Reshape `YYYY-MM-DD:HH-MM` to `YYYY-MM-DD HH:MM:SS` without any
    timezone conversion.

    Some XC servers refuse the dash-only shape for archives whose recording
    is still being finalised and only resolve the SQL-datetime shape. This
    function changes only the format — the timestamp value stays in whatever
    zone the caller supplied (typically UTC, since clients derive it from the
    UTC epoch in the EPG data).

    Do NOT add timezone conversion here — that was the root cause of the
    "wrong programme plays" bug (plugin v1.1.4 → v1.2.6 history).
    """
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%d:%H-%M")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.error("Timeshift SQL timestamp reshape failed for %r: %s", timestamp, e)
        return timestamp
