import logging
import threading
import time
from collections import namedtuple

from django.db import connection
from django.db.utils import OperationalError

from core.models import EPG_DAYS_LIMIT, CoreSettings
from core.utils import ensure_custom_properties_dict

logger = logging.getLogger(__name__)

# SQLSTATE of a deadlock victim. Matching the code instead of the message keeps
# this working when the server runs with a non-English lc_messages.
_DEADLOCK_SQLSTATE = "40P01"


def _is_deadlock_error(exc):
    return getattr(exc.__cause__, "sqlstate", None) == _DEADLOCK_SQLSTATE


def retry_on_deadlock(fn, *, attempts=3, base_delay=0.02):
    """Retry ``fn`` when PostgreSQL reports a deadlock (SQLSTATE 40P01).

    Only safe in autocommit: a deadlock aborts any open transaction, so an
    outer ``atomic`` block cannot recover by calling ``fn`` again.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except OperationalError as exc:
            if not _is_deadlock_error(exc) or attempt + 1 >= attempts:
                raise
            logger.warning(
                "Deadlock detected, retrying (%s/%s)", attempt + 1, attempts
            )
            time.sleep(base_delay * (2**attempt))

# Bound memory/DB work per chunk for large libraries (20k+ channels).
EPG_LOGO_APPLY_BATCH_SIZE = 500
EPG_LOGO_APPLY_MAX_ERRORS = 100

lock = threading.Lock()
# Dictionary to track usage: {account_id: current_usage}
active_streams_map = {}


def coerce_channel_profile_ids(custom_properties):
    """Ensure channel_profile_ids is a list of ints (UI MultiSelect uses strings).

    ``ensure_custom_properties_dict`` guards against legacy rows where
    custom_properties was stored as a JSON-encoded string rather than an
    object; without it a bad row would raise here instead of degrading
    gracefully.
    """
    props = dict(ensure_custom_properties_dict(custom_properties))
    if "channel_profile_ids" not in props:
        return props
    raw = props["channel_profile_ids"]
    if not isinstance(raw, list):
        raw = [raw] if raw not in (None, "") else []
    ids = []
    for item in raw:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    props["channel_profile_ids"] = ids
    return props


def format_channel_number(value, empty=""):
    """Display formatting for an effective channel_number. Returns int for
    whole-valued floats (so ``123.0`` renders as ``123``), the float as-is
    for fractional values, or ``empty`` when the value is ``None``.
    """
    if value is None:
        return empty
    if value == int(value):
        return int(value)
    return value


EpgWindow = namedtuple("EpgWindow", ["forward_days", "prev_days"])


def _parse_day_count(raw):
    """Return an int, or None when raw is missing, blank, or not an integer."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _explicit_days(params, url_key, user_custom, user_key, upper):
    """Days from the URL, else the user's saved value; None when neither is set.

    A URL value that is present but unreadable counts as 0. A saved 0 is a real
    value, not "unset".
    """
    if url_key in params:
        parsed = _parse_day_count(params.get(url_key))
        return 0 if parsed is None else max(0, min(parsed, upper))
    parsed = _parse_day_count(user_custom.get(user_key))
    return None if parsed is None else max(0, min(parsed, upper))


def resolve_epg_output_window(request, user, *, policy=None):
    """Resolve the forward and past windows for an EPG export.

    ``forward_days`` of 0 means all stored future programmes. ``prev_days`` of
    0 means no programmes that have already ended.

    A URL value wins, then the user's saved value (a saved 0 is explicit, so a
    user whose key is missing inherits and one saved at 0 does not). Otherwise
    the system default applies, for standard XMLTV and XC XMLTV alike.
    """
    if policy is None:
        policy = CoreSettings.get_epg_history_policy()
    params = request.GET
    user_custom = ensure_custom_properties_dict(getattr(user, "custom_properties", None))

    forward_days = _explicit_days(params, "days", user_custom, "epg_days", EPG_DAYS_LIMIT)
    if forward_days is None:
        forward_days = policy.default_days

    prev_days = _explicit_days(
        params, "prev_days", user_custom, "epg_prev_days", policy.max_days
    )
    if prev_days is None:
        prev_days = policy.default_prev_days
    return EpgWindow(forward_days, prev_days)


def is_catchup_enabled(*, user=None):
    """Return whether catch-up / timeshift is allowed.

    When a *user* is supplied, their ``custom_properties.catchup_enabled``
    (default True) is checked first (no DB). System
    ``system_settings.catchup_enabled`` (default True, Redis-cached) can
    disable catch-up for everyone. Both flags are JSON booleans.
    """
    if user is not None:
        props = getattr(user, "custom_properties", None) or {}
        if props.get("catchup_enabled") is False:
            return False

    return CoreSettings.get_catchup_enabled()


def get_channel_catchup_streams(channel):
    """Active catch-up streams for a channel, in ``channelstream`` order.

    Inactive M3U accounts are excluded, matching live dispatch.
    """
    if not getattr(channel, "is_catchup", False):
        return []

    return list(
        channel.streams.filter(is_catchup=True, m3u_account__is_active=True)
        .order_by("channelstream__order")
        .select_related("m3u_account__user_agent")
    )


