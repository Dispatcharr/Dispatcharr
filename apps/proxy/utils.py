import logging
import re
from core.utils import RedisClient
from apps.proxy.vod_proxy.multi_worker_connection_manager import MultiWorkerVODConnectionManager, get_vod_client_stop_key
from apps.timeshift.redis_keys import (
    TimeshiftRedisKeys,
    parse_stats_channel_id,
)
from core.models import CoreSettings
from apps.proxy.live_proxy.services.channel_service import ChannelService

logger = logging.getLogger("proxy")

_STOP_REASON_LIMIT = "limit"
_STOP_REASON_ADMIN = "admin"


def _timeshift_stop_channel_id(redis_client, stats_channel_id, client_id, fallback=None):
    """Return the programme virtual_channel_id used for generator stop keys."""
    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
    programme_vid = redis_client.hget(client_key, "programme_vid")
    if programme_vid:
        if isinstance(programme_vid, bytes):
            programme_vid = programme_vid.decode()
        return programme_vid
    return fallback if fallback is not None else stats_channel_id


def _timeshift_generation_channel_ids(redis_client, client_id):
    """Return virtual channel ids with active generation counters for a client."""
    if redis_client is None or not client_id:
        return []
    prefix = "timeshift:stream_gen:"
    suffix = f":{client_id}"
    try:
        keys = redis_client.scan_iter(
            match=f"{prefix}*{suffix}", count=100,
        )
        channel_ids = []
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode()
            key = str(key)
            if not key.startswith(prefix) or not key.endswith(suffix):
                continue
            channel_id = key[len(prefix):-len(suffix)]
            if channel_id:
                channel_ids.append(channel_id)
        return channel_ids
    except Exception as exc:
        logger.debug(
            "Timeshift generation stop-key scan failed for %s: %s",
            client_id, exc,
        )
        return []


def _timeshift_stop_channel_ids(redis_client, stats_channel_id, client_id, fallback=None):
    """Return all Redis stop-key channel ids that may be observed by a stream."""
    candidates = [
        _timeshift_stop_channel_id(
            redis_client, stats_channel_id, client_id, fallback=fallback,
        )
    ]
    candidates.extend(_timeshift_generation_channel_ids(redis_client, client_id))

    seen = set()
    ordered = []
    for channel_id in candidates:
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        ordered.append(channel_id)
    return ordered


def _set_timeshift_stop_keys(redis_client, stats_channel_id, client_id, reason, fallback=None):
    """Signal a timeshift stream to stop across workers."""
    stop_channel_ids = _timeshift_stop_channel_ids(
        redis_client, stats_channel_id, client_id, fallback=fallback,
    )
    for stop_channel_id in stop_channel_ids:
        stop_key = TimeshiftRedisKeys.client_stop(stop_channel_id, client_id)
        redis_client.setex(stop_key, 60, reason)
    return stop_channel_ids


def stop_timeshift_client(redis_client, stats_channel_id, client_id):
    """Stop one catch-up viewer (admin Stats UI and ``POST /proxy/catchup/stop_client/``)."""
    if redis_client is None:
        return {"status": "error", "message": "Redis unavailable"}
    if not stats_channel_id or not client_id:
        return {"status": "error", "message": "Missing channel or client id"}

    from apps.timeshift.views import (
        _cancel_stats_disconnect_grace,
        _cleanup_all_stream_generations,
        _close_active_upstream,
        _finalize_playback_session_auth,
        _trigger_timeshift_stats_update,
        _unregister_stats_client,
    )

    try:
        stop_channel_ids = _set_timeshift_stop_keys(
            redis_client, stats_channel_id, client_id, _STOP_REASON_ADMIN,
        )
        for stop_channel_id in stop_channel_ids:
            _close_active_upstream(stop_channel_id, client_id)
        _cancel_stats_disconnect_grace(redis_client, stats_channel_id, client_id)
        _unregister_stats_client(redis_client, stats_channel_id, client_id)
        _cleanup_all_stream_generations(redis_client, client_id)
        _finalize_playback_session_auth(redis_client, client_id)
        try:
            from apps.timeshift.views import _superseded_pool_key
            redis_client.delete(_superseded_pool_key(client_id))
        except Exception:
            pass
    except Exception as exc:
        logger.error(
            "Timeshift admin stop failed for %s on %s: %s",
            client_id, stats_channel_id, exc,
        )
        return {"status": "error", "message": str(exc)}

    _trigger_timeshift_stats_update(redis_client)

    logger.info(
        "Timeshift admin stop: client=%s stats_channel=%s stop_channels=%s",
        client_id, stats_channel_id, stop_channel_ids,
    )
    return {
        "status": "success",
        "message": "Timeshift client stop signal sent",
        "channel_id": stats_channel_id,
        "client_id": client_id,
        "stop_channel_id": stop_channel_ids[0] if stop_channel_ids else stats_channel_id,
        "stop_channel_ids": stop_channel_ids,
        "stop_key_set": True,
        "locally_processed": False,
    }


