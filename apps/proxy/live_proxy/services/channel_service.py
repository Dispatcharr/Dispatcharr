"""
Channel service layer for handling business logic related to channel operations.
This separates business logic from HTTP handling in views.
"""

import logging
import time
import json
import gevent
from django.db import close_old_connections
from apps.channels.models import Channel, Stream
from ..server import ProxyServer
from ..redis_keys import RedisKeys
from ..constants import EventType, ChannelState, ChannelMetadataField, REDIS_TTL_MEDIUM
from ..config_helper import ConfigHelper
from ..url_utils import get_stream_info_for_switch
from core.utils import log_system_event
from .log_parsers import LogParserFactory

logger = logging.getLogger("live_proxy")

STREAM_SWITCH_CONFIRM_TIMEOUT = 15  # transcode teardown can take several seconds
STREAM_SWITCH_POLL_INTERVAL = 0.1

class ChannelService:
    """Service class for channel operations"""

    @staticmethod
    def mark_channel_stopping(channel_id, broadcast=False):
        """Mark a channel as stopping in Redis so all uWSGI workers converge on teardown."""
        proxy_server = ProxyServer.get_instance()
        if not proxy_server.redis_client:
            return False

        try:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            if proxy_server.redis_client.exists(metadata_key):
                proxy_server.redis_client.hset(metadata_key, mapping={
                    ChannelMetadataField.STATE: ChannelState.STOPPING,
                    ChannelMetadataField.STATE_CHANGED_AT: str(time.time()),
                })

            stop_key = RedisKeys.channel_stopping(channel_id)
            proxy_server.redis_client.setex(stop_key, 60, "true")

            if broadcast:
                ChannelService._publish_channel_stop_event(channel_id)
            return True
        except Exception as e:
            logger.error(f"Error marking channel {channel_id} as stopping: {e}")
            return False

    @staticmethod
    def is_shutdown_pending(channel_id):
        """True while the post-disconnect shutdown delay has started but stop has not run."""
        proxy_server = ProxyServer.get_instance()
        if not proxy_server.redis_client:
            return False

        delay = ConfigHelper.channel_shutdown_delay()
        if delay <= 0:
            return False

        disconnect_value = proxy_server.redis_client.get(
            RedisKeys.last_client_disconnect(channel_id)
        )
        if not disconnect_value:
            return False

        try:
            disconnect_time = float(disconnect_value)
        except (ValueError, TypeError):
            return False

        return (time.time() - disconnect_time) < delay

    @staticmethod
    def is_channel_teardown_active(channel_id):
        """True when a coordinated channel stop is in progress (visible to all workers)."""
        proxy_server = ProxyServer.get_instance()
        if channel_id in proxy_server._stopping_channels:
            return True

        if not proxy_server.redis_client:
            return False

        if proxy_server.redis_client.exists(RedisKeys.channel_stopping(channel_id)):
            return True

        metadata_key = RedisKeys.channel_metadata(channel_id)
        state = proxy_server.redis_client.hget(metadata_key, ChannelMetadataField.STATE)
        if state:
            state_str = state.decode() if isinstance(state, bytes) else state
            if state_str == ChannelState.STOPPING:
                return True

        return False

    @staticmethod
    def is_channel_unavailable_for_new_clients(channel_id):
        """Reject new stream requests only while coordinated teardown is active."""
        return ChannelService.is_channel_teardown_active(channel_id)

    @staticmethod
    def cancel_pending_shutdown(channel_id):
        """
        Abort the post-disconnect grace timer when a client reconnects.

        Clears the disconnect timestamp and any leaked stopping markers. When
        upstream is still active but the last client released its profile slot
        during the grace window, re-reserve the slot from Redis metadata.

        Does not run during coordinated stop_channel() — clearing teardown
        markers mid-stop would leave clients attached to upstream that is
        about to be torn down.
        """
        proxy_server = ProxyServer.get_instance()
        if not proxy_server.redis_client:
            return False

        if channel_id in proxy_server._stopping_channels:
            return False

        disconnect_key = RedisKeys.last_client_disconnect(channel_id)
        had_pending = bool(proxy_server.redis_client.exists(disconnect_key))
        in_grace = had_pending or ChannelService.is_shutdown_pending(channel_id)

        if not in_grace:
            return False

        try:
            proxy_server.redis_client.delete(disconnect_key)

            metadata_key = RedisKeys.channel_metadata(channel_id)
            state = proxy_server.redis_client.hget(
                metadata_key, ChannelMetadataField.STATE
            )
            if state:
                state_str = state.decode() if isinstance(state, bytes) else state
                if state_str == ChannelState.STOPPING:
                    proxy_server.redis_client.hset(metadata_key, mapping={
                        ChannelMetadataField.STATE: ChannelState.ACTIVE,
                        ChannelMetadataField.STATE_CHANGED_AT: str(time.time()),
                    })

            stop_key = RedisKeys.channel_stopping(channel_id)
            if proxy_server.redis_client.exists(stop_key):
                proxy_server.redis_client.delete(stop_key)

            if ChannelService._channel_proxy_is_active(
                proxy_server.redis_client, channel_id
            ):
                from apps.channels.models import Channel

                channel = Channel.objects.filter(uuid=channel_id).first()
                if channel and not proxy_server.redis_client.get(
                    f"channel_stream:{channel.id}"
                ):
                    sid, pid, error, slot_reserved = channel.get_stream()
                    if error:
                        logger.warning(
                            f"Could not re-reserve stream for {channel_id} "
                            f"after shutdown cancel: {error}"
                        )
                    elif slot_reserved and sid and pid:
                        proxy_server.redis_client.hset(metadata_key, mapping={
                            ChannelMetadataField.STREAM_ID: str(sid),
                            ChannelMetadataField.M3U_PROFILE: str(pid),
                        })
                        logger.info(
                            f"Re-reserved profile slot for {channel_id} "
                            f"(stream={sid}, profile={pid})"
                        )
        finally:
            close_old_connections()

        return True

    @staticmethod
    def _channel_proxy_is_active(redis_client, channel_id):
        """True when live proxy metadata shows this channel is still running."""
        metadata_key = RedisKeys.channel_metadata(channel_id)
        if not redis_client.exists(metadata_key):
            return False
        state = redis_client.hget(metadata_key, ChannelMetadataField.STATE)
        if state is None:
            return False
        if isinstance(state, bytes):
            state = state.decode()
        return state in (
            ChannelState.ACTIVE,
            ChannelState.WAITING_FOR_CLIENTS,
            ChannelState.BUFFERING,
            ChannelState.INITIALIZING,
            ChannelState.CONNECTING,
        )

    @staticmethod
    def promote_channel_when_buffer_ready(channel_id):
        """
        Promote channel state once the initial buffer threshold is met.

        - connecting/initializing + buffer ready + clients -> active
        - connecting/initializing + buffer ready + no clients -> waiting_for_clients
        - waiting_for_clients + clients -> active

        Returns the resulting state, or None when no promotion applies.
        """
        proxy_server = ProxyServer.get_instance()
        redis_client = proxy_server.redis_client
        if not redis_client:
            return None

        metadata_key = RedisKeys.channel_metadata(channel_id)
        state_raw = redis_client.hget(metadata_key, ChannelMetadataField.STATE)
        if not state_raw:
            return None

        state = state_raw.decode() if isinstance(state_raw, bytes) else state_raw
        if state == ChannelState.ACTIVE:
            return ChannelState.ACTIVE

        if state == ChannelState.WAITING_FOR_CLIENTS:
            ready_raw = redis_client.hget(
                metadata_key, ChannelMetadataField.CONNECTION_READY_TIME
            )
            if not ready_raw:
                return None
            client_count = redis_client.scard(RedisKeys.clients(channel_id)) or 0
            if client_count <= 0:
                return ChannelState.WAITING_FOR_CLIENTS
            proxy_server.update_channel_state(
                channel_id,
                ChannelState.ACTIVE,
                {"clients_at_activation": str(client_count)},
            )
            return ChannelState.ACTIVE

        if state not in (ChannelState.INITIALIZING, ChannelState.CONNECTING):
            return None

        try:
            buffer_index = int(redis_client.get(RedisKeys.buffer_index(channel_id)) or 0)
        except (TypeError, ValueError):
            buffer_index = 0

        chunks_needed = ConfigHelper.initial_behind_chunks()
        if buffer_index < chunks_needed:
            return None

        client_count = redis_client.scard(RedisKeys.clients(channel_id)) or 0
        new_state = (
            ChannelState.ACTIVE if client_count > 0 else ChannelState.WAITING_FOR_CLIENTS
        )
        current_time = str(time.time())
        extra = {
            ChannelMetadataField.CONNECTION_READY_TIME: current_time,
            ChannelMetadataField.BUFFER_CHUNKS: str(buffer_index),
        }
        if new_state == ChannelState.ACTIVE:
            extra["clients_at_activation"] = str(client_count)

        proxy_server.update_channel_state(channel_id, new_state, extra)
        logger.info(
            f"Channel {channel_id} buffer ready ({buffer_index}/{chunks_needed} chunks) "
            f"-> {new_state} (clients={client_count})"
        )
        return new_state

    @staticmethod
    def initialize_channel(channel_id, stream_url, user_agent, transcode=False, stream_profile_value=None, stream_id=None, m3u_profile_id=None, channel_name=None, stream_name=None):
        """
        Initialize a channel with the given parameters.

        Args:
            channel_id: UUID of the channel
            stream_url: URL of the stream
            user_agent: User agent for the stream connection
            transcode: Whether to transcode the stream
            stream_profile_value: Stream profile value to store in metadata
            stream_id: ID of the stream being used
            m3u_profile_id: ID of the M3U profile being used
            channel_name: Channel name (avoids DB lookup if already known)
            stream_name: Stream name (avoids DB lookup if already known)

        Returns:
            bool: Success status
        """
        proxy_server = ProxyServer.get_instance()

        try:
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
                    proxy_server.redis_client.expire(metadata_key, REDIS_TTL_MEDIUM)
                    logger.info(f"Created initial metadata with stream_id {stream_id} for channel {channel_id}")

                # Verify the stream_id was set
                stream_id_value = proxy_server.redis_client.hget(metadata_key, ChannelMetadataField.STREAM_ID)
                if stream_id_value:
                    logger.debug(f"Verified stream_id {stream_id_value} is now set in Redis")
                else:
                    logger.error(f"Failed to set stream_id {stream_id} in Redis before initialization")

            if not channel_name:
                try:
                    channel_name = Channel.objects.filter(uuid=channel_id).values_list(
                        'name', flat=True
                    ).first()
                except Exception as e:
                    logger.warning(f"Failed to load channel name for {channel_id}: {e}")
            if not stream_name and stream_id:
                try:
                    stream_name = Stream.objects.filter(id=stream_id).values_list(
                        'name', flat=True
                    ).first()
                except Exception as e:
                    logger.warning(f"Failed to load stream name for {stream_id}: {e}")

            # Now proceed with channel initialization
            success = proxy_server.initialize_channel(
                stream_url,
                channel_id,
                user_agent,
                transcode,
                stream_id,
                channel_name=channel_name,
                stream_name=stream_name,
            )

            # Store additional metadata if initialization was successful
            if success and proxy_server.redis_client:
                metadata_key = RedisKeys.channel_metadata(channel_id)
                update_data = {}
                if stream_profile_value:
                    update_data[ChannelMetadataField.STREAM_PROFILE] = stream_profile_value
                if stream_id:
                    update_data[ChannelMetadataField.STREAM_ID] = str(stream_id)
                if m3u_profile_id:
                    update_data[ChannelMetadataField.M3U_PROFILE] = str(m3u_profile_id)
                if channel_name:
                    update_data[ChannelMetadataField.CHANNEL_NAME] = channel_name
                if stream_name:
                    update_data[ChannelMetadataField.STREAM_NAME] = stream_name

                if update_data:
                    proxy_server.redis_client.hset(metadata_key, mapping=update_data)

            return success
        finally:
            close_old_connections()

    @staticmethod
    def change_stream_url(channel_id, new_url=None, user_agent=None, target_stream_id=None, m3u_profile_id=None, stream_name=None):
        """
        Change the URL of an existing stream.

        Args:
            channel_id: UUID of the channel
            new_url: New stream URL (optional if target_stream_id is provided)
            user_agent: Optional user agent to update
            target_stream_id: Optional target stream ID to switch to
            m3u_profile_id: Optional M3U profile ID to update

        Returns:
            dict: Result information including success status and diagnostics
        """
        proxy_server = ProxyServer.get_instance()

        # If no direct URL is provided but a target stream is, get URL from target stream
        stream_id = None
        if not new_url and target_stream_id:
            stream_info = get_stream_info_for_switch(channel_id, target_stream_id)
            if 'error' in stream_info:
                return {
                    'status': 'error',
                    'message': stream_info['error']
                }
            new_url = stream_info['url']
            user_agent = stream_info['user_agent']
            stream_id = target_stream_id
            stream_name = stream_info.get('stream_name')
            # Extract M3U profile ID from stream info if available
            if 'm3u_profile_id' in stream_info:
                m3u_profile_id = stream_info['m3u_profile_id']
                logger.info(f"Found M3U profile ID {m3u_profile_id} for stream ID {stream_id}")
        elif target_stream_id:
            # If we have both URL and target_stream_id, use the target_stream_id
            stream_id = target_stream_id

        # Check if channel exists
        in_local_managers = channel_id in proxy_server.stream_managers
        in_local_buffers = channel_id in proxy_server.stream_buffers

        # Check Redis for keys
        redis_keys = None
        if proxy_server.redis_client:
            try:
                # This is inefficient but used for diagnostics - in production would use more targeted checks
                redis_keys = proxy_server.redis_client.keys(f"live:*:{channel_id}*")
                redis_keys = [k for k in redis_keys] if redis_keys else []
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

        # If we're the owner, update directly
        if proxy_server.am_i_owner(channel_id) and channel_id in proxy_server.stream_managers:
            logger.info(f"This worker is the owner, changing stream URL for channel {channel_id}")
            manager = proxy_server.stream_managers[channel_id]
            old_url = manager.url

            if new_url == old_url:
                # update_url() returns False for same URL; still success so metadata refreshes
                success = True
                logger.info(f"Channel {channel_id} already using URL {new_url}, refreshing metadata only")
            else:
                # Update the stream
                success = manager.update_url(new_url, stream_id, m3u_profile_id)
                logger.info(f"Stream URL changed from {old_url} to {new_url}, result: {success}")

            # Update Redis metadata based on the actual outcome.
            # On success, write the new values. On failure, restore whatever URL
            # the manager will actually reconnect to (may be old_url if the
            # exception happened before self.url was reassigned, or new_url if it
            # happened after) so Redis never describes a URL that isn't in use.
            if proxy_server.redis_client:
                try:
                    if success:
                        ChannelService._update_channel_metadata(channel_id, new_url, user_agent, stream_id, m3u_profile_id, stream_name)
                    else:
                        ChannelService._update_channel_metadata(channel_id, manager.url, user_agent)
                    result['metadata_updated'] = True
                except Exception as e:
                    logger.error(f"Error updating Redis metadata: {e}", exc_info=True)
                    result['metadata_updated'] = False

            result.update({
                'direct_update': True,
                'success': success,
                'worker_id': proxy_server.worker_id
            })
        else:
            # Not the owner: publish the switch event. The owner will update metadata
            # after the actual switch attempt succeeds (or roll back on failure).
            # All needed info (url, user_agent, stream_id, m3u_profile_id) is carried
            # in the pubsub message, so there is no reason to pre-write metadata here.
            logger.debug(f"This worker is not the owner, publishing stream switch event for channel {channel_id}")
            if proxy_server.redis_client:
                status_key = RedisKeys.switch_status(channel_id)
                try:
                    # Clear stale status from a prior switch
                    proxy_server.redis_client.delete(status_key)
                except Exception as e:
                    logger.warning(f"Could not clear switch status for channel {channel_id}: {e}")

                ChannelService._publish_stream_switch_event(
                    channel_id, new_url, user_agent, stream_id, m3u_profile_id, stream_name
                )

                switch_status = None
                deadline = time.time() + STREAM_SWITCH_CONFIRM_TIMEOUT
                while time.time() < deadline:
                    try:
                        switch_status = proxy_server.redis_client.get(status_key)
                    except Exception as e:
                        logger.warning(f"Error polling switch status for channel {channel_id}: {e}")
                        switch_status = None
                        break
                    if switch_status in ("switched", "failed"):
                        break
                    gevent.sleep(STREAM_SWITCH_POLL_INTERVAL)

                result.update({
                    'direct_update': False,
                    'event_published': True,
                    'worker_id': proxy_server.worker_id
                })

                if switch_status == "switched":
                    result['success'] = True
                elif switch_status == "failed":
                    result['success'] = False
                    result['message'] = 'Owner worker failed to switch stream'
                else:
                    result['success'] = False
                    result['confirmed'] = False
                    result['message'] = (
                        f'Stream switch was not confirmed by the channel owner '
                        f'within {STREAM_SWITCH_CONFIRM_TIMEOUT}s'
                    )
                    logger.error(
                        f"Stream switch for channel {channel_id} not confirmed within "
                        f"{STREAM_SWITCH_CONFIRM_TIMEOUT}s (owner may be down or still switching)"
                    )
            else:
                result.update({
                    'direct_update': False,
                    'event_published': False,
                    'success': False,
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
        proxy_server = ProxyServer.get_instance()

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
                if metadata and 'state' in metadata:
                    channel_info = {"state": metadata['state']}
            except Exception as e:
                logger.error(f"Error fetching channel state: {e}")

        # Mark stopping in Redis and notify all workers before local teardown.
        # stop_channel() releases profile slots via _clean_redis_keys() before Redis deletion.
        if proxy_server.redis_client:
            ChannelService.mark_channel_stopping(channel_id, broadcast=True)
            logger.info(f"Marked channel {channel_id} stopping and broadcast stop to all workers")
        local_result = proxy_server.stop_channel(channel_id)

        return {
            'status': 'success',
            'message': 'Channel stop request sent',
            'channel_id': channel_id,
            'previous_state': channel_info,
            'model_released': bool(local_result),
            'local_stop_result': local_result
        }

    @staticmethod
    def stop_channels(channel_uuids):
        """Best-effort stop for each channel UUID. Never raises.

        Used before optional/manual deletes and automated M3U cleanup so proxy
        teardown runs outside Django's delete atomic block.
        """
        for channel_uuid in channel_uuids:
            if not channel_uuid:
                continue
            try:
                ChannelService.stop_channel(str(channel_uuid))
            except Exception as e:
                logger.warning(
                    "Failed to stop proxy session for channel %s: %s",
                    channel_uuid,
                    e,
                )

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
        proxy_server = ProxyServer.get_instance()

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
        proxy_server = ProxyServer.get_instance()

        if not proxy_server.redis_client:
            return False, None, None, {"error": "Redis not available"}

        try:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            if not proxy_server.redis_client.exists(metadata_key):
                return False, None, None, {"error": "No channel metadata"}

            metadata = proxy_server.redis_client.hgetall(metadata_key)

            # Extract state and owner
            state = metadata.get(ChannelMetadataField.STATE, 'unknown')
            owner = metadata.get(ChannelMetadataField.OWNER, 'unknown')

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
                last_data_time = float(last_data)
                data_age = time.time() - last_data_time
                details["last_data_age"] = data_age

                # If no data for too long, consider invalid
                if data_age > 30:  # 30 seconds threshold
                    return False, state, owner, {"error": f"No data for {data_age:.1f}s", **details}

            return True, state, owner, details

        except Exception as e:
            logger.error(f"Error validating channel state: {e}", exc_info=True)
            return False, None, None, {"error": f"Exception: {str(e)}"}

    @staticmethod
    def parse_and_store_stream_info(channel_id, stream_info_line, stream_type="video", stream_id=None):
        """
        Parse stream info from FFmpeg/VLC/Streamlink logs and store in Redis/DB.
        Uses specialized parsers for each streaming tool.
        """
        try:
            # Use factory to parse the line based on stream type
            parsed_data = LogParserFactory.parse(stream_type, stream_info_line)

            if not parsed_data:
                return

            # Update Redis and database with parsed data
            ChannelService._update_stream_info_in_redis(
                channel_id,
                parsed_data.get('video_codec'),
                parsed_data.get('resolution'),
                parsed_data.get('width'),
                parsed_data.get('height'),
                parsed_data.get('source_fps'),
                parsed_data.get('pixel_format'),
                parsed_data.get('video_bitrate'),
                parsed_data.get('audio_codec'),
                parsed_data.get('sample_rate'),
                parsed_data.get('audio_channels'),
                parsed_data.get('audio_bitrate'),
                parsed_data.get('stream_type')
            )

            if stream_id:
                ChannelService._update_stream_stats_in_db(
                    stream_id,
                    video_codec=parsed_data.get('video_codec'),
                    resolution=parsed_data.get('resolution'),
                    source_fps=parsed_data.get('source_fps'),
                    pixel_format=parsed_data.get('pixel_format'),
                    video_bitrate=parsed_data.get('video_bitrate'),
                    audio_codec=parsed_data.get('audio_codec'),
                    sample_rate=parsed_data.get('sample_rate'),
                    audio_channels=parsed_data.get('audio_channels'),
                    audio_bitrate=parsed_data.get('audio_bitrate'),
                    stream_type=parsed_data.get('stream_type')
                )

        except Exception as e:
            logger.debug(f"Error parsing {stream_type} stream info: {e}")

    @staticmethod
    def _update_stream_info_in_redis(channel_id, codec, resolution, width, height, fps, pixel_format, video_bitrate, audio_codec=None, sample_rate=None, channels=None, audio_bitrate=None, input_format=None):
        """Update stream info in Redis metadata"""
        try:
            proxy_server = ProxyServer.get_instance()
            if not proxy_server.redis_client:
                return False

            metadata_key = RedisKeys.channel_metadata(channel_id)
            update_data = {
                ChannelMetadataField.STREAM_INFO_UPDATED: str(time.time())
            }

            # Video info
            if codec is not None:
                update_data[ChannelMetadataField.VIDEO_CODEC] = str(codec)

            if resolution is not None:
                update_data[ChannelMetadataField.RESOLUTION] = str(resolution)

            if width is not None:
                update_data[ChannelMetadataField.WIDTH] = str(width)

            if height is not None:
                update_data[ChannelMetadataField.HEIGHT] = str(height)

            if fps is not None:
                update_data[ChannelMetadataField.SOURCE_FPS] = str(round(fps, 2))

            if pixel_format is not None:
                update_data[ChannelMetadataField.PIXEL_FORMAT] = str(pixel_format)

            if video_bitrate is not None:
                update_data[ChannelMetadataField.VIDEO_BITRATE] = str(round(video_bitrate, 1))

            # Audio info
            if audio_codec is not None:
                update_data[ChannelMetadataField.AUDIO_CODEC] = str(audio_codec)

            if sample_rate is not None:
                update_data[ChannelMetadataField.SAMPLE_RATE] = str(sample_rate)

            if channels is not None:
                update_data[ChannelMetadataField.AUDIO_CHANNELS] = str(channels)

            if audio_bitrate is not None:
                update_data[ChannelMetadataField.AUDIO_BITRATE] = str(round(audio_bitrate, 1))
            if input_format is not None:
                update_data[ChannelMetadataField.STREAM_TYPE] = str(input_format)

            proxy_server.redis_client.hset(metadata_key, mapping=update_data)
            return True

        except Exception as e:
            logger.error(f"Error updating stream info in Redis: {e}")
            return False

    @staticmethod
    def _update_stream_stats_in_db(stream_id, **stats):
        """Update stream stats in database"""
        try:
            from apps.channels.models import Stream
            from django.utils import timezone

            stream = Stream.objects.get(id=stream_id)

            # Get existing stats or create new dict
            current_stats = stream.stream_stats or {}

            # Update with new stats
            for key, value in stats.items():
                if value is not None:
                    current_stats[key] = value

            # Save updated stats and timestamp
            stream.stream_stats = current_stats
            stream.stream_stats_updated_at = timezone.now()
            stream.save(update_fields=['stream_stats', 'stream_stats_updated_at'])

            logger.debug(f"Updated stream stats in database for stream {stream_id}: {stats}")
            return True

        except Exception as e:
            logger.error(f"Error updating stream stats in database for stream {stream_id}: {e}")
            return False

        finally:
            # Release geventpool checkout after ORM.
            close_old_connections()

    # Helper methods for Redis operations

    @staticmethod
    def _update_channel_metadata(channel_id, url, user_agent=None, stream_id=None, m3u_profile_id=None, stream_name=None):
        """Update channel metadata in Redis"""
        try:
            proxy_server = ProxyServer.get_instance()

            if not proxy_server.redis_client:
                return False

            metadata_key = RedisKeys.channel_metadata(channel_id)

            # First check if the key exists and what type it is
            key_type = proxy_server.redis_client.type(metadata_key)
            logger.debug(f"Redis key {metadata_key} is of type: {key_type}")

            # Build metadata update dict
            metadata = {ChannelMetadataField.URL: url}
            if user_agent:
                metadata[ChannelMetadataField.USER_AGENT] = user_agent
            if stream_id:
                metadata[ChannelMetadataField.STREAM_ID] = str(stream_id)
                if not stream_name:
                    try:
                        from apps.channels.models import Stream
                        stream_name = Stream.objects.filter(id=stream_id).values_list('name', flat=True).first()
                    except Exception as e:
                        logger.warning(f"Failed to update stream name in Redis for stream {stream_id}: {e}")
                if stream_name:
                    metadata[ChannelMetadataField.STREAM_NAME] = stream_name
            if m3u_profile_id:
                metadata[ChannelMetadataField.M3U_PROFILE] = str(m3u_profile_id)

            # Also update the stream switch time field
            metadata[ChannelMetadataField.STREAM_SWITCH_TIME] = str(time.time())

            # Use the appropriate method based on the key type
            if key_type == 'hash':
                proxy_server.redis_client.hset(metadata_key, mapping=metadata)
            elif key_type == 'none':  # Key doesn't exist yet
                proxy_server.redis_client.hset(metadata_key, mapping=metadata)
            else:
                # If key exists with wrong type, delete it and recreate
                proxy_server.redis_client.delete(metadata_key)
                proxy_server.redis_client.hset(metadata_key, mapping=metadata)

            # Set switch request flag to ensure all workers see it
            switch_key = RedisKeys.switch_request(channel_id)
            proxy_server.redis_client.setex(switch_key, 30, url)  # 30 second TTL

            logger.debug(f"Updated metadata for channel {channel_id} in Redis")
            return True
        finally:
            close_old_connections()

    @staticmethod
    def _publish_stream_switch_event(channel_id, new_url, user_agent=None, stream_id=None, m3u_profile_id=None, stream_name=None):
        """Publish a stream switch event to Redis pubsub"""
        proxy_server = ProxyServer.get_instance()

        if not proxy_server.redis_client:
            return False

        switch_request = {
            "event": EventType.STREAM_SWITCH,
            "channel_id": str(channel_id),
            "url": new_url,
            "user_agent": user_agent,
            "stream_id": stream_id,
            "m3u_profile_id": m3u_profile_id,
            "stream_name": stream_name,
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
        proxy_server = ProxyServer.get_instance()

        if not proxy_server.redis_client:
            return False

        stop_request = {
            "event": EventType.CHANNEL_STOP,
            "channel_id": str(channel_id),
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
        proxy_server = ProxyServer.get_instance()

        if not proxy_server.redis_client:
            return False

        stop_request = {
            "event": EventType.CLIENT_STOP,
            "channel_id": str(channel_id),
            "client_id": client_id,
            "requester_worker_id": proxy_server.worker_id,
            "timestamp": time.time()
        }

        proxy_server.redis_client.publish(
            RedisKeys.events_channel(channel_id),
            json.dumps(stop_request)
        )
        return True
