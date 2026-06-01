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


def get_channel_catchup_info(channel):
    """Return catch-up info for a Channel, or None if catch-up is unavailable.

    Uses the denormalized ``channel.is_catchup`` and
    ``channel.catchup_provider_stream_id`` fields for a zero-cost gate,
    then fetches the first catch-up stream (for its ``m3u_account``) with a
    targeted filter instead of iterating all streams.
    """
    if not getattr(channel, "is_catchup", False) or not channel.catchup_provider_stream_id:
        return None

    stream = (
        channel.streams.filter(is_catchup=True)
        .select_related("m3u_account")
        .first()
    )
    if stream is None:
        return None

    return {
        "stream": stream,
        "props": stream.custom_properties or {},
        "provider_stream_id": str(channel.catchup_provider_stream_id),
        "tv_archive_duration": channel.catchup_days or 7,
    }


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
