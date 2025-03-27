"""
Channel service layer for handling business logic related to channel operations.
This separates business logic from HTTP handling in views.
"""

import logging
import time
import json
from django.shortcuts import get_object_or_404
from apps.channels.models import Channel
from apps.proxy.config import TSConfig as Config
from .. import proxy_server
from ..redis_keys import RedisKeys
from ..constants import EventType, ChannelState, ChannelMetadataField
from ..url_utils import get_stream_info_for_switch

logger = logging.getLogger("ts_proxy")

class ChannelService:
    """Service class for channel operations"""

    @staticmethod
    def initialize_channel(channel_id, stream_url, user_agent, transcode=False, profile_value=None, stream_id=None):
        """
        Initialize a channel with the given parameters.

        Args:
            channel_id: UUID of the channel
            stream_url: URL of the stream
            user_agent: User agent for the stream connection
            transcode: Whether to transcode the stream
            profile_value: Stream profile value to store in metadata
            stream_id: ID of the stream being used

        Returns:
            bool: Success status
        """
        # FIXED: First, ensure that Redis metadata including stream_id is set BEFORE channel initialization
        # This ensures the stream ID is available when the StreamManager looks it up
        if stream_id and proxy_server.redis_client:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            # Check if metadata already exists
            if proxy_server.redis_client.exists(metadata_key):
                # Just update the existing metadata with stream_id
                proxy_server.redis_client.hset(metadata_key, ChannelMetadataField.STREAM_ID, str(stream_id))
                logger.info(f"Pre-set stream ID {stream_id} in Redis for channel {channel_id}")
            else:
                # Create initial metadata with essential values
                initial_metadata = {
                    ChannelMetadataField.STREAM_ID: str(stream_id),
                    "temp_init": str(time.time())
                }
                proxy_server.redis_client.hset(metadata_key, mapping=initial_metadata)
                logger.info(f"Created initial metadata with stream_id {stream_id} for channel {channel_id}")

            # Verify the stream_id was set
            stream_id_value = proxy_server.redis_client.hget(metadata_key, ChannelMetadataField.STREAM_ID)
            if stream_id_value:
                logger.info(f"Verified stream_id {stream_id_value.decode('utf-8')} is now set in Redis")
            else:
                logger.error(f"Failed to set stream_id {stream_id} in Redis before initialization")

        # Now proceed with channel initialization
        success = proxy_server.initialize_channel(stream_url, channel_id, user_agent, transcode, stream_id)

        # Store additional metadata if initialization was successful
        if success and proxy_server.redis_client:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            update_data = {}
            if profile_value:
                update_data[ChannelMetadataField.STREAM_PROFILE] = profile_value
            if stream_id:
                update_data[ChannelMetadataField.STREAM_ID] = str(stream_id)

            if update_data:
                proxy_server.redis_client.hset(metadata_key, mapping=update_data)

        return success

    @staticmethod
    def change_stream_url(channel_id, new_url=None, user_agent=None, target_stream_id=None):
        """
        Change the URL of an existing stream.

        Args:
            channel_id: UUID of the channel
            new_url: New stream URL (optional if target_stream_id is provided)
            user_agent: Optional user agent to update
            target_stream_id: Optional target stream ID to switch to

        Returns:
            dict: Result information including success status and diagnostics
        """
        # If no direct URL is provided but a target stream is, get URL from target stream
        if not new_url and target_stream_id:
            stream_info = get_stream_info_for_switch(channel_id, target_stream_id)
            if 'error' in stream_info:
                return {
                    'status': 'error',
                    'message': stream_info['error']
                }
            new_url = stream_info['url']
            user_agent = stream_info['user_agent']

        # Check if channel exists
        in_local_managers = channel_id in proxy_server.stream_managers
        in_local_buffers = channel_id in proxy_server.stream_buffers

        # Check Redis for keys
        redis_keys = None
        if proxy_server.redis_client:
            try:
                # This is inefficient but used for diagnostics - in production would use more targeted checks
                redis_keys = proxy_server.redis_client.keys(f"ts_proxy:*:{channel_id}*")
                redis_keys = [k.decode('utf-8') for k in redis_keys] if redis_keys else []
            except Exception as e:
                logger.error(f"Error checking Redis keys: {e}")

        # Check if channel exists using standard method
        channel_exists = proxy_server.check_if_channel_exists(channel_id)

        # Log detailed diagnostics
        logger.info(f"Channel {channel_id} diagnostics: "
                   f"in_local_managers={in_local_managers}, "
                   f"in_local_buffers={in_local_buffers}, "
                   f"redis_keys_count={len(redis_keys) if redis_keys else 0}, "
                   f"channel_exists={channel_exists}")

        if not channel_exists:
            # Try to recover if Redis keys exist but channel check failed
            if redis_keys:
                logger.warning(f"Channel {channel_id} not detected but Redis keys exist. Forcing initialization.")
                proxy_server.initialize_channel(new_url, channel_id, user_agent)
                result = {
                    'status': 'recovered',
                    'message': 'Channel was recovered and initialized'
                }
            else:
                logger.error(f"Channel {channel_id} not found in any worker or Redis")
                return {
                    'status': 'error',
                    'message': 'Channel not found',
                    'diagnostics': {
                        'in_local_managers': in_local_managers,
                        'in_local_buffers': in_local_buffers,
                        'redis_keys': redis_keys,
                    }
                }
        else:
            result = {'status': 'success'}

        # Update metadata in Redis regardless of ownership
        if proxy_server.redis_client:
            try:
                ChannelService._update_channel_metadata(channel_id, new_url, user_agent)
                result['metadata_updated'] = True
            except Exception as e:
                logger.error(f"Error updating Redis metadata: {e}", exc_info=True)
                result['metadata_updated'] = False

        # If we're the owner, update directly
        if proxy_server.am_i_owner(channel_id) and channel_id in proxy_server.stream_managers:
            logger.info(f"This worker is the owner, changing stream URL for channel {channel_id}")
            manager = proxy_server.stream_managers[channel_id]
            old_url = manager.url

            # Update the stream
            success = manager.update_url(new_url)
            logger.info(f"Stream URL changed from {old_url} to {new_url}, result: {success}")

            result.update({
                'direct_update': True,
                'success': success,
                'worker_id': proxy_server.worker_id
            })
        else:
            # If we're not the owner, publish an event for the owner to pick up
            logger.info(f"Not the owner, requesting URL change via Redis PubSub")
            if proxy_server.redis_client:
                ChannelService._publish_stream_switch_event(channel_id, new_url, user_agent)
                result.update({
                    'direct_update': False,
                    'event_published': True,
                    'worker_id': proxy_server.worker_id
                })
            else:
                result.update({
                    'direct_update': False,
                    'event_published': False,
                    'error': 'Redis not available for pubsub'
                })

        return result

    @staticmethod
    def stop_channel(channel_id):
        """
        Stop a channel and release all resources.

        Args:
            channel_id: UUID of the channel

        Returns:
            dict: Result information including previous state if available
        """
        # Check if channel exists
        channel_exists = proxy_server.check_if_channel_exists(channel_id)
        if not channel_exists:
            logger.warning(f"Channel {channel_id} not found in any worker or Redis")
            return {'status': 'error', 'message': 'Channel not found'}

        # Get channel state information for result
        channel_info = None
        if proxy_server.redis_client:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            try:
                metadata = proxy_server.redis_client.hgetall(metadata_key)
                if metadata and b'state' in metadata:
                    state = metadata[b'state'].decode('utf-8')
                    channel_info = {"state": state}

                    # Immediately mark as stopping in metadata so clients detect it faster
                    proxy_server.redis_client.hset(metadata_key, ChannelMetadataField.STATE, ChannelState.STOPPING)
                    proxy_server.redis_client.hset(metadata_key, ChannelMetadataField.STATE_CHANGED_AT, str(time.time()))
            except Exception as e:
                logger.error(f"Error fetching channel state: {e}")

        # Set stopping flag with higher TTL to ensure it persists
        if proxy_server.redis_client:
            stop_key = RedisKeys.channel_stopping(channel_id)
            proxy_server.redis_client.setex(stop_key, 60, "true")  # Higher TTL of 60 seconds
            logger.info(f"Set channel stopping flag with 60s TTL for channel {channel_id}")

        # Broadcast stop event to all workers via PubSub
        if proxy_server.redis_client:
            ChannelService._publish_channel_stop_event(channel_id)

            # Also stop locally to ensure this worker cleans up right away
            local_result = proxy_server.stop_channel(channel_id)
        else:
            # No Redis, just stop locally
            local_result = proxy_server.stop_channel(channel_id)

        # Release the channel in the channel model if applicable
        try:
            channel = Channel.objects.get(uuid=channel_id)
            channel.release_stream()
            logger.info(f"Released channel {channel_id} stream allocation")
            model_released = True
        except Channel.DoesNotExist:
            logger.warning(f"Could not find Channel model for UUID {channel_id}, attempting stream hash")
            stream = Stream.objects.get(stream_hash=channel_id)
            stream.release_stream()
            logger.info(f"Released stream {channel_id} stream allocation")
            model_released = True
        except Exception as e:
            logger.error(f"Error releasing channel stream: {e}")
            model_released = False

        return {
            'status': 'success',
            'message': 'Channel stop request sent',
            'channel_id': channel_id,
            'previous_state': channel_info,
            'model_released': model_released,
            'local_stop_result': local_result
        }

    @staticmethod
    def stop_client(channel_id, client_id):
        """
        Stop a specific client connection.

        Args:
            channel_id: UUID of the channel
            client_id: ID of the client to stop

        Returns:
            dict: Result information
        """
        logger.info(f"Request to stop client {client_id} on channel {channel_id}")

        # Set a Redis key for immediate detection
        key_set = False
        if proxy_server.redis_client:
            stop_key = RedisKeys.client_stop(channel_id, client_id)
            try:
                proxy_server.redis_client.setex(stop_key, 30, "true")  # 30 second TTL
                logger.info(f"Set stop key for client {client_id}")
                key_set = True
            except Exception as e:
                logger.error(f"Error setting client stop key: {e}")

        # Check if channel exists
        channel_exists = proxy_server.check_if_channel_exists(channel_id)
        if not channel_exists:
            logger.warning(f"Channel {channel_id} not found")
            return {
                'status': 'error',
                'message': 'Channel not found',
                'stop_key_set': key_set
            }

        # Try to stop locally if client is on this worker
        local_client_stopped = False
        if channel_id in proxy_server.client_managers:
            client_manager = proxy_server.client_managers[channel_id]
            with client_manager.lock:
                if client_id in client_manager.clients:
                    client_manager.remove_client(client_id)
                    local_client_stopped = True
                    logger.info(f"Client {client_id} stopped locally on channel {channel_id}")

        # If client wasn't found locally, broadcast stop event for other workers
        event_published = False
        if not local_client_stopped and proxy_server.redis_client:
            try:
                ChannelService._publish_client_stop_event(channel_id, client_id)
                event_published = True
                logger.info(f"Published stop request for client {client_id} on channel {channel_id}")
            except Exception as e:
                logger.error(f"Error publishing client stop event: {e}")

        return {
            'status': 'success',
            'message': 'Client stop request processed',
            'channel_id': channel_id,
            'client_id': client_id,
            'locally_processed': local_client_stopped,
            'stop_key_set': key_set,
            'event_published': event_published
        }

    @staticmethod
    def validate_channel_state(channel_id):
        """
        Validate if a channel is in a healthy state and has an active owner.

        Args:
            channel_id: UUID of the channel

        Returns:
            tuple: (valid, state, owner, details) - validity status, current state, owner, and diagnostic info
        """
        if not proxy_server.redis_client:
            return False, None, None, {"error": "Redis not available"}

        try:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            if not proxy_server.redis_client.exists(metadata_key):
                return False, None, None, {"error": "No channel metadata"}

            metadata = proxy_server.redis_client.hgetall(metadata_key)

            # Extract state and owner
            state = metadata.get(ChannelMetadataField.STATE.encode(), b'unknown').decode('utf-8')
            owner = metadata.get(ChannelMetadataField.OWNER.encode(), b'unknown').decode('utf-8')

            # Valid states indicate channel is running properly
            valid_states = [ChannelState.ACTIVE, ChannelState.WAITING_FOR_CLIENTS, ChannelState.CONNECTING]

            if state not in valid_states:
                return False, state, owner, {"error": f"Invalid state: {state}"}

            # Check if owner is still active
            owner_heartbeat_key = RedisKeys.worker_heartbeat(owner)
            owner_alive = proxy_server.redis_client.exists(owner_heartbeat_key)

            if not owner_alive:
                return False, state, owner, {"error": "Owner not active"}

            # Check for recent activity
            last_data_key = RedisKeys.last_data(channel_id)
            last_data = proxy_server.redis_client.get(last_data_key)

            details = {
                "state": state,
                "owner": owner,
                "owner_alive": owner_alive
            }

            if last_data:
                last_data_time = float(last_data.decode('utf-8'))
                data_age = time.time() - last_data_time
                details["last_data_age"] = data_age

                # If no data for too long, consider invalid
                if data_age > 30:  # 30 seconds threshold
                    return False, state, owner, {"error": f"No data for {data_age:.1f}s", **details}

            return True, state, owner, details

        except Exception as e:
            logger.error(f"Error validating channel state: {e}", exc_info=True)
            return False, None, None, {"error": f"Exception: {str(e)}"}

    # Helper methods for Redis operations

    @staticmethod
    def _update_channel_metadata(channel_id, url, user_agent=None):
        """Update channel metadata in Redis"""
        if not proxy_server.redis_client:
            return False

        metadata_key = RedisKeys.channel_metadata(channel_id)

        # First check if the key exists and what type it is
        key_type = proxy_server.redis_client.type(metadata_key).decode('utf-8')
        logger.debug(f"Redis key {metadata_key} is of type: {key_type}")

        # Use the appropriate method based on the key type
        if key_type == 'hash':
            proxy_server.redis_client.hset(metadata_key, ChannelMetadataField.URL, url)
            if user_agent:
                proxy_server.redis_client.hset(metadata_key, ChannelMetadataField.USER_AGENT, user_agent)
        elif key_type == 'none':  # Key doesn't exist yet
            # Create new hash with all required fields
            metadata = {ChannelMetadataField.URL: url}
            if user_agent:
                metadata[ChannelMetadataField.USER_AGENT] = user_agent
            proxy_server.redis_client.hset(metadata_key, mapping=metadata)
        else:
            # If key exists with wrong type, delete it and recreate
            proxy_server.redis_client.delete(metadata_key)
            metadata = {ChannelMetadataField.URL: url}
            if user_agent:
                metadata[ChannelMetadataField.USER_AGENT] = user_agent
            proxy_server.redis_client.hset(metadata_key, mapping=metadata)

        # Set switch request flag to ensure all workers see it
        switch_key = RedisKeys.switch_request(channel_id)
        proxy_server.redis_client.setex(switch_key, 30, url)  # 30 second TTL

        logger.info(f"Updated metadata for channel {channel_id} in Redis")
        return True

    @staticmethod
    def _publish_stream_switch_event(channel_id, new_url, user_agent=None):
        """Publish a stream switch event to Redis pubsub"""
        if not proxy_server.redis_client:
            return False

        switch_request = {
            "event": EventType.STREAM_SWITCH,
            "channel_id": channel_id,
            "url": new_url,
            "user_agent": user_agent,
            "requester": proxy_server.worker_id,
            "timestamp": time.time()
        }

        proxy_server.redis_client.publish(
            RedisKeys.events_channel(channel_id),
            json.dumps(switch_request)
        )
        return True

    @staticmethod
    def _publish_channel_stop_event(channel_id):
        """Publish a channel stop event to Redis pubsub"""
        if not proxy_server.redis_client:
            return False

        stop_request = {
            "event": EventType.CHANNEL_STOP,
            "channel_id": channel_id,
            "requester_worker_id": proxy_server.worker_id,
            "timestamp": time.time()
        }

        proxy_server.redis_client.publish(
            RedisKeys.events_channel(channel_id),
            json.dumps(stop_request)
        )

        logger.info(f"Published channel stop event for {channel_id}")
        return True

    @staticmethod
    def _publish_client_stop_event(channel_id, client_id):
        """Publish a client stop event to Redis pubsub"""
        if not proxy_server.redis_client:
            return False

        stop_request = {
            "event": EventType.CLIENT_STOP,
            "channel_id": channel_id,
            "client_id": client_id,
            "requester_worker_id": proxy_server.worker_id,
            "timestamp": time.time()
        }

        proxy_server.redis_client.publish(
            RedisKeys.events_channel(channel_id),
            json.dumps(stop_request)
        )
        return True
