import logging
from core.utils import RedisClient
from apps.proxy.vod_proxy.multi_worker_connection_manager import MultiWorkerVODConnectionManager, get_vod_client_stop_key
from core.models import CoreSettings
from apps.proxy.ts_proxy.services.channel_service import ChannelService

logger = logging.getLogger("proxy")


def attempt_stream_termination(user_id, requesting_client_id, active_connections):
    try:
        logger.info("[stream limits]" f"[{requesting_client_id}] User {user_id} has {len(active_connections)} active connections, checking termination candidates")

        user_limit_settings = CoreSettings.get_user_limit_settings()
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

        if target['type'] == 'live':
            result = ChannelService.stop_client(target['media_id'], target['client_id'])
            if result.get("status") == "error":
                return False
        else:
            connection_manager = MultiWorkerVODConnectionManager.get_instance()
            redis_client = connection_manager.redis_client

            if not redis_client:
                return False

            # Check if connection exists
            connection_key = f"vod_persistent_connection:{target['client_id']}"
            connection_data = redis_client.hgetall(connection_key)
            if not connection_data:
                logger.warning(f"VOD connection not found: {target['client_id']}")
                return False

            # Set a stop signal key that the worker will check
            stop_key = get_vod_client_stop_key(target['client_id'])
            redis_client.setex(stop_key, 60, "true")  # 60 second TTL

        return True
    except Exception as e:
        logger.error("[stream limits]" f"[{requesting_client_id}] Error during stream termination for user {user_id}: {e}")
        return False

def get_user_active_connections(user_id):
    redis_client = RedisClient.get_client()
    connections = []

    try:
        cursor = 0

        # Grab live streams
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match="ts_proxy:channel:*:clients:*", count=1000)

            for key in keys:
                parts = key.split(':')
                if len(parts) >= 5:
                    channel_id = parts[2]
                    client_id = parts[4]

                    client_user_id = redis_client.hget(key, 'user_id')
                    connected_at = redis_client.hget(key, 'connected_at')

                    logger.info(f"[stream limits] user_id = {user_id}")
                    logger.info(f"[stream limits] channel_id = {channel_id}")
                    logger.info(f"[stream limits] client_id = {client_id}")

                    if client_user_id and int(client_user_id) == user_id:
                        try:
                            logger.info(f"[stream limits] Found LIVE connection for user {user_id} on channel {channel_id} with client ID {client_id}")
                            connected_at = float(connected_at) if connected_at else 0
                            connections.append({
                                'media_id': channel_id,
                                'client_id': client_id,
                                'connected_at': connected_at,
                                'type': 'live',
                            })
                        except (ValueError, TypeError):
                            pass

            if cursor == 0:
                break


        cursor = 0

        # Grab VOD
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match="vod_persistent_connections:*", count=1000)

            for key in keys:
                parts = key.split(':')
                if len(parts) >= 2:
                    client_id = parts[1]

                    client_user_id = redis_client.hget(key, 'user_id')
                    connected_at = redis_client.hget(key, 'created_at')

                    logger.info(f"[stream limits] user_id = {user_id}")
                    logger.info(f"[stream limits] client_id = {client_id}")

                    if client_user_id and int(client_user_id) == user_id:
                        try:
                            logger.info(f"[stream limits] Found VOD connection for user {user_id} on channel {channel_id} with client ID {client_id}")
                            connected_at = float(connected_at) if connected_at else 0
                            connections.append({
                                'media_id': channel_id,
                                'client_id': client_id,
                                'connected_at': connected_at,
                                'type': 'vod',
                            })
                        except (ValueError, TypeError):
                            pass

            if cursor == 0:
                break

        return connections

    except Exception as e:
        logger.warning(f"Error getting active channel details for user {user_id}: {e}")
        return []


def check_user_stream_limits(user, client_id):
    # Check user stream limits
    if user and user.stream_limit > 0:
        logger.info("[stream limits]" f"[{client_id}] User {user.username} (ID: {user.id}) is requesting a stream (stream_limit: {user.stream_limit})")
        user_limit_settings = CoreSettings.get_user_limit_settings()

        active_connections = get_user_active_connections(user.id)
        unique_channel_count = set([conn['media_id'] for conn in active_connections])
        user_stream_count = len(unique_channel_count) if user_limit_settings.get("ignore_same_channel_connections", False) else len(active_connections)

        print(active_connections)

        logger.info(f"[stream limits]" f"[{client_id}] User {user.username} currently has {len(active_connections)} active connections across {len(unique_channel_count)} unique channels (counting method: {'unique channels' if user_limit_settings.get('ignore_same_channel_connections', False) else 'total connections'})")

        if user.stream_limit > 0 and user_stream_count >= user.stream_limit:
            if user_limit_settings.get("terminate_on_limit_exceeded", True) == False:
                return False

            if len(active_connections) >= user.stream_limit:
                logger.warning("[stream limits]"
                    f"[{client_id}] User {user.username} (ID: {user.id}) has reached stream limit "
                    f"({len(active_connections)}/{user.stream_limit} channels), attempting to free up slot"
                )

                if not attempt_stream_termination(user.id, client_id, active_connections):
                    return False

        return True
