import logging
import threading

logger = logging.getLogger(__name__)

# Bound memory/DB work per chunk for large libraries (20k+ channels).
EPG_LOGO_APPLY_BATCH_SIZE = 500
EPG_LOGO_APPLY_MAX_ERRORS = 100

lock = threading.Lock()
# Dictionary to track usage: {account_id: current_usage}
active_streams_map = {}


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


def get_channel_catchup_streams(channel):
    """Ordered catch-up streams for a Channel (empty list if unavailable).

    Returned in ``channelstream__order`` so the timeshift proxy can fail over:
    it tries each stream's provider in turn until one serves the archive —
    mirroring how live playback walks a channel's stream list. Streams from
    disabled M3U accounts are excluded, same as live dispatch.
    """
    if not getattr(channel, "is_catchup", False):
        return []

    return list(
        channel.streams.filter(is_catchup=True, m3u_account__is_active=True)
        .order_by("channelstream__order")
        .select_related("m3u_account")
    )


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