# Shared by the id-list and account entry points. Writes only rows whose flags
# changed, locking them in id order. FOR NO KEY UPDATE serializes those writes
# without blocking ChannelStream foreign-key inserts on the same channel.
_CATCHUP_ROLLUP_SQL = """
    WITH scope AS (
        {scope}
    ),
    active AS (
        SELECT cs.channel_id, MAX(s.catchup_days) AS max_days
        FROM dispatcharr_channels_channelstream cs
        JOIN dispatcharr_channels_stream s ON s.id = cs.stream_id
        JOIN m3u_m3uaccount a ON a.id = s.m3u_account_id
        WHERE s.is_catchup
          AND a.is_active
          AND cs.channel_id IN (SELECT id FROM scope)
        GROUP BY cs.channel_id
    ),
    changed AS (
        SELECT c.id,
               (active.channel_id IS NOT NULL) AS is_catchup,
               COALESCE(active.max_days, 0) AS catchup_days
        FROM dispatcharr_channels_channel c
        LEFT JOIN active ON active.channel_id = c.id
        WHERE c.id IN (SELECT id FROM scope)
          AND (c.is_catchup IS DISTINCT FROM (active.channel_id IS NOT NULL)
               OR c.catchup_days IS DISTINCT FROM COALESCE(active.max_days, 0))
        ORDER BY c.id
        FOR NO KEY UPDATE OF c
    )
    UPDATE dispatcharr_channels_channel c
    SET is_catchup = changed.is_catchup,
        catchup_days = changed.catchup_days
    FROM changed
    WHERE c.id = changed.id
"""

_CATCHUP_SCOPE_CHANNEL_IDS = "SELECT unnest(%s::bigint[]) AS id"
_CATCHUP_SCOPE_ACCOUNT = """
        SELECT DISTINCT cs.channel_id AS id
        FROM dispatcharr_channels_channelstream cs
        JOIN dispatcharr_channels_stream s ON s.id = cs.stream_id
        WHERE s.m3u_account_id = %s
"""


def _run_catchup_rollup(scope_sql, params):
    sql = _CATCHUP_ROLLUP_SQL.format(scope=scope_sql)

    def _execute():
        with connection.cursor() as cur:
            cur.execute(sql, params)

    if connection.in_atomic_block:
        # Caller's transaction is already aborted on deadlock; cannot retry here.
        _execute()
    else:
        retry_on_deadlock(_execute)


def rollup_catchup_for_channels(channel_ids):
    """Set ``is_catchup`` / ``catchup_days`` from active catch-up streams.

    Channels with no active catch-up stream are reset. Used by the
    ChannelStream signal and by bulk paths that skip ``post_save``.
    """
    ids = list({cid for cid in channel_ids if cid is not None})
    if ids:
        _run_catchup_rollup(_CATCHUP_SCOPE_CHANNEL_IDS, [ids])


def rollup_catchup_for_account(account_id):
    """Roll up catch-up flags for every channel linked to an M3U account.

    Also corrects stale flags after catch-up streams are removed or the account
    is deactivated. Channels with no stream from *account_id* are not touched.
    """
    _run_catchup_rollup(_CATCHUP_SCOPE_ACCOUNT, [account_id])


def increment_stream_count(account):
    with lock:
        current_usage = active_streams_map.get(account.id, 0)
        current_usage += 1
        active_streams_map[account.id] = current_usage
        account.active_streams = current_usage
        account.save(update_fields=['active_streams'])

def decrement_stream_count(account):
    with lock:
        current_usage = active_streams_map.get(account.id, 0)
        if current_usage > 0:
            current_usage -= 1
            if current_usage == 0:
                del active_streams_map[account.id]
            else:
                active_streams_map[account.id] = current_usage
            account.active_streams = current_usage
            account.save(update_fields=['active_streams'])


def auto_apply_epg_logos_enabled(custom_properties):
    """Return whether channel logos should be auto-applied after EPG refresh."""
    return bool((custom_properties or {}).get('auto_apply_epg_logos', False))


def _empty_logo_apply_stats():
    return {
        'updated_count': 0,
        'created_logos_count': 0,
        'error_count': 0,
        'errors': [],
    }


def _merge_logo_apply_stats(accumulated, batch_stats):
    accumulated['updated_count'] += batch_stats['updated_count']
    accumulated['created_logos_count'] += batch_stats['created_logos_count']
    accumulated['error_count'] += batch_stats['error_count']
    remaining = EPG_LOGO_APPLY_MAX_ERRORS - len(accumulated['errors'])
    if remaining > 0:
        accumulated['errors'].extend(batch_stats['errors'][:remaining])
    return accumulated


