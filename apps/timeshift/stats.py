"""Build catch-up (timeshift) connection stats for the admin UI."""

import logging
import re
import time

from django.db import close_old_connections

from datetime import timezone as dt_timezone

from apps.channels.models import Channel
from apps.m3u.models import M3UAccountProfile
from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.timeshift.redis_keys import TimeshiftRedisKeys, parse_stats_channel_id
from apps.timeshift.helpers import parse_catchup_timestamp
from core.utils import RedisClient

logger = logging.getLogger(__name__)

# Shared with views near-EOF classification (common ~1.88MB duration probes).
EOF_PROBE_TAIL_BYTES = 2_097_152

_STREAM_STATS_TO_METADATA = {
    "video_codec": ChannelMetadataField.VIDEO_CODEC,
    "resolution": ChannelMetadataField.RESOLUTION,
    "source_fps": ChannelMetadataField.SOURCE_FPS,
    "pixel_format": ChannelMetadataField.PIXEL_FORMAT,
    "video_bitrate": ChannelMetadataField.VIDEO_BITRATE,
    "audio_codec": ChannelMetadataField.AUDIO_CODEC,
    "sample_rate": ChannelMetadataField.SAMPLE_RATE,
    "audio_channels": ChannelMetadataField.AUDIO_CHANNELS,
    "audio_bitrate": ChannelMetadataField.AUDIO_BITRATE,
    "stream_type": ChannelMetadataField.STREAM_TYPE,
}

# Redis metadata → stats API / UI display keys (matches live stats cards).
_METADATA_TO_DISPLAY = {
    ChannelMetadataField.RESOLUTION: "resolution",
    ChannelMetadataField.SOURCE_FPS: "source_fps",
    ChannelMetadataField.VIDEO_CODEC: "video_codec",
    ChannelMetadataField.AUDIO_CODEC: "audio_codec",
    ChannelMetadataField.AUDIO_CHANNELS: "audio_channels",
    ChannelMetadataField.STREAM_TYPE: "stream_type",
}


def stream_stats_to_metadata_fields(stream_stats):
    """Map a ``Stream.stream_stats`` dict to Redis channel metadata fields."""
    if not stream_stats:
        return {}
    out = {}
    for src_key, field_name in _STREAM_STATS_TO_METADATA.items():
        value = stream_stats.get(src_key)
        if value is not None and value != "":
            out[field_name] = str(value)
    if out:
        out[ChannelMetadataField.STREAM_INFO_UPDATED] = str(time.time())
    return out


def stream_info_from_metadata(metadata):
    """Extract display-oriented stream stats from Redis channel metadata."""
    if not metadata:
        return {}
    out = {}
    for field_name, display_key in _METADATA_TO_DISPLAY.items():
        value = metadata.get(field_name)
        if value is not None and value != "":
            out[display_key] = _decode_value(value)
    return out


def seed_stream_stats_metadata(
    redis_client,
    metadata_key,
    metadata_payload,
    *,
    stats_stream_id,
    stream_stats=None,
):
    """Copy stream stats into catch-up Redis metadata when the upstream stream changes.

    ``stream_stats`` should come from the already-loaded ``catchup_stream`` row
    when available. A DB lookup is only attempted when the pool reuses a session
    whose metadata was evicted and no in-memory stats were passed.
    """
    if stats_stream_id is None or redis_client is None:
        return
    sid = str(stats_stream_id)
    try:
        existing = redis_client.hget(metadata_key, ChannelMetadataField.STREAM_ID)
        if isinstance(existing, bytes):
            existing = existing.decode()
    except Exception:
        existing = None

    if existing == sid:
        return

    stats = stream_stats
    if not stats:
        try:
            from apps.channels.models import Stream

            row = Stream.objects.filter(id=int(sid)).values("stream_stats").first()
            stats = row.get("stream_stats") if row else None
        except Exception as exc:
            logger.debug("Timeshift stream stats lookup failed for %s: %s", sid, exc)
            stats = None

    fields = stream_stats_to_metadata_fields(stats)
    if not fields:
        return
    metadata_payload.update(fields)
    metadata_payload[ChannelMetadataField.STREAM_ID] = sid


def _decode_value(value):
    if isinstance(value, bytes):
        return value.decode()
    return value


def _decode_hash(data):
    if not data:
        return {}
    return {_decode_value(k): _decode_value(v) for k, v in data.items()}


def compute_playback_base_from_byte_range(range_start, content_length, duration_secs):
    """Map a byte offset into an approximate programme position in seconds."""
    if range_start is None or range_start <= 0:
        return None
    try:
        range_start = int(range_start)
        content_length = int(content_length)
        duration_secs = float(duration_secs)
    except (TypeError, ValueError):
        return None
    if content_length <= 0 or duration_secs <= 0:
        return None
    ratio = min(1.0, max(0.0, range_start / content_length))
    return ratio * duration_secs