def attempt_stream_termination(user_id, requesting_client_id, active_connections):
    try:
        logger.info("[stream limits]" f"[{requesting_client_id}] User {user_id} has {len(active_connections)} active connections, checking termination candidates")

        user_limit_settings = CoreSettings.get_user_limits_settings()
        terminate_oldest = user_limit_settings.get("terminate_oldest", True)
        prioritize_single = user_limit_settings.get("prioritize_single_client_channels", True)
        ignore_same_channel = user_limit_settings.get("ignore_same_channel_connections", False)

        channel_counts = {}
        for connection in active_connections:
            media_id = connection['media_id']
            channel_counts[media_id] = channel_counts.get(media_id, 0) + 1

        def prioritize(connection):
            is_multi = channel_counts[connection['media_id']] > 1

            # if we're ignoring same-channel connections, put them at the end
            same_ch_key = 1 if (ignore_same_channel and is_multi) else 0

            # key for prioritizing single-client channels
            single_key = 0 if (prioritize_single and not is_multi) else 1

            # sort by age setting
            time_key = connection['connected_at'] if terminate_oldest else -connection['connected_at']

            return (same_ch_key, single_key, time_key)

        termination_candidates = sorted(active_connections, key=prioritize)

        if not termination_candidates:
            logger.warning("[stream limits]" f"[{requesting_client_id}] No termination candidates found for user {user_id}")
            return False

        target = termination_candidates[0]
        logger.info("[stream limits]"
            f"[{requesting_client_id}] Terminating client {target['client_id']} "
            f"on media {target['media_id']} (connected_at={target['connected_at']})"
        )

        # When counting by unique channel, stop all connections on that channel.
        targets = (
            [c for c in active_connections if c['media_id'] == target['media_id']]
            if ignore_same_channel
            else [target]
        )

        for t in targets:
            if t['type'] == 'live':
                result = ChannelService.stop_client(t['media_id'], t['client_id'])
                if result.get("status") == "error":
                    logger.warning(f"[stream limits][{requesting_client_id}] Failed to stop client {t['client_id']} on channel {t['media_id']}")
            elif t['type'] == 'timeshift':
                redis_client = RedisClient.get_client()
                if not redis_client:
                    # Deny the new stream if we cannot stop the old one.
                    return False
                stop_channel_ids = _set_timeshift_stop_keys(
                    redis_client, t['media_id'], t['client_id'], _STOP_REASON_LIMIT,
                )
                from apps.timeshift.views import _close_active_upstream
                for stop_channel_id in stop_channel_ids:
                    _close_active_upstream(stop_channel_id, t['client_id'])
                logger.info(
                    f"[stream limits][{requesting_client_id}] Set stop key for "
                    f"timeshift client {t['client_id']} on {stop_channel_ids}",
                )
            else:
                connection_manager = MultiWorkerVODConnectionManager.get_instance()
                redis_client = connection_manager.redis_client

                if not redis_client:
                    return False

                connection_key = f"vod_persistent_connection:{t['client_id']}"
                connection_data = redis_client.hgetall(connection_key)
                if not connection_data:
                    logger.warning(f"VOD connection not found: {t['client_id']}")
                    continue

                stop_key = get_vod_client_stop_key(t['client_id'])
                redis_client.setex(stop_key, 60, "true")  # 60 second TTL

        return True
    except Exception as e:
        logger.error("[stream limits]" f"[{requesting_client_id}] Error during stream termination for user {user_id}: {e}")
        return False

def get_user_active_connections(user_id):
    """Return active stream connections for a single user.

    Pass `user_id=None` to return all active connections across the system.
    """
    redis_client = RedisClient.get_client()
    connections = []

    try:
        # Grab live and timeshift streams (same key layout, separate namespaces)
        for pattern, conn_type in (
            ("live:channel:*:clients:*", "live"),
            ("timeshift:channel:*:clients:*", "timeshift"),
        ):
            for key in redis_client.scan_iter(match=pattern, count=1000):
                parts = key.split(':')
                if len(parts) >= 5:
                    channel_id = parts[2]
                    client_id = parts[4]

                    client_user_id, connected_at = redis_client.hmget(key, 'user_id', 'connected_at')

                    logger.debug(f"[stream limits] user_id = {user_id}")
                    logger.debug(f"[stream limits] channel_id = {channel_id}")
                    logger.debug(f"[stream limits] client_id = {client_id}")

                    if user_id is None or (client_user_id and int(client_user_id) == user_id):
                        try:
                            logger.debug(f"[stream limits] Found {conn_type.upper()} connection for user {user_id} on channel {channel_id} with client ID {client_id}")
                            connected_at = float(connected_at) if connected_at else 0
                            connections.append({
                                'media_id': channel_id,
                                'client_id': client_id,
                                'connected_at': connected_at,
                                'type': conn_type,
                            })
                        except (ValueError, TypeError):
                            pass

        # Grab VOD
        for key in redis_client.scan_iter(match="vod_persistent_connection:*", count=1000):
            parts = key.split(':')
            if len(parts) >= 2:
                client_id = parts[1]

                client_user_id, connected_at, content_uuid = redis_client.hmget(
                    key, 'user_id', 'created_at', 'content_uuid'
                )

                logger.debug(f"[stream limits] user_id = {user_id}")
                logger.debug(f"[stream limits] client_id = {client_id}")

                if user_id is None or (client_user_id and int(client_user_id) == user_id):
                    try:
                        logger.debug(f"[stream limits] Found VOD connection for user {user_id} on content {content_uuid} with client ID {client_id}")
                        connected_at = float(connected_at) if connected_at else 0
                        connections.append({
                            'media_id': content_uuid or client_id,
                            'client_id': client_id,
                            'connected_at': connected_at,
                            'type': 'vod',
                        })
                    except (ValueError, TypeError):
                        pass

        return connections

    except Exception as e:
        logger.warning(f"Error getting active channel details for user {user_id}: {e}")
        return []