def apply_logos_from_epg_icon_url(channels):
    """
    Set channel.logo from epg_data.icon_url for the given channels.

    Expects channels to be pre-filtered with select_related('epg_data', 'logo').
    Uses bulk logo lookup/create and a single channel bulk_update for efficiency.
    """
    from .models import Channel, Logo

    work = []
    url_to_meta = {}

    for channel in channels:
        if not channel.epg_data:
            continue
        icon_url = (channel.epg_data.icon_url or '').strip()
        if not icon_url:
            continue
        if channel.logo and channel.logo.url == icon_url:
            continue
        work.append((channel, icon_url))
        if icon_url not in url_to_meta:
            url_to_meta[icon_url] = (
                channel.epg_data.name,
                channel.epg_data.tvg_id,
            )

    if not work:
        return _empty_logo_apply_stats()

    unique_urls = list(url_to_meta.keys())
    logo_by_url = {
        logo.url: logo
        for logo in Logo.objects.filter(url__in=unique_urls)
    }

    missing_urls = [url for url in unique_urls if url not in logo_by_url]
    created_logos_count = 0
    if missing_urls:
        logos_to_create = [
            Logo(
                name=(url_to_meta[url][0] or f"Logo for {url_to_meta[url][1]}"),
                url=url,
            )
            for url in missing_urls
        ]
        created_logos_count = len(logos_to_create)
        Logo.objects.bulk_create(logos_to_create, ignore_conflicts=True)
        for logo in Logo.objects.filter(url__in=unique_urls):
            logo_by_url[logo.url] = logo

    channels_to_update = []
    errors = []
    for channel, icon_url in work:
        logo = logo_by_url.get(icon_url)
        if not logo:
            errors.append(f"Channel {channel.id}: Logo not found for {icon_url}")
            continue
        if channel.logo_id != logo.id:
            channel.logo = logo
            channels_to_update.append(channel)

    if channels_to_update:
        Channel.objects.bulk_update(channels_to_update, ['logo'], batch_size=500)

    return {
        'updated_count': len(channels_to_update),
        'created_logos_count': created_logos_count,
        'error_count': len(errors),
        'errors': errors,
    }


def channels_with_epg_icon_queryset(*, epg_source=None, epg_source_id=None):
    """Channels mapped to a source that have a non-empty EPG icon URL."""
    from .models import Channel

    qs = Channel.objects.filter(epg_data__isnull=False)
    if epg_source is not None:
        qs = qs.filter(epg_data__epg_source=epg_source)
    elif epg_source_id is not None:
        qs = qs.filter(epg_data__epg_source_id=epg_source_id)
    else:
        raise ValueError("epg_source or epg_source_id is required")

    return qs.exclude(
        epg_data__icon_url__isnull=True,
    ).exclude(
        epg_data__icon_url='',
    )


def apply_logos_from_epg_queryset(channels_qs, *, batch_size=EPG_LOGO_APPLY_BATCH_SIZE):
    """
    Apply logos for a potentially large queryset without loading every row at once.
    Streams channel IDs from the database and processes fixed-size chunks.
    """
    from .models import Channel

    stats = _empty_logo_apply_stats()
    batch_ids = []

    id_stream = channels_qs.order_by('id').values_list('id', flat=True).iterator(
        chunk_size=batch_size,
    )
    for channel_id in id_stream:
        batch_ids.append(channel_id)
        if len(batch_ids) >= batch_size:
            batch = Channel.objects.filter(
                id__in=batch_ids,
            ).select_related('epg_data', 'logo')
            _merge_logo_apply_stats(stats, apply_logos_from_epg_icon_url(batch))
            batch_ids = []

    if batch_ids:
        batch = Channel.objects.filter(
            id__in=batch_ids,
        ).select_related('epg_data', 'logo')
        _merge_logo_apply_stats(stats, apply_logos_from_epg_icon_url(batch))

    return stats


def apply_logos_from_epg_for_source(epg_source, *, batch_size=EPG_LOGO_APPLY_BATCH_SIZE):
    """Apply EPG icon URLs to all channels mapped to the given EPG source."""
    channels_qs = channels_with_epg_icon_queryset(epg_source=epg_source)
    return apply_logos_from_epg_queryset(channels_qs, batch_size=batch_size)


def maybe_auto_apply_epg_logos(epg_source):
    """Auto-apply logos after refresh when enabled on the source. Non-fatal on error."""
    if not auto_apply_epg_logos_enabled(epg_source.custom_properties):
        return None
    try:
        stats = apply_logos_from_epg_for_source(epg_source)
        if stats['updated_count'] or stats['created_logos_count']:
            logger.info(
                "Auto-applied EPG logos for source %s: updated %s channels, "
                "created %s logos.",
                epg_source.name,
                stats['updated_count'],
                stats['created_logos_count'],
            )
        else:
            logger.info(
                "Auto-apply EPG logos for source %s: all matched channels already current.",
                epg_source.name,
            )
        return stats
    except Exception as logo_error:
        logger.warning(
            "EPG logo auto-apply failed for source %s (non-fatal): %s",
            epg_source.name,
            logo_error,
            exc_info=True,
        )
        return None
