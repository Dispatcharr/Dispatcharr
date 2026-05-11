import threading

lock = threading.Lock()
# Dictionary to track usage: {account_id: current_usage}
active_streams_map = {}


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


def _is_archive_enabled(props):
    """Truthy check for tv_archive flag — tolerates 1, "1", True, "True"."""
    if not props:
        return False
    return str(props.get("tv_archive")) in ("1", "True")


def get_channel_catchup_info(channel):
    """Return catch-up info for a Channel, or None if no stream has tv_archive.

    Walks `channel.streams` in `channelstream__order`, returning the first
    stream whose `custom_properties.tv_archive` is set. Shape:
        {
            "stream": Stream,
            "props": dict (the stream's custom_properties),
            "provider_stream_id": str,
            "tv_archive_duration": int (days, defaults to 7),
        }
    """
    for stream in channel.streams.order_by("channelstream__order"):
        props = stream.custom_properties or {}
        if not _is_archive_enabled(props):
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