def check_user_stream_limits(user, client_id, media_id=None):
    # Check user stream limits
    if user and user.stream_limit > 0:
        logger.debug("[stream limits]" f"[{client_id}] User {user.username} (ID: {user.id}) is requesting a stream (stream_limit: {user.stream_limit})")
        user_limit_settings = CoreSettings.get_user_limits_settings()
        ignore_same_channel = user_limit_settings.get("ignore_same_channel_connections", False)

        active_connections = get_user_active_connections(user.id)
        unique_channel_count = set([conn['media_id'] for conn in active_connections])
        user_stream_count = len(unique_channel_count) if ignore_same_channel else len(active_connections)

        logger.debug(f"[stream limits]" f"[{client_id}] User {user.username} currently has {len(active_connections)} active connections across {len(unique_channel_count)} unique channels (counting method: {'unique channels' if ignore_same_channel else 'total connections'})")

        # If ignore_same_channel is enabled and this request is for a live channel the user
        # is already watching, allow it through without counting against the limit.
        # VOD is excluded: connections aren't shared so multiple VOD connections to the
        # same content would mean multiple upstream connections.
        live_channel_ids = {str(conn['media_id']) for conn in active_connections if conn['type'] == 'live'}
        if ignore_same_channel and media_id and str(media_id) in live_channel_ids:
            logger.debug(f"[stream limits][{client_id}] Same-channel reconnect for {media_id} allowed (ignore_same_channel=True)")
            return True

        # Timeshift sibling range/probe requests share one provider slot per
        # session_id. Each distinct client/session still consumes its own slot.
        if media_id and client_id:
            media_id_str = str(media_id)
            req_channel = None
            channel_match = re.match(r"^(\d+)_", media_id_str)
            if channel_match:
                req_channel = channel_match.group(1)
            for conn in active_connections:
                if conn.get('type') != 'timeshift':
                    continue
                if conn.get('client_id') != client_id:
                    continue
                conn_media_id = str(conn.get('media_id') or '')
                if conn_media_id == media_id_str or conn_media_id.startswith(f"{media_id_str}_"):
                    logger.debug(
                        f"[stream limits][{client_id}] Same timeshift session probe for {media_id} allowed"
                    )
                    return True
                if req_channel:
                    parsed_conn = parse_stats_channel_id(conn_media_id)
                    if parsed_conn:
                        conn_channel = str(parsed_conn["channel_id"])
                    else:
                        conn_channel = conn_media_id.split("_", 1)[0]
                    if conn_channel == req_channel:
                        logger.debug(
                            f"[stream limits][{client_id}] Same timeshift channel {req_channel} allowed"
                        )
                        return True

        if user_stream_count >= user.stream_limit:
            if user_limit_settings.get("terminate_on_limit_exceeded", True) == False:
                return False

            if user_stream_count >= user.stream_limit:
                logger.warning("[stream limits]"
                    f"[{client_id}] User {user.username} (ID: {user.id}) has reached stream limit "
                    f"({user_stream_count}/{user.stream_limit} streams), attempting to free up slot"
                )

                if not attempt_stream_termination(user.id, client_id, active_connections):
                    return False

    return True


_TS_PACKET_SIZE = 188
_TS_SYNC_BYTE = 0x47


def find_ts_sync(buf):
    """Return byte offset of the first valid MPEG-TS sync chain in *buf*, or -1.

    Args:
        buf: Raw bytes from an upstream HTTP response (typically the first 1 KB).

    Returns:
        Offset of the first 0x47 byte that starts three consecutive 188-byte
        packets, or -1. Used to strip PHP/HTML preamble before streaming.
    """
    end = len(buf) - 2 * _TS_PACKET_SIZE
    for i in range(0, end):
        if (
            buf[i] == _TS_SYNC_BYTE
            and buf[i + _TS_PACKET_SIZE] == _TS_SYNC_BYTE
            and buf[i + 2 * _TS_PACKET_SIZE] == _TS_SYNC_BYTE
        ):
            return i
    return -1
