import threading

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


def resolve_channel_by_provider_stream_id(provider_stream_id):
    """Find a Channel + Stream by the XC provider's stream_id.

    XC clients address channels via the provider's `stream_id` (stored in
    `Stream.custom_properties["stream_id"]`), not Dispatcharr's internal
    `Channel.id`. Returns `(Channel, Stream)` on hit, `(None, None)` on miss.
    """
    from apps.channels.models import Stream

    stream = (
        Stream.objects.filter(
            custom_properties__stream_id=str(provider_stream_id),
            m3u_account__account_type="XC",
        )
        .select_related("m3u_account")
        .first()
    )
    if stream is None:
        return None, None
    channel = stream.channels.first()
    if channel is None:
        return None, None
    return channel, stream


def get_channel_catchup_info(channel):
    """Return catch-up info for a Channel, or None if no stream has tv_archive.

    Walks `channel.streams` in `channelstream__order`, returns a dict for the
    first archive-enabled stream: `{stream, props, provider_stream_id,
    tv_archive_duration}`. `tv_archive` may be stored as 1, "1", True or
    "True" depending on the M3U importer that wrote it.
    """
    for stream in channel.streams.order_by("channelstream__order"):
        props = stream.custom_properties or {}
        if str(props.get("tv_archive")) not in ("1", "True"):
            continue
        provider_stream_id = props.get("stream_id")
        if not provider_stream_id:
            continue
        try:
            archive_days = int(props.get("tv_archive_duration", 7) or 7)
        except (TypeError, ValueError):
            archive_days = 7
        return {
            "stream": stream,
            "props": props,
            "provider_stream_id": str(provider_stream_id),
            "tv_archive_duration": archive_days,
        }
    return None


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