def resolve_stats_playback_fields(
    *,
    timestamp_utc,
    existing_programme_start,
    existing_position_anchor,
    existing_playback_base,
    range_start,
    representation_length,
    programme_duration_secs,
    now,
):
    """Return ``(playback_base_secs, position_anchor_at)`` for stats registration.

    ``playback_base_secs`` is set for byte-range seeks (VLC); ``None`` means
    derive position from the URL programme timestamp instead.
    """
    if isinstance(existing_programme_start, bytes):
        existing_programme_start = existing_programme_start.decode()
    if isinstance(existing_position_anchor, bytes):
        existing_position_anchor = existing_position_anchor.decode()
    if isinstance(existing_playback_base, bytes):
        existing_playback_base = existing_playback_base.decode()

    programme_changed = (
        existing_programme_start is not None
        and existing_programme_start != timestamp_utc
    )

    # Near-EOF duration probes must not reanchor stats to end-of-file.
    if (
        range_start is not None
        and representation_length is not None
        and not programme_changed
    ):
        try:
            start = int(range_start)
            total = int(representation_length)
        except (TypeError, ValueError):
            start = None
            total = None
        if start is not None and total is not None and total > 0:
            if start >= max(0, total - EOF_PROBE_TAIL_BYTES):
                try:
                    keep_base = (
                        float(existing_playback_base)
                        if existing_playback_base is not None
                        else None
                    )
                except (TypeError, ValueError):
                    keep_base = None
                keep_anchor = existing_position_anchor or now
                return keep_base, keep_anchor

    byte_base = compute_playback_base_from_byte_range(
        range_start, representation_length, programme_duration_secs,
    )

    if programme_changed:
        return None, now

    if byte_base is not None:
        return byte_base, now

    if range_start == 0:
        return None, now

    # Plain GET (no Range): providers restart from byte 0 on reconnect.
    if range_start is None:
        return None, now

    return None, now


def compute_playback_position_secs(
    programme_start_url,
    epg_start_iso,
    position_anchor_at,
    current_time,
    duration_secs=None,
    playback_base_secs=None,
    paused=False,
):
    """Best-effort catch-up play position in seconds within the programme.

    IPTV clients seek by opening a new catch-up URL at the target time, so the
    URL timestamp (``programme_start_url``) is the requested position. Offset it
    from the programme's EPG start, then advance by wall-clock since the current
    stream opened (``position_anchor_at``).

    Native players (VLC) often keep the programme URL fixed and seek via
    ``Range: bytes=…``; in that case ``playback_base_secs`` carries the mapped
    position at the anchor instead of the URL timestamp offset.

    When ``paused`` is true, wall-clock since the anchor is ignored so admin
    stats stay frozen at the last reported playhead.
    """
    elapsed_since_anchor = 0.0
    if not paused and position_anchor_at:
        try:
            elapsed_since_anchor = max(0.0, current_time - float(position_anchor_at))
        except (TypeError, ValueError):
            elapsed_since_anchor = 0.0

    if playback_base_secs is not None:
        try:
            position = float(playback_base_secs) + elapsed_since_anchor
        except (TypeError, ValueError):
            position = elapsed_since_anchor
    else:
        if not programme_start_url or not epg_start_iso:
            return None
        url_dt = parse_catchup_timestamp(programme_start_url)
        if url_dt is None:
            return None
        try:
            from datetime import datetime

            epg_dt = datetime.fromisoformat(epg_start_iso)
        except (TypeError, ValueError):
            return None
        if epg_dt.tzinfo is not None:
            epg_dt = epg_dt.astimezone(dt_timezone.utc).replace(tzinfo=None)
        url_offset = (url_dt - epg_dt).total_seconds()
        position = url_offset + elapsed_since_anchor

    if position < 0:
        position = 0.0
    if duration_secs:
        position = min(position, float(duration_secs))
    return position


def find_stats_channel_for_session(redis_client, session_id):
    """Locate the Redis stats channel id for a catch-up session."""
    if not redis_client or not session_id:
        return None
    pattern = f"timeshift:channel:*:clients:{session_id}"
    cursor = 0
    while True:
        cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
        for key in keys:
            key_str = _decode_value(key)
            match = re.match(r"timeshift:channel:(.+):clients:.+", key_str)
            if match:
                return match.group(1)
        if cursor == 0:
            break
    return None


def _client_paused(raw_value):
    if raw_value is None or raw_value == "":
        return False
    value = _decode_value(raw_value).strip().lower()
    return value in {"1", "true", "yes"}


