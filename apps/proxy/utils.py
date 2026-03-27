import logging
from core.utils import RedisClient
from apps.proxy.vod_proxy.multi_worker_connection_manager import MultiWorkerVODConnectionManager, get_vod_client_stop_key
from core.models import CoreSettings
from apps.proxy.ts_proxy.services.channel_service import ChannelService

logger = logging.getLogger("proxy")


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

        # When counting by unique channel, freeing one connection from a multi-connection
        # channel doesn't free a slot — terminate all connections to that channel so the
        # unique-channel count actually drops by one.
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
    redis_client = RedisClient.get_client()
    connections = []

    try:
        # Grab live streams
        for key in redis_client.scan_iter(match="ts_proxy:channel:*:clients:*", count=1000):
            parts = key.split(':')
            if len(parts) >= 5:
                channel_id = parts[2]
                client_id = parts[4]

                client_user_id = redis_client.hget(key, 'user_id')
                connected_at = redis_client.hget(key, 'connected_at')

                logger.debug(f"[stream limits] user_id = {user_id}")
                logger.debug(f"[stream limits] channel_id = {channel_id}")
                logger.debug(f"[stream limits] client_id = {client_id}")

                if client_user_id and int(client_user_id) == user_id:
                    try:
                        logger.debug(f"[stream limits] Found LIVE connection for user {user_id} on channel {channel_id} with client ID {client_id}")
                        connected_at = float(connected_at) if connected_at else 0
                        connections.append({
                            'media_id': channel_id,
                            'client_id': client_id,
                            'connected_at': connected_at,
                            'type': 'live',
                        })
                    except (ValueError, TypeError):
                        pass

        # Grab VOD
        for key in redis_client.scan_iter(match="vod_persistent_connection:*", count=1000):
            parts = key.split(':')
            if len(parts) >= 2:
                client_id = parts[1]

                client_user_id = redis_client.hget(key, 'user_id')
                connected_at = redis_client.hget(key, 'created_at')
                content_uuid = redis_client.hget(key, 'content_uuid')

                logger.debug(f"[stream limits] user_id = {user_id}")
                logger.debug(f"[stream limits] client_id = {client_id}")

                if client_user_id and int(client_user_id) == user_id:
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
