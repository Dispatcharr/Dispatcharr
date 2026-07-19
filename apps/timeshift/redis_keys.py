"""Redis key patterns and logical ids for catch-up (timeshift).

All catch-up state lives under the ``timeshift:`` prefix so live-proxy
janitors and live stats scans never see it.
"""

import re
import secrets

# Logical id: stats channel key segment ``timeshift:channel:{id}:...``
_STATS_CHANNEL_RE = re.compile(r"^(\d+)_(.+)$")


class TimeshiftRedisKeys:
    @staticmethod
    def channel_metadata(channel_id):
        return f"timeshift:channel:{channel_id}:metadata"

    @staticmethod
    def clients(channel_id):
        return f"timeshift:channel:{channel_id}:clients"

    @staticmethod
    def client_metadata(channel_id, client_id):
        return f"timeshift:channel:{channel_id}:clients:{client_id}"

    @staticmethod
    def client_stop(channel_id, client_id):
        return f"timeshift:channel:{channel_id}:client:{client_id}:stop"

    @staticmethod
    def pool(session_id):
        return f"timeshift:pool:{session_id}"

    @staticmethod
    def pool_lock(session_id):
        return f"timeshift:pool:{session_id}:lock"

    @staticmethod
    def pool_superseded(session_id):
        return f"timeshift:pool:{session_id}:superseded"

    @staticmethod
    def pool_scan_pattern():
        return "timeshift:pool:*"

    @staticmethod
    def api_session(session_id):
        return f"timeshift:session:{session_id}"

    @staticmethod
    def stats_grace(stats_channel_id, client_id):
        return f"timeshift:grace:{stats_channel_id}:{client_id}"

    @staticmethod
    def stream_generation(virtual_channel_id, client_id):
        return f"timeshift:stream_gen:{virtual_channel_id}:{client_id}"

    @staticmethod
    def stream_generation_scan_pattern(client_id):
        return f"timeshift:stream_gen:*:{client_id}"

    @staticmethod
    def format_cache(account_id):
        return f"timeshift:format_idx:{account_id}"


def mint_session_id():
    """Opaque per-viewer session id (URL query param and pool key suffix)."""
    return secrets.token_urlsafe(16)


def stats_channel_id(channel_id, session_id):
    """Stable stats/redis channel id for one viewer on a channel."""
    return f"{channel_id}_{session_id}"


def programme_media_id(channel_id, safe_ts):
    """Catch-up position identity (channel + programme timestamp)."""
    return f"{channel_id}_{safe_ts}"


def virtual_channel_id(channel_id, safe_ts, stream_id_value):
    """Programme virtual id for stop keys and stream generation."""
    return f"{channel_id}_{safe_ts}_{stream_id_value}"


def parse_stats_channel_id(stats_channel_id):
    """Split a stats channel id into numeric channel id and session id."""
    match = _STATS_CHANNEL_RE.match(str(stats_channel_id or ""))
    if not match:
        return None
    return {
        "channel_id": int(match.group(1)),
        "session_id": match.group(2),
    }