def update_catchup_session_position(
    session_id,
    *,
    position_secs,
    paused=None,
    user_id=None,
    redis_client=None,
):
    """Record a native client's playhead for catch-up stats.

    Updates the active stats client hash for ``session_id`` and refreshes the
    API session idle TTL. Does not seek the provider stream.

    Returns:
        ``True`` when metadata was updated, ``False`` when there is no active
        playback stats entry (or Redis is unavailable).
    """
    from apps.timeshift.sessions import touch_catchup_session

    if redis_client is None:
        redis_client = RedisClient.get_client()
    if redis_client is None or not session_id:
        return False

    stats_channel_id = find_stats_channel_for_session(redis_client, session_id)
    if not stats_channel_id:
        return False

    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, session_id)
    client_set_key = TimeshiftRedisKeys.clients(stats_channel_id)
    metadata_key = TimeshiftRedisKeys.channel_metadata(stats_channel_id)
    try:
        if not redis_client.exists(client_key):
            return False
        if user_id is not None:
            stored_user = redis_client.hget(client_key, "user_id")
            if stored_user is not None and str(_decode_value(stored_user)) != str(user_id):
                return False
    except Exception:
        return False

    now = str(time.time())
    mapping = {
        "playback_base_secs": str(float(position_secs)),
        "position_anchor_at": now,
        "last_active": now,
    }
    # Must match apps.timeshift.views.CLIENT_TTL_SECONDS (stats / fingerprint).
    client_ttl_seconds = 60

    try:
        pipe = redis_client.pipeline(transaction=False)
        pipe.hset(client_key, mapping=mapping)
        if paused is True:
            pipe.hset(client_key, "paused", "1")
        elif paused is False:
            pipe.hdel(client_key, "paused")
        pipe.expire(client_key, client_ttl_seconds)
        pipe.expire(client_set_key, client_ttl_seconds)
        pipe.expire(metadata_key, client_ttl_seconds)
        pipe.execute()
    except Exception:
        return False

    touch_catchup_session(session_id, redis_client=redis_client)
    return True


