"""URL builders + timestamp conversion + archive-days probe for XC catch-up."""

import logging
from collections import namedtuple
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Resolved upstream credentials for one catch-up attempt. Produced from
#: ``get_transformed_credentials(account, reserved_profile)`` so the URL is
#: built with the credentials of the profile whose pool slot was actually
#: reserved — alternate profiles express different logins as URL regex
#: transforms, and using the raw account fields for them would desynchronize
#: pool accounting from real upstream usage.
TimeshiftCredentials = namedtuple(
    "TimeshiftCredentials", ("server_url", "username", "password")
)

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


def parse_catchup_timestamp(timestamp_str):
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


def convert_timestamp_to_provider_tz(timestamp_str, provider_tz_name):
    """Convert a UTC catch-up timestamp to the serving provider's local zone.

    The XC API surface is strictly UTC, so the client builds the catch-up URL
    from a UTC wall-clock. Real XC providers, however, index their archive in
    their OWN local zone (the ``server_info.timezone`` they report on auth). This
    shifts the UTC instant into that zone so the upstream seek lands on the right
    hour — empirically a provider reading ``17-00`` as its local time returns the
    17:00-local programme, not 17:00 UTC.

    ``timestamp_str`` is ``YYYY-MM-DD:HH-MM`` or ``YYYY-MM-DD_HH-MM`` (UTC).
    ``provider_tz_name`` is an IANA name (e.g. ``Europe/Brussels``). When it is
    falsy, ``"UTC"``, or unknown, the timestamp is returned unchanged — providers
    that index in UTC (or whose zone we don't know) need no shift. Returns the
    colon-dash shape ``YYYY-MM-DD:HH-MM`` (the canonical PATH shape). On any parse
    failure the input is returned unchanged.
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
            "Timeshift: unknown provider timezone %r — no conversion applied",
            provider_tz_name,
        )
        return timestamp_str
    # datetime.timezone.utc (not ZoneInfo("UTC")) for the source side — immune to
    # a mis-set host /etc/timezone. astimezone() is DST-correct for the date.
    local_dt = dt.replace(tzinfo=timezone.utc).astimezone(target)
    return local_dt.strftime("%Y-%m-%d:%H-%M")


def get_programme_duration(channel, timestamp_str):
    """Duration in minutes of the EPG programme starting at `timestamp_str`.

    `timestamp_str` is `YYYY-MM-DD:HH-MM` or `YYYY-MM-DD_HH-MM` in UTC — the
    client's original value, built from the strictly-UTC EPG output. The
    UTC→provider-zone conversion happens only for the upstream URL (in
    ``timeshift_proxy``), never for this EPG lookup: programmes are stored in
    UTC, so the lookup must stay in UTC too.
    Falls back to a 120-minute default if EPG lookup fails.
    """
    try:
        dt = parse_catchup_timestamp(timestamp_str)
        if dt is None:
            return DEFAULT_DURATION_MINUTES
        # EPG start_time/end_time are timezone-aware (USE_TZ=True), so the
        # parsed datetime must also be aware to avoid a TypeError in the ORM
        # filter.
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
    """Format A: `/streaming/timeshift.php?username=&password=&stream=&start=&duration=`."""
    # Credentials are URL-encoded: a `&`, `/` or `#` in the password would
    # otherwise corrupt the URL structure.
    return (
        f"{creds.server_url.rstrip('/')}/streaming/timeshift.php"
        f"?username={quote(str(creds.username), safe='')}"
        f"&password={quote(str(creds.password), safe='')}"
        f"&stream={stream_id}"
        f"&start={timestamp}"
        f"&duration={duration_minutes}"
    )


def build_timeshift_url_format_b(creds, stream_id, timestamp, duration_minutes):
    """Format B: `/timeshift/{user}/{pass}/{duration}/{timestamp}/{stream_id}.ts`."""
    return (
        f"{creds.server_url.rstrip('/')}/timeshift"
        f"/{quote(str(creds.username), safe='')}"
        f"/{quote(str(creds.password), safe='')}"
        f"/{duration_minutes}"
        f"/{timestamp}"
        f"/{stream_id}.ts"
    )


def build_timeshift_candidate_urls(creds, stream_id, timestamp, duration_minutes):
    """Ordered upstream catch-up candidates — PATH form first.

    Two URL layouts exist on XC servers and they do NOT behave the same:

    • Format B — PATH layout: ``/timeshift/{user}/{pass}/{dur}/{START}/{id}.ts``
      The canonical XC catch-up form (what TiviMate emits natively). It actually
      SEEKS the requested archive instant. Tried FIRST.
    • Format A — QUERY layout: ``/streaming/timeshift.php?...&start={START}``
      A non-standard variant. Some providers implement it incorrectly and return
      the LIVE stream (HTTP 200, ignoring ``start``) — indistinguishable from a
      real archive at the byte level, so it would masquerade as a successful
      catch-up. Kept only as a fallback for providers that expose ONLY
      timeshift.php, and therefore tried AFTER every PATH candidate.

    Within each layout we vary the timestamp shape, because different servers'
    parsers accept different ones (colon-dash is the canonical PATH shape;
    underscore and SQL-datetime cover other servers' parsers). No timezone
    conversion happens here — the caller (``timeshift_proxy``) has already
    converted the value to the serving provider's zone; only the *shape* varies.
    """
    underscore_ts = format_timestamp_as_underscore(timestamp)
    sql_ts = format_timestamp_as_sql_datetime(timestamp)
    return [
        # PATH form first — it seeks the archive correctly.
        build_timeshift_url_format_b(creds, stream_id, timestamp, duration_minutes),
        build_timeshift_url_format_b(creds, stream_id, underscore_ts, duration_minutes),
        # QUERY form fallback — may return LIVE on some providers (see above).
        build_timeshift_url_format_a(creds, stream_id, underscore_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, sql_ts, duration_minutes),
        build_timeshift_url_format_a(creds, stream_id, timestamp, duration_minutes),
    ]


def format_timestamp_as_underscore(timestamp):
    """Reshape ``YYYY-MM-DD:HH-MM`` to ``YYYY-MM-DD_HH-MM`` without any
    timezone conversion.

    Many XC servers use the underscore shape as their
    canonical catch-up URL format, especially for recently-indexed archives
    (< 5–6 hours old). The colon-dash and SQL shapes only resolve against the
    legacy catch-up parser, which covers archives older than roughly half a day.

    Shape-only, by design: the single timezone conversion in the chain happens
    upstream in ``timeshift_proxy`` (UTC → serving provider's zone), so the
    value received here is already in the provider's zone.
    """
    dt = parse_catchup_timestamp(timestamp)
    if dt is None:
        logger.error("Timeshift underscore reshape failed for %r: unrecognised format", timestamp)
        return timestamp
    return dt.strftime("%Y-%m-%d_%H-%M")


def format_timestamp_as_sql_datetime(timestamp):
    """Reshape ``YYYY-MM-DD:HH-MM`` (or underscore variant) to ``YYYY-MM-DD HH:MM:SS``
    without any timezone conversion.

    Some XC servers refuse the dash-only shape for archives whose recording
    is still being finalised and only resolve the SQL-datetime shape.

    Shape-only, by design: the single timezone conversion in the chain happens
    upstream in ``timeshift_proxy`` (UTC → serving provider's zone via
    ``convert_timestamp_to_provider_tz``), so the value received here is
    already in the provider's zone — this function must not convert again.
    """
    dt = parse_catchup_timestamp(timestamp)
    if dt is None:
        logger.error("Timeshift SQL timestamp reshape failed for %r: unrecognised format", timestamp)
        return timestamp
    return dt.strftime("%Y-%m-%d %H:%M:%S")