def build_timeshift_stats_data(redis_client):
    """Build catch-up stats payload from Redis session metadata."""
    empty = {
        "timeshift_sessions": [],
        "total_connections": 0,
        "timestamp": time.time(),
    }
    if redis_client is None:
        return empty

    try:
        current_time = time.time()
        connections = []
        cursor = 0
        metadata_pattern = "timeshift:channel:*:metadata"

        while True:
            cursor, keys = redis_client.scan(
                cursor, match=metadata_pattern, count=100,
            )
            for key in keys:
                key_str = _decode_value(key)
                match = re.search(r"timeshift:channel:(.+):metadata", key_str)
                if not match:
                    continue
                stats_channel_id = match.group(1)
                parsed_stats = parse_stats_channel_id(stats_channel_id)
                if not parsed_stats:
                    continue

                metadata = _decode_hash(redis_client.hgetall(key))

                client_set_key = TimeshiftRedisKeys.clients(stats_channel_id)
                client_ids = redis_client.smembers(client_set_key) or []
                if not client_ids:
                    continue

                init_time = float(metadata.get(ChannelMetadataField.INIT_TIME, 0) or 0)
                uptime = current_time - init_time if init_time > 0 else 0
                total_bytes = int(metadata.get(ChannelMetadataField.TOTAL_BYTES, 0) or 0)
                avg_bitrate_kbps = 0
                if uptime > 0 and total_bytes > 0:
                    avg_bitrate_kbps = (total_bytes * 8) / uptime / 1000

                logo_id = metadata.get(ChannelMetadataField.LOGO_ID)
                m3u_profile_id = metadata.get(ChannelMetadataField.M3U_PROFILE)
                channel_name = metadata.get(
                    ChannelMetadataField.CHANNEL_NAME, "Catch-up",
                )
                channel_id_raw = metadata.get(ChannelMetadataField.CHANNEL_ID)
                if not channel_id_raw:
                    channel_id_raw = str(parsed_stats["channel_id"])
                channel_uuid = metadata.get(ChannelMetadataField.CHANNEL_UUID, "")
                stream_info = stream_info_from_metadata(metadata)

                for raw_client_id in client_ids:
                    client_id = _decode_value(raw_client_id)
                    client_key = TimeshiftRedisKeys.client_metadata(
                        stats_channel_id, client_id,
                    )
                    client_data = _decode_hash(redis_client.hgetall(client_key))
                    if not client_data:
                        continue

                    programme_start = client_data.get("programme_start")
                    if not programme_start:
                        continue

                    try:
                        channel_id = int(channel_id_raw)
                    except (TypeError, ValueError):
                        continue

                    playback_base_raw = client_data.get("playback_base_secs")
                    playback_base_secs = None
                    if playback_base_raw is not None and playback_base_raw != "":
                        try:
                            playback_base_secs = float(playback_base_raw)
                        except (TypeError, ValueError):
                            playback_base_secs = None

                    paused = _client_paused(client_data.get("paused"))

                    connected_at = client_data.get("connected_at")
                    duration = 0
                    if connected_at:
                        try:
                            duration = int(current_time - float(connected_at))
                        except (TypeError, ValueError):
                            duration = 0

                    connections.append({
                        "stats_channel_id": stats_channel_id,
                        "session_id": parsed_stats["session_id"],
                        "client_id": client_id,
                        "channel_id": channel_id,
                        "channel_uuid": channel_uuid,
                        "channel_name": channel_name,
                        "logo_id": int(logo_id) if logo_id else None,
                        "programme_start": programme_start,
                        "position_anchor_at": client_data.get("position_anchor_at"),
                        "playback_base_secs": playback_base_secs,
                        "paused": paused,
                        "m3u_profile_id": int(m3u_profile_id) if m3u_profile_id else None,
                        "ip_address": client_data.get("ip_address", "Unknown"),
                        "user_agent": client_data.get("user_agent", "unknown"),
                        "user_id": client_data.get("user_id", "0"),
                        "username": client_data.get("username", "unknown"),
                        "connected_at": float(connected_at) if connected_at else None,
                        "duration": duration,
                        "bytes_streamed": total_bytes,
                        "avg_bitrate_kbps": round(avg_bitrate_kbps, 2),
                        "uptime": uptime,
                        **stream_info,
                    })

            if cursor == 0:
                break

        channel_ids = {conn["channel_id"] for conn in connections if conn.get("channel_id")}
        channels_by_id = {}
        if channel_ids:
            for channel in Channel.objects.select_related("logo", "epg_data").filter(
                id__in=channel_ids,
            ):
                channels_by_id[channel.id] = channel

        profile_ids = {
            conn["m3u_profile_id"]
            for conn in connections
            if conn.get("m3u_profile_id")
        }
        profiles_by_id = {}
        if profile_ids:
            for profile in M3UAccountProfile.objects.select_related("m3u_account").filter(
                id__in=profile_ids,
            ):
                profiles_by_id[profile.id] = profile

        session_stats = {}
        for conn in connections:
            session_key = conn["session_id"]
            channel = channels_by_id.get(conn["channel_id"])

            if channel:
                conn["channel_name"] = channel.name
                if channel.logo_id:
                    conn["logo_id"] = channel.logo_id
                    if channel.logo:
                        conn["logo_url"] = channel.logo.url

            profile = profiles_by_id.get(conn.get("m3u_profile_id"))
            if profile:
                conn["m3u_profile"] = {
                    "profile_name": profile.name,
                    "account_name": profile.m3u_account.name,
                    "account_id": profile.m3u_account.id,
                    "m3u_profile_id": profile.id,
                }

            position_anchor_at = conn.get("position_anchor_at")
            try:
                position_anchor_at = (
                    float(position_anchor_at) if position_anchor_at else None
                )
            except (TypeError, ValueError):
                position_anchor_at = None

            playback_base_secs = conn.get("playback_base_secs")

            if session_key not in session_stats:
                session_stats[session_key] = {
                    "session_id": session_key,
                    "stats_channel_id": conn["stats_channel_id"],
                    "channel_id": conn["channel_id"],
                    "channel_uuid": conn.get("channel_uuid", ""),
                    "channel_name": conn["channel_name"],
                    "logo_id": conn.get("logo_id"),
                    "logo_url": conn.get("logo_url"),
                    "programme_start": conn["programme_start"],
                    "position_anchor_at": position_anchor_at,
                    "playback_base_secs": playback_base_secs,
                    "paused": bool(conn.get("paused")),
                    "resolution": conn.get("resolution"),
                    "source_fps": conn.get("source_fps"),
                    "video_codec": conn.get("video_codec"),
                    "audio_codec": conn.get("audio_codec"),
                    "audio_channels": conn.get("audio_channels"),
                    "stream_type": conn.get("stream_type"),
                    "connection_count": 0,
                    "connections": [],
                }

            session_stats[session_key]["connection_count"] += 1
            session_stats[session_key]["connections"].append({
                "client_id": conn["client_id"],
                "session_id": conn["session_id"],
                "ip_address": conn["ip_address"],
                "user_agent": conn["user_agent"],
                "user_id": conn["user_id"],
                "username": conn["username"],
                "connected_at": conn["connected_at"],
                "duration": conn["duration"],
                "bytes_streamed": conn["bytes_streamed"],
                "avg_bitrate_kbps": conn["avg_bitrate_kbps"],
                "m3u_profile": conn.get("m3u_profile", {}),
                "m3u_profile_id": conn.get("m3u_profile_id"),
            })

        return {
            "timeshift_sessions": list(session_stats.values()),
            "total_connections": len(connections),
            "timestamp": current_time,
        }
    except Exception as exc:
        logger.error("Error building timeshift stats: %s", exc, exc_info=True)
        return empty
    finally:
        close_old_connections()
