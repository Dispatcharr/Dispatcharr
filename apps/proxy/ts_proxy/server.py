"""
Transport Stream (TS) Proxy Server
Handles live TS stream proxying with support for:
- Stream switching
- Buffer management
- Multiple client connections
- Connection state tracking
"""

import threading
import logging
import socket
import random
import time
import sys
import os
import json
import gevent  # Add gevent import
from typing import Dict, Optional, Set
from apps.proxy.config import TSConfig as Config
from apps.channels.models import Channel, Stream
from core.utils import RedisClient, log_system_event
from redis.exceptions import ConnectionError, TimeoutError
from .stream_manager import StreamManager
from .stream_buffer import StreamBuffer
from .client_manager import ClientManager
from .redis_keys import RedisKeys
from .constants import ChannelState, EventType, StreamType
from .config_helper import ConfigHelper
from .utils import get_logger

logger = get_logger()

class ProxyServer:
    """Manages TS proxy server instance with worker coordination"""
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            from .server import ProxyServer
            from .stream_manager import StreamManager
            from .stream_buffer import StreamBuffer
            from .client_manager import ClientManager

            cls._instance = ProxyServer()

        return cls._instance

    def __init__(self):
        """Initialize proxy server with worker identification"""
        self.stream_managers = {}
        self.stream_buffers = {}
        self.client_managers = {}

        # Generate a unique worker ID
        import socket
        import os
        pid = os.getpid()
        hostname = socket.gethostname()
        self.worker_id = f"{hostname}:{pid}"

        # Connect to Redis - use dedicated client for proxy
        self.redis_client = None
        self.redis_connection_attempts = 0
        self.redis_max_retries = 3
        self.redis_retry_interval = 5  # seconds

        try:
            # Use dedicated Redis client for proxy
            self.redis_client = RedisClient.get_client()
            if self.redis_client is not None:
                logger.info(f"Using dedicated Redis client for proxy server")
                logger.info(f"Worker ID: {self.worker_id}")
            else:
                # Fall back to direct connection with retry
                self._setup_redis_connection()

        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            self.redis_client = None

        # Start cleanup thread
        self.cleanup_interval = getattr(Config, 'CLEANUP_INTERVAL', 60)
        self._start_cleanup_thread()

        # Start event listener for Redis pubsub messages
        self._start_event_listener()

    def _setup_redis_connection(self):
        """Setup Redis connection with retry logic"""
        # Try to use get_redis_client utility instead of direct connection
        self.redis_client = RedisClient.get_client(max_retries=self.redis_max_retries,
                                            retry_interval=self.redis_retry_interval)
        if self.redis_client:
            logger.info(f"Successfully connected to Redis using utility function")
            logger.info(f"Worker ID: {self.worker_id}")
        else:
            logger.error(f"Failed to connect to Redis after {self.redis_max_retries} attempts")

    def _execute_redis_command(self, command_func, *args, **kwargs):
        """Execute Redis command with error handling and reconnection logic"""
        if not self.redis_client:
            return None

        try:
            return command_func(*args, **kwargs)
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis connection lost: {e}. Attempting to reconnect...")
            try:
                # Try to reconnect
                self.redis_connection_attempts = 0
                self._setup_redis_connection()
                if self.redis_client:
                    # Retry the command once
                    return command_func(*args, **kwargs)
            except Exception as reconnect_error:
                logger.error(f"Failed to reconnect to Redis: {reconnect_error}")
            return None
        except Exception as e:
            logger.error(f"Redis command error: {e}")
            return None

    def _start_event_listener(self):
        """Listen for events from other workers"""
        if not self.redis_client:
            return

        def event_listener():
            retry_count = 0
            max_retries = 10
            base_retry_delay = 1  # Start with 1 second delay
            max_retry_delay = 30  # Cap at 30 seconds
            pubsub_client = None
            pubsub = None

            while True:
                try:
                    # Use dedicated PubSub client for event listener
                    pubsub_client = RedisClient.get_pubsub_client()
                    if pubsub_client:
                        logger.info("Using dedicated Redis PubSub client for event listener")
                    else:
                        # Fall back to creating a dedicated client if utility fails
                        logger.warning("Utility function for PubSub client failed, creating direct connection")
                        from django.conf import settings
                        import redis

                        redis_host = os.environ.get("REDIS_HOST", getattr(settings, 'REDIS_HOST', 'localhost'))
                        redis_port = int(os.environ.get("REDIS_PORT", getattr(settings, 'REDIS_PORT', 6379)))
                        redis_db = int(os.environ.get("REDIS_DB", getattr(settings, 'REDIS_DB', 0)))

                        pubsub_client = redis.Redis(
                            host=redis_host,
                            port=redis_port,
                            db=redis_db,
                            socket_timeout=60,
                            socket_connect_timeout=10,
                            socket_keepalive=True,
                            health_check_interval=30
                        )
                        logger.info("Created fallback Redis PubSub client for event listener")

                    # Test connection before subscribing
                    pubsub_client.ping()

                    # Create a pubsub instance from the client
                    pubsub = pubsub_client.pubsub()
                    pubsub.psubscribe("ts_proxy:events:*")

                    logger.info(f"Started Redis event listener for client activity")

                    # Reset retry count on successful connection
                    retry_count = 0

                    for message in pubsub.listen():
                        if message["type"] != "pmessage":
                            continue

                        try:
                            channel = message["channel"].decode("utf-8")
                            data = json.loads(message["data"].decode("utf-8"))

                            event_type = data.get("event")
                            channel_id = data.get("channel_id")

                            if channel_id and event_type:
                                # For owner, update client status immediately
                                if self.am_i_owner(channel_id):
                                    if event_type == EventType.CLIENT_CONNECTED:
                                        logger.debug(f"Owner received {EventType.CLIENT_CONNECTED} event for channel {channel_id}")
                                        # Reset any disconnect timer
                                        disconnect_key = RedisKeys.last_client_disconnect(channel_id)
                                        self.redis_client.delete(disconnect_key)

                                    elif event_type == EventType.CLIENT_DISCONNECTED:
                                        client_id = data.get("client_id")
                                        worker_id = data.get("worker_id")
                                        logger.debug(f"Owner received {EventType.CLIENT_DISCONNECTED} event for channel {channel_id}, client {client_id} from worker {worker_id}")
                                        # Delegate to dedicated method
                                        self.handle_client_disconnect(channel_id)


                                    elif event_type == EventType.STREAM_SWITCH:
                                        logger.info(f"Owner received {EventType.STREAM_SWITCH} request for channel {channel_id}")
                                        # Handle stream switch request
                                        new_url = data.get("url")
                                        user_agent = data.get("user_agent")

                                        if new_url and channel_id in self.stream_managers:
                                            # Update metadata in Redis
                                            if self.redis_client:
                                                metadata_key = RedisKeys.channel_metadata(channel_id)
                                                self.redis_client.hset(metadata_key, "url", new_url)
                                                if user_agent:
                                                    self.redis_client.hset(metadata_key, "user_agent", user_agent)

                                                # Set switch status
                                                status_key = RedisKeys.switch_status(channel_id)
                                                self.redis_client.set(status_key, "switching")

                                            # Perform the stream switch
                                            stream_manager = self.stream_managers[channel_id]
                                            success = stream_manager.update_url(new_url)

                                            if success:
                                                logger.info(f"Stream switch initiated for channel {channel_id}")

                                                # Publish confirmation
                                                switch_result = {
                                                    "event": EventType.STREAM_SWITCHED,  # Use constant instead of string
                                                    "channel_id": channel_id,
                                                    "success": True,
                                                    "url": new_url,
                                                    "timestamp": time.time()
                                                }
                                                self.redis_client.publish(
                                                    f"ts_proxy:events:{channel_id}",
                                                    json.dumps(switch_result)
                                                )

                                                # Update status
                                                if self.redis_client:
                                                    self.redis_client.set(status_key, "switched")
                                            else:
                                                logger.error(f"Failed to switch stream for channel {channel_id}")

                                                # Publish failure
                                                switch_result = {
                                                    "event": EventType.STREAM_SWITCHED,
                                                    "channel_id": channel_id,
                                                    "success": False,
                                                    "url": new_url,
                                                    "timestamp": time.time()
                                                }
                                                self.redis_client.publish(
                                                    f"ts_proxy:events:{channel_id}",
                                                    json.dumps(switch_result)
                                                )
                                    elif event_type == EventType.CHANNEL_STOP:
                                        logger.info(f"Received {EventType.CHANNEL_STOP} event for channel {channel_id}")
                                        # First mark channel as stopping in Redis
                                        if self.redis_client:
                                            # Set stopping state in metadata
                                            metadata_key = RedisKeys.channel_metadata(channel_id)
                                            if self.redis_client.exists(metadata_key):
                                                self.redis_client.hset(metadata_key, mapping={
                                                    "state": ChannelState.STOPPING,
                                                    "state_changed_at": str(time.time())
                                                })

                                        # If we have local resources for this channel, clean them up
                                        if channel_id in self.stream_buffers or channel_id in self.client_managers:
                                            # Use existing stop_channel method
                                            logger.info(f"Stopping local resources for channel {channel_id}")
                                            self.stop_channel(channel_id)

                                        # Acknowledge stop by publishing a response
                                        stop_response = {
                                            "event": EventType.CHANNEL_STOPPED,
                                            "channel_id": channel_id,
                                            "worker_id": self.worker_id,
                                            "timestamp": time.time()
                                        }
                                        self.redis_client.publish(
                                            f"ts_proxy:events:{channel_id}",
                                            json.dumps(stop_response)
                                        )
                                    elif event_type == EventType.CLIENT_STOP:
                                        client_id = data.get("client_id")
                                        if client_id and channel_id:
                                            logger.info(f"Received request to stop client {client_id} on channel {channel_id}")

                                            # Both remove from client manager AND set a key for the generator to detect
                                            if channel_id in self.client_managers:
                                                client_manager = self.client_managers[channel_id]
                                                if client_id in client_manager.clients:
                                                    client_manager.remove_client(client_id)
                                                    logger.info(f"Removed client {client_id} from client manager")

                                            # Set a Redis key for the generator to detect
                                            if self.redis_client:
                                                stop_key = RedisKeys.client_stop(channel_id, client_id)
                                                self.redis_client.setex(stop_key, 30, "true")  # 30 second TTL
                                                logger.info(f"Set stop key for client {client_id}")
                        except Exception as e:
                            logger.error(f"Error processing event message: {e}")

                except (ConnectionError, TimeoutError) as e:
                    # Calculate exponential backoff with jitter
                    retry_count += 1
                    delay = min(base_retry_delay * (2 ** (retry_count - 1)), max_retry_delay)
                    # Add some randomness to prevent thundering herd
                    jitter = random.uniform(0, 0.5 * delay)
                    final_delay = delay + jitter

                    logger.error(f"Error in event listener: {e}. Retrying in {final_delay:.1f}s (attempt {retry_count})")
                    gevent.sleep(final_delay)  # REPLACE: time.sleep(final_delay)

                except Exception as e:
                    logger.error(f"Error in event listener: {e}")
                    # Add a short delay to prevent rapid retries on persistent errors
                    gevent.sleep(5)  # REPLACE: time.sleep(5)

                finally:
                    # Always clean up PubSub connections in all error paths
                    try:
                        if pubsub:
                            pubsub.close()
                            pubsub = None
                    except Exception as e:
                        logger.debug(f"Error closing pubsub: {e}")

                    try:
                        if pubsub_client:
                            pubsub_client.close()
                            pubsub_client = None
                    except Exception as e:
                        logger.debug(f"Error closing pubsub_client: {e}")

        thread = threading.Thread(target=event_listener, daemon=True)
        thread.name = "redis-event-listener"
        thread.start()

    def get_channel_owner(self, channel_id):
        """Get the worker ID that owns this channel with proper error handling"""
        if not self.redis_client:
            return None

        try:
            lock_key = RedisKeys.channel_owner(channel_id)
            return self._execute_redis_command(
                lambda: self.redis_client.get(lock_key).decode('utf-8') if self.redis_client.get(lock_key) else None
            )
        except Exception as e:
            logger.error(f"Error getting channel owner: {e}")
            return None

    def am_i_owner(self, channel_id):
        """Check if this worker is the owner of the channel"""
        owner = self.get_channel_owner(channel_id)
        return owner == self.worker_id

    def try_acquire_ownership(self, channel_id, ttl=30):
        """Try to become the owner of this channel using proper locking"""
        if not self.redis_client:
            return True  # If no Redis, always become owner

        try:
            # Create a lock key with proper namespace
            lock_key = RedisKeys.channel_owner(channel_id)

            # Use Redis SETNX for atomic locking with error handling
            acquired = self._execute_redis_command(
                lambda: self.redis_client.setnx(lock_key, self.worker_id)
            )

            if acquired is None:  # Redis command failed
                logger.warning(f"Redis command failed during ownership acquisition - assuming ownership")
                return True

            # If acquired, set expiry to prevent orphaned locks
            if acquired:
                self._execute_redis_command(
                    lambda: self.redis_client.expire(lock_key, ttl)
                )
                logger.info(f"Worker {self.worker_id} acquired ownership of channel {channel_id}")
                return True

            # If not acquired, check if we already own it (might be a retry)
            current_owner = self._execute_redis_command(
                lambda: self.redis_client.get(lock_key)
            )
            if current_owner and current_owner.decode('utf-8') == self.worker_id:
                # Refresh TTL
                self._execute_redis_command(
                    lambda: self.redis_client.expire(lock_key, ttl)
                )
                logger.info(f"Worker {self.worker_id} refreshed ownership of channel {channel_id}")
                return True

            # Someone else owns it
            return False

        except Exception as e:
            logger.error(f"Error acquiring channel ownership: {e}")
            return False

    def release_ownership(self, channel_id):
        """Release ownership of this channel safely"""
        if not self.redis_client:
            return

        try:
            lock_key = RedisKeys.channel_owner(channel_id)

            # Only delete if we're the current owner to prevent race conditions
            current = self.redis_client.get(lock_key)
            if current and current.decode('utf-8') == self.worker_id:
                self.redis_client.delete(lock_key)
                logger.info(f"Released ownership of channel {channel_id}")

                # Also ensure channel stopping key is set to signal clients
                stop_key = RedisKeys.channel_stopping(channel_id)
                self.redis_client.setex(stop_key, 30, "true")
                logger.info(f"Set stopping signal for channel {channel_id} clients")

        except Exception as e:
            logger.error(f"Error releasing channel ownership: {e}")

    def extend_ownership(self, channel_id, ttl=30):
        """Extend ownership lease with grace period"""
        if not self.redis_client:
            return False

        try:
            lock_key = RedisKeys.channel_owner(channel_id)
            current = self.redis_client.get(lock_key)

            # Only extend if we're still the owner
            if current and current.decode('utf-8') == self.worker_id:
                self.redis_client.expire(lock_key, ttl)
                return True
            return False
        except Exception as e:
            logger.error(f"Error extending ownership: {e}")
            return False

    def initialize_channel(self, url, channel_id, user_agent=None, transcode=False, stream_id=None):
        """Initialize a channel without redundant active key"""
        try:
            # IMPROVED: First check if channel is already being initialized by another process
            if self.redis_client:
                metadata_key = RedisKeys.channel_metadata(channel_id)
                if self.redis_client.exists(metadata_key):
                    metadata = self.redis_client.hgetall(metadata_key)
                    if b'state' in metadata:
                        state = metadata[b'state'].decode('utf-8')
                        active_states = [ChannelState.INITIALIZING, ChannelState.CONNECTING,
                                        ChannelState.WAITING_FOR_CLIENTS, ChannelState.ACTIVE, ChannelState.BUFFERING]
                        if state in active_states:
                            logger.info(f"Channel {channel_id} already being initialized with state {state}")
                            # Create buffer and client manager only if we don't have them
                            if channel_id not in self.stream_buffers:
                                self.stream_buffers[channel_id] = StreamBuffer(channel_id, redis_client=self.redis_client)
                            if channel_id not in self.client_managers:
                                self.client_managers[channel_id] = ClientManager(
                                    channel_id,
                                    redis_client=self.redis_client,
                                    worker_id=self.worker_id
                                )
                            return True

            # Create buffer and client manager instances (or reuse if they exist)
            if channel_id not in self.stream_buffers:
                buffer = StreamBuffer(channel_id, redis_client=self.redis_client)
                self.stream_buffers[channel_id] = buffer

            if channel_id not in self.client_managers:
                client_manager = ClientManager(
                    channel_id,
                    redis_client=self.redis_client,
                    worker_id=self.worker_id
                )
                self.client_managers[channel_id] = client_manager

            # IMPROVED: Set initializing state in Redis BEFORE any other operations
            if self.redis_client:
                # Set early initialization state to prevent race conditions
                metadata_key = RedisKeys.channel_metadata(channel_id)
                initial_metadata = {
                    "state": ChannelState.INITIALIZING,
                    "init_time": str(time.time()),
                    "owner": self.worker_id
                }
                if stream_id:
                    initial_metadata["stream_id"] = str(stream_id)
                self.redis_client.hset(metadata_key, mapping=initial_metadata)
                logger.info(f"Set early initializing state for channel {channel_id}")

            # Get channel URL from Redis if available
            channel_url = url
            channel_user_agent = user_agent
            channel_stream_id = stream_id  # Store the stream ID

            # First check if channel metadata already exists
            existing_metadata = None
            metadata_key = RedisKeys.channel_metadata(channel_id)

            if self.redis_client:
                existing_metadata = self.redis_client.hgetall(metadata_key)

                # If no url was passed, try to get from Redis
                if not url and existing_metadata:
                    url_bytes = existing_metadata.get(b'url')
                    if url_bytes:
                        channel_url = url_bytes.decode('utf-8')

                    ua_bytes = existing_metadata.get(b'user_agent')
                    if ua_bytes:
                        channel_user_agent = ua_bytes.decode('utf-8')

                # Get stream ID from metadata if not provided
                if not channel_stream_id and b'stream_id' in existing_metadata:
                    try:
                        channel_stream_id = int(existing_metadata[b'stream_id'].decode('utf-8'))
                        logger.debug(f"Found stream_id {channel_stream_id} in metadata for channel {channel_id}")
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Could not parse stream_id from metadata: {e}")

            # Check if channel is already owned
            current_owner = self.get_channel_owner(channel_id)

            # Exit early if another worker owns the channel
            if current_owner and current_owner != self.worker_id:
                logger.info(f"Channel {channel_id} already owned by worker {current_owner}")
                logger.info(f"This worker ({self.worker_id}) will read from Redis buffer only")

                # Create buffer but not stream manager (only if not already exists)
                if channel_id not in self.stream_buffers:
                    buffer = StreamBuffer(channel_id=channel_id, redis_client=self.redis_client)
                    self.stream_buffers[channel_id] = buffer

                # Create client manager with channel_id and redis_client (only if not already exists)
                if channel_id not in self.client_managers:
                    client_manager = ClientManager(channel_id=channel_id, redis_client=self.redis_client, worker_id=self.worker_id)
                    self.client_managers[channel_id] = client_manager

                return True

            # Only continue with full initialization if URL is provided
            # or we can get it from Redis
            if not channel_url:
                logger.error(f"No URL available for channel {channel_id}")
                return False

            # Try to acquire ownership with Redis locking
            if not self.try_acquire_ownership(channel_id):
                # Another worker just acquired ownership
                logger.info(f"Another worker just acquired ownership of channel {channel_id}")

                # Create buffer but not stream manager (only if not already exists)
                if channel_id not in self.stream_buffers:
                    buffer = StreamBuffer(channel_id=channel_id, redis_client=self.redis_client)
                    self.stream_buffers[channel_id] = buffer

                # Create client manager with channel_id and redis_client (only if not already exists)
                if channel_id not in self.client_managers:
                    client_manager = ClientManager(channel_id=channel_id, redis_client=self.redis_client, worker_id=self.worker_id)
                    self.client_managers[channel_id] = client_manager

                return True

            # We now own the channel - ONLY NOW should we set metadata with initializing state
            logger.info(f"Worker {self.worker_id} is now the owner of channel {channel_id}")

            if self.redis_client:
                # NOW create or update metadata with initializing state
                metadata = {
                    "url": channel_url,
                    "init_time": str(time.time()),
                    "last_active": str(time.time()),
                    "owner": self.worker_id,
                    "state": ChannelState.INITIALIZING  # Use constant instead of string literal
                }
                if channel_user_agent:
                    metadata["user_agent"] = channel_user_agent

                # Make sure stream_id is always set in metadata and properly logged
                if channel_stream_id:
                    metadata["stream_id"] = str(channel_stream_id)
                    logger.info(f"Storing stream_id {channel_stream_id} in metadata for channel {channel_id}")
                else:
                    logger.warning(f"No stream_id provided for channel {channel_id} during initialization")

                # Set channel metadata BEFORE creating the StreamManager
                self.redis_client.hset(metadata_key, mapping=metadata)
                self.redis_client.expire(metadata_key, 3600)  # Increased TTL from 30 seconds to 1 hour

                # Verify the stream_id was set correctly in Redis
                stream_id_value = self.redis_client.hget(metadata_key, "stream_id")
                if stream_id_value:
                    logger.info(f"Verified stream_id {stream_id_value.decode('utf-8')} is set in Redis for channel {channel_id}")
                else:
                    logger.warning(f"Failed to set stream_id in Redis for channel {channel_id}")

            # Create stream buffer
            buffer = StreamBuffer(channel_id=channel_id, redis_client=self.redis_client)
            logger.debug(f"Created StreamBuffer for channel {channel_id}")
            self.stream_buffers[channel_id] = buffer

            # Only the owner worker creates the actual stream manager
            stream_manager = StreamManager(
                channel_id,
                channel_url,
                buffer,
                user_agent=channel_user_agent,
                transcode=transcode,
                stream_id=channel_stream_id,  # Pass stream ID to the manager
                worker_id=self.worker_id  # Pass worker_id explicitly to eliminate circular dependency
            )
            logger.info(f"Created StreamManager for channel {channel_id} with stream ID {channel_stream_id}")
            self.stream_managers[channel_id] = stream_manager

            # Log channel start event
            try:
                channel_obj = Channel.objects.get(uuid=channel_id)

                # Get stream name if stream_id is available
                stream_name = None
                if channel_stream_id:
                    try:
                        stream_obj = Stream.objects.get(id=channel_stream_id)
                        stream_name = stream_obj.name
                    except Exception:
                        pass

                log_system_event(
                    'channel_start',
                    channel_id=channel_id,
                    channel_name=channel_obj.name,
                    stream_name=stream_name,
                    stream_id=channel_stream_id
                )
            except Exception as e:
                logger.error(f"Could not log channel start event: {e}")

            # Create client manager with channel_id, redis_client AND worker_id (only if not already exists)
            if channel_id not in self.client_managers:
                client_manager = ClientManager(
                    channel_id=channel_id,
                    redis_client=self.redis_client,
                    worker_id=self.worker_id
                )
                self.client_managers[channel_id] = client_manager

            # Start stream manager thread only for the owner
            thread = threading.Thread(target=stream_manager.run, daemon=True)
            thread.name = f"stream-{channel_id}"
            thread.start()
            logger.info(f"Started stream manager thread for channel {channel_id}")

            # If we're the owner, we need to set the channel state rather than starting a grace period immediately
            if self.am_i_owner(channel_id):
                self.update_channel_state(channel_id, ChannelState.CONNECTING, {
                    "init_time": str(time.time()),
                    "owner": self.worker_id
                })

                # Set connection attempt start time
                attempt_key = RedisKeys.connection_attempt(channel_id)
                self.redis_client.setex(attempt_key, 60, str(time.time()))

                logger.info(f"Channel {channel_id} in {ChannelState.CONNECTING} state - will start grace period after connection")
            return True

        except Exception as e:
            logger.error(f"Error initializing channel {channel_id}: {e}", exc_info=True)
            # Release ownership on failure
            self.release_ownership(channel_id)
            return False

    def check_if_channel_exists(self, channel_id):
        """
        Check if a channel exists and is in a valid state.
        Enhanced to detect zombie channels after server restarts.
        """
        # Check local memory first
        if channel_id in self.stream_managers or channel_id in self.stream_buffers:
            return True

        # Check Redis using the standard key pattern
        if self.redis_client:
            # Primary check - look for channel metadata
            metadata_key = RedisKeys.channel_metadata(channel_id)

            # If metadata exists, validate it's in a healthy state
            if self.redis_client.exists(metadata_key):
                metadata = self.redis_client.hgetall(metadata_key)

                # Get channel state and owner
                state = metadata.get(b'state', b'unknown').decode('utf-8')
                owner = metadata.get(b'owner', b'').decode('utf-8')

                # States that indicate the channel is running properly or shutting down
                valid_states = [ChannelState.ACTIVE, ChannelState.WAITING_FOR_CLIENTS,
                                ChannelState.CONNECTING, ChannelState.BUFFERING, ChannelState.INITIALIZING,
                                ChannelState.STOPPING]

                # If the channel is in a valid state, check if the owner is still active
                if state in valid_states:
                    # Check if owner still exists by checking heartbeat
                    owner_heartbeat_key = f"ts_proxy:worker:{owner}:heartbeat"
                    owner_alive = self.redis_client.exists(owner_heartbeat_key)

                    if owner_alive:
                        return True
                    else:
                        # This is a zombie channel - owner is gone but metadata still exists
                        logger.warning(f"Detected zombie channel {channel_id} - owner {owner} is no longer active")

                        # Check if there are any clients connected
                        client_set_key = RedisKeys.clients(channel_id)
                        client_count = self.redis_client.scard(client_set_key) or 0

                        if client_count > 0:
                            logger.warning(f"Zombie channel {channel_id} has {client_count} clients - attempting ownership takeover")
                            # Could potentially take ownership here in the future
                            # For now, just clean it up to be safe
                        else:
                            logger.warning(f"Zombie channel {channel_id} has no clients - cleaning up")

                        self._clean_zombie_channel(channel_id, metadata)
                        return False
                elif state in [ChannelState.STOPPED, ChannelState.ERROR]:
                    # These terminal states indicate the channel should be cleaned up and reinitialized
                    logger.info(f"Channel {channel_id} in terminal state {state} - returning False to trigger cleanup")
                    return False
                else:
                    # Unknown or initializing state, check how long it's been in this state
                    if b'state_changed_at' in metadata:
                        state_changed_at = float(metadata[b'state_changed_at'].decode('utf-8'))
                        state_age = time.time() - state_changed_at

                        # If in initializing state for too long, consider it stale
                        if state_age > 60:  # 60 seconds threshold
                            logger.warning(f"Channel {channel_id} stuck in {state} state for {state_age:.1f}s - treating as zombie")
                            self._clean_zombie_channel(channel_id, metadata)
                            return False

                    # Otherwise assume it's still in progress
                    return True

            # Additional checks if metadata doesn't exist
            additional_keys = [
                RedisKeys.clients(channel_id),
                RedisKeys.buffer_index(channel_id),
                RedisKeys.channel_owner(channel_id)
            ]

            for key in additional_keys:
                if self.redis_client.exists(key):
                    # Found orphaned keys without metadata - clean them up
                    logger.warning(f"Found orphaned keys for channel {channel_id} without metadata - cleaning up")
                    self._clean_redis_keys(channel_id)
                    return False

        return False

    def _clean_zombie_channel(self, channel_id, metadata=None):
        """Clean up a zombie channel (channel with Redis keys but no active owner)"""
        try:
            logger.info(f"Cleaning up zombie channel {channel_id}")

            # If we have metadata, log details for debugging
            if metadata:
                state = metadata.get(b'state', b'unknown').decode('utf-8')
                owner = metadata.get(b'owner', b'unknown').decode('utf-8')
                logger.info(f"Zombie channel details - state: {state}, owner: {owner}")

            # Clean up Redis keys
            self._clean_redis_keys(channel_id)

            # Force release resources in the Channel model
            try:
                channel = Channel.objects.get(uuid=channel_id)
                channel.release_stream()
                logger.info(f"Released stream allocation for zombie channel {channel_id}")
            except Exception as e:
                try:
                    stream = Stream.objects.get(stream_hash=channel_id)
                    stream.release_stream()
                    logger.info(f"Released stream allocation for zombie channel {channel_id}")
                except Exception as e:
                    logger.error(f"Error releasing stream for zombie channel {channel_id}: {e}")

            return True
        except Exception as e:
            logger.error(f"Error cleaning zombie channel {channel_id}: {e}", exc_info=True)
            return False

    def handle_client_disconnect(self, channel_id):
        """
        Handle client disconnect event - check if channel should shut down.
        Can be called directly by owner or via PubSub from non-owner workers.
        """
        if channel_id not in self.client_managers:
            return

        try:
            # VERIFY REDIS CLIENT COUNT DIRECTLY
            client_set_key = RedisKeys.clients(channel_id)
            total = self.redis_client.scard(client_set_key) or 0

            if total == 0:
                logger.debug(f"No clients left after disconnect event - stopping channel {channel_id}")
                # Set the disconnect timer for other workers to see
                disconnect_key = RedisKeys.last_client_disconnect(channel_id)
                self.redis_client.setex(disconnect_key, 60, str(time.time()))

                # Get configured shutdown delay or default
                shutdown_delay = ConfigHelper.channel_shutdown_delay()

                if shutdown_delay > 0:
                    logger.info(f"Waiting {shutdown_delay}s before stopping channel...")
                    gevent.sleep(shutdown_delay)

                    # Re-check client count before stopping
                    total = self.redis_client.scard(client_set_key) or 0
                    if total > 0:
                        logger.info(f"New clients connected during shutdown delay - aborting shutdown")
                        self.redis_client.delete(disconnect_key)
                        return

                # Stop the channel directly
                self.stop_channel(channel_id)
        except Exception as e:
            logger.error(f"Error handling client disconnect for channel {channel_id}: {e}")

    def stop_channel(self, channel_id):
        """Stop a channel with proper ownership handling"""
        try:
            logger.info(f"Stopping channel {channel_id}")

            # First set a stopping key that clients will check
            if self.redis_client:
                stop_key = RedisKeys.channel_stopping(channel_id)
                self.redis_client.setex(stop_key, 10, "true")

            # Only stop the actual stream manager if we're the owner
            if self.am_i_owner(channel_id):
                logger.info(f"This worker ({self.worker_id}) is the owner - closing provider connection")
                if channel_id in self.stream_managers:
                    stream_manager = self.stream_managers[channel_id]

                    # Signal thread to stop and close resources
                    if hasattr(stream_manager, 'stop'):
                        stream_manager.stop()
                    else:
                        stream_manager.running = False
                        if hasattr(stream_manager, '_close_socket'):
                            stream_manager._close_socket()

                # Wait for stream thread to finish
                stream_thread_name = f"stream-{channel_id}"
                stream_thread = None

                for thread in threading.enumerate():
                    if thread.name == stream_thread_name:
                        stream_thread = thread
                        break

                if stream_thread and stream_thread.is_alive():
                    logger.info(f"Waiting for stream thread to terminate")
                    try:
                        # Very short timeout to prevent hanging the app
                        stream_thread.join(timeout=2.0)
                        if stream_thread.is_alive():
                            logger.warning(f"Stream thread did not terminate within timeout")
                    except RuntimeError:
                        logger.debug(f"Could not join stream thread (may be current thread)")

                # Release ownership
                self.release_ownership(channel_id)
                logger.info(f"Released ownership of channel {channel_id}")

                # Log channel stop event (after cleanup, before releasing ownership section ends)
                try:
                    channel_obj = Channel.objects.get(uuid=channel_id)

                    # Calculate runtime and get total bytes from metadata
                    runtime = None
                    total_bytes = None
                    if self.redis_client:
                        metadata_key = RedisKeys.channel_metadata(channel_id)
                        metadata = self.redis_client.hgetall(metadata_key)
                        if metadata:
                            # Calculate runtime from init_time
                            if b'init_time' in metadata:
                                try:
                                    init_time = float(metadata[b'init_time'].decode('utf-8'))
                                    runtime = round(time.time() - init_time, 2)
                                except Exception:
                                    pass
                            # Get total bytes transferred
                            if b'total_bytes' in metadata:
                                try:
                                    total_bytes = int(metadata[b'total_bytes'].decode('utf-8'))
                                except Exception:
                                    pass

                    log_system_event(
                        'channel_stop',
                        channel_id=channel_id,
                        channel_name=channel_obj.name,
                        runtime=runtime,
                        total_bytes=total_bytes
                    )
                except Exception as e:
                    logger.error(f"Could not log channel stop event: {e}")

            # Always clean up local resources - WITH SAFE CHECKS
            if channel_id in self.stream_managers:
                del self.stream_managers[channel_id]
                logger.info(f"Removed stream manager for channel {channel_id}")

            # Stop buffer and ensure all its timers are cancelled - SAFE CHECK HERE
            if channel_id in self.stream_buffers:
                buffer = self.stream_buffers[channel_id]
                # Call stop on buffer to properly shut it down
                if hasattr(buffer, 'stop'):
                    try:
                        buffer.stop()
                        logger.debug(f"Buffer for channel {channel_id} properly stopped")
                    except Exception as e:
                        logger.error(f"Error stopping buffer: {e}")

                # Save reference and check again before deleting
                try:
                    if channel_id in self.stream_buffers:  # Check again to prevent race conditions
                        del self.stream_buffers[channel_id]
                        logger.info(f"Removed stream buffer for channel {channel_id}")
                except KeyError:
                    logger.debug(f"Buffer for channel {channel_id} already removed")

            # Clean up client manager - SAFE CHECK HERE TOO
            if channel_id in self.client_managers:
                try:
                    client_manager = self.client_managers[channel_id]
                    # Stop the heartbeat thread before deleting
                    if hasattr(client_manager, 'stop'):
                        client_manager.stop()
                    del self.client_managers[channel_id]
                    logger.info(f"Removed client manager for channel {channel_id}")
                except KeyError:
                    logger.debug(f"Client manager for channel {channel_id} already removed")

            # Clean up Redis keys
            self._clean_redis_keys(channel_id)

            return True
        except Exception as e:
            logger.error(f"Error stopping channel {channel_id}: {e}")
            return False

    def check_inactive_channels(self):
        """Check for inactive channels (no clients) and stop them"""
        channels_to_stop = []

        for channel_id, client_manager in self.client_managers.items():
            if client_manager.get_client_count() == 0:
                channels_to_stop.append(channel_id)

        for channel_id in channels_to_stop:
            logger.info(f"Auto-stopping inactive channel {channel_id}")
            self.stop_channel(channel_id)

    def _cleanup_channel(self, channel_id: str) -> None:
        """Remove channel resources"""
        # Removed reference to non-existent fetch_threads collection
        for collection in [self.stream_managers, self.stream_buffers, self.client_managers]:
            collection.pop(channel_id, None)

    def shutdown(self) -> None:
        """Stop all channels and cleanup"""
        for channel_id in list(self.stream_managers.keys()):
            self.stop_channel(channel_id)

    def _start_cleanup_thread(self):
        """Start background thread to maintain ownership and clean up resources"""
        def cleanup_task():
            while True:
                try:
                    # Send worker heartbeat first
                    if self.redis_client:
                        worker_heartbeat_key = f"ts_proxy:worker:{self.worker_id}:heartbeat"
                        self._execute_redis_command(
                            lambda: self.redis_client.setex(worker_heartbeat_key, 30, str(time.time()))
                        )

                    # Refresh channel registry
                    self.refresh_channel_registry()

                    # Create a unified list of all channels we have locally
                    all_local_channels = set(self.stream_managers.keys()) | set(self.client_managers.keys())

                    # Single loop through all channels - process each exactly once
                    for channel_id in list(all_local_channels):
                        if self.am_i_owner(channel_id):
                            # === OWNER CHANNEL HANDLING ===
                            # Extend ownership lease
                            self.extend_ownership(channel_id)

                            # Get channel state from metadata hash
                            channel_state = "unknown"
                            if self.redis_client:
                                metadata_key = RedisKeys.channel_metadata(channel_id)
                                metadata = self.redis_client.hgetall(metadata_key)
                                if metadata and b'state' in metadata:
                                    channel_state = metadata[b'state'].decode('utf-8')

                            # Check if channel has any clients left
                            total_clients = 0
                            if channel_id in self.client_managers:
                                client_manager = self.client_managers[channel_id]
                                total_clients = client_manager.get_total_client_count()
                            else:
                                # This can happen during reconnection attempts or crashes
                                # Check Redis directly for any connected clients
                                if self.redis_client:
                                    client_set_key = RedisKeys.clients(channel_id)
                                    total_clients = self.redis_client.scard(client_set_key) or 0

                                    if total_clients == 0:
                                        logger.warning(f"Channel {channel_id} is missing client_manager but we're the owner with 0 clients - will trigger cleanup")

                            # Log client count periodically
                            if time.time() % 30 < 1:  # Every ~30 seconds
                                logger.info(f"Channel {channel_id} has {total_clients} clients, state: {channel_state}")

                            # If in connecting or waiting_for_clients state, check grace period
                            if channel_state in [ChannelState.CONNECTING, ChannelState.WAITING_FOR_CLIENTS]:
                                # Check if channel is already stopping
                                if self.redis_client:
                                    stop_key = RedisKeys.channel_stopping(channel_id)
                                    if self.redis_client.exists(stop_key):
                                        logger.debug(f"Channel {channel_id} is already stopping - skipping monitor shutdown")
                                        continue

                                # Get connection_ready_time from metadata (indicates if channel reached ready state)
                                connection_ready_time = None
                                if metadata and b'connection_ready_time' in metadata:
                                    try:
                                        connection_ready_time = float(metadata[b'connection_ready_time'].decode('utf-8'))
                                    except (ValueError, TypeError):
                                        pass

                                if total_clients == 0:
                                    # Check if we have a connection_attempt timestamp (set when CONNECTING starts)
                                    connection_attempt_time = None
                                    attempt_key = RedisKeys.connection_attempt(channel_id)
                                    if self.redis_client:
                                        attempt_value = self.redis_client.get(attempt_key)
                                        if attempt_value:
                                            try:
                                                connection_attempt_time = float(attempt_value.decode('utf-8'))
                                            except (ValueError, TypeError):
                                                pass

                                    # Also get init time as a fallback
                                    init_time = None
                                    if metadata and b'init_time' in metadata:
                                        try:
                                            init_time = float(metadata[b'init_time'].decode('utf-8'))
                                        except (ValueError, TypeError):
                                            pass

                                    # Use whichever timestamp we have (prefer connection_attempt as it's more recent)
                                    start_time = connection_attempt_time or init_time

                                    if start_time:
                                        # Check which timeout to apply based on channel lifecycle
                                        if connection_ready_time:
                                            # Already reached ready - use shutdown_delay
                                            time_since_ready = time.time() - connection_ready_time
                                            shutdown_delay = ConfigHelper.channel_shutdown_delay()

                                            if time_since_ready > shutdown_delay:
                                                logger.warning(
                                                    f"Channel {channel_id} in {channel_state} state with 0 clients for {time_since_ready:.1f}s "
                                                    f"(after reaching ready, shutdown_delay: {shutdown_delay}s) - stopping channel"
                                                )
                                                self.stop_channel(channel_id)
                                                continue
                                        else:
                                            # Never reached ready - use grace_period timeout
                                            time_since_start = time.time() - start_time
                                            connecting_timeout = ConfigHelper.channel_init_grace_period()

                                            if time_since_start > connecting_timeout:
                                                logger.warning(
                                                    f"Channel {channel_id} stuck in {channel_state} state for {time_since_start:.1f}s "
                                                    f"with no clients (timeout: {connecting_timeout}s) - stopping channel due to upstream issues"
                                                )
                                                self.stop_channel(channel_id)
                                                continue
                                elif connection_ready_time:
                                    # We have clients now, but check grace period for state transition
                                    grace_period = ConfigHelper.channel_init_grace_period()
                                    time_since_ready = time.time() - connection_ready_time

                                    logger.debug(f"GRACE PERIOD CHECK: Channel {channel_id} in {channel_state} state, "
                                                 f"time_since_ready={time_since_ready:.1f}s, grace_period={grace_period}s, "
                                                 f"total_clients={total_clients}")

                                    if time_since_ready <= grace_period:
                                        # Still within grace period
                                        logger.debug(f"Channel {channel_id} in grace period - {time_since_ready:.1f}s of {grace_period}s elapsed")
                                        continue
                                    else:
                                        # Grace period expired with clients - mark channel as active
                                        logger.info(f"Grace period expired with {total_clients} clients - marking channel {channel_id} as active")
                                        if self.update_channel_state(channel_id, ChannelState.ACTIVE, {
                                            "grace_period_ended_at": str(time.time()),
                                            "clients_at_activation": str(total_clients)
                                        }):
                                            logger.info(f"Channel {channel_id} activated with {total_clients} clients after grace period")
                            # If active and no clients, start normal shutdown procedure
                            elif channel_state not in [ChannelState.CONNECTING, ChannelState.WAITING_FOR_CLIENTS] and total_clients == 0:
                                # Check if channel is already stopping
                                if self.redis_client:
                                    stop_key = RedisKeys.channel_stopping(channel_id)
                                    if self.redis_client.exists(stop_key):
                                        logger.debug(f"Channel {channel_id} is already stopping - skipping monitor shutdown")
                                        continue

                                # Check if there's a pending no-clients timeout
                                disconnect_key = RedisKeys.last_client_disconnect(channel_id)
                                disconnect_time = None

                                if self.redis_client:
                                    disconnect_value = self.redis_client.get(disconnect_key)
                                    if disconnect_value:
                                        try:
                                            disconnect_time = float(disconnect_value.decode('utf-8'))
                                        except (ValueError, TypeError) as e:
                                            logger.error(f"Invalid disconnect time for channel {channel_id}: {e}")

                                current_time = time.time()

                                if not disconnect_time:
                                    # First time seeing zero clients, set timestamp
                                    if self.redis_client:
                                        self.redis_client.setex(disconnect_key, 60, str(current_time))
                                    logger.warning(f"No clients detected for channel {channel_id}, starting shutdown timer")
                                elif current_time - disconnect_time > ConfigHelper.channel_shutdown_delay():
                                    # We've had no clients for the shutdown delay period
                                    logger.warning(f"No clients for {current_time - disconnect_time:.1f}s, stopping channel {channel_id}")
                                    self.stop_channel(channel_id)
                                else:
                                    # Still in shutdown delay period
                                    logger.debug(f"Channel {channel_id} shutdown timer: "
                                                f"{current_time - disconnect_time:.1f}s of "
                                                f"{ConfigHelper.channel_shutdown_delay()}s elapsed")
                            else:
                                # There are clients or we're still connecting - clear any disconnect timestamp
                                if self.redis_client:
                                    self.redis_client.delete(f"ts_proxy:channel:{channel_id}:last_client_disconnect_time")

                        else:
                            # === NON-OWNER CHANNEL HANDLING ===
                            # For channels we don't own, check if they've been stopped/cleaned up in Redis
                            if self.redis_client:
                                # Method 1: Check for stopping key
                                stop_key = RedisKeys.channel_stopping(channel_id)
                                if self.redis_client.exists(stop_key):
                                    logger.debug(f"Non-owner cleanup: Channel {channel_id} has stopping flag in Redis, cleaning up local resources")
                                    self._cleanup_local_resources(channel_id)
                                    continue

                                # Method 2: Check if owner still exists
                                owner_key = RedisKeys.channel_owner(channel_id)
                                if not self.redis_client.exists(owner_key):
                                    logger.debug(f"Non-owner cleanup: Channel {channel_id} has no owner in Redis, cleaning up local resources")
                                    self._cleanup_local_resources(channel_id)
                                    continue

                                # Method 3: Check if metadata still exists
                                metadata_key = RedisKeys.channel_metadata(channel_id)
                                if not self.redis_client.exists(metadata_key):
                                    logger.debug(f"Non-owner cleanup: Channel {channel_id} has no metadata in Redis, cleaning up local resources")
                                    self._cleanup_local_resources(channel_id)
                                    continue

                            # Check for local client count - if zero, clean up our local resources
                            if channel_id in self.client_managers:
                                if self.client_managers[channel_id].get_client_count() == 0:
                                    # We're not the owner, and we have no local clients - clean up our resources
                                    logger.debug(f"Non-owner cleanup: Channel {channel_id} has no local clients, cleaning up local resources")
                                    self._cleanup_local_resources(channel_id)
                            else:
                                # This shouldn't happen, but clean up anyway
                                logger.warning(f"Non-owner cleanup: Channel {channel_id} has no client_manager entry, cleaning up local resources")
                                self._cleanup_local_resources(channel_id)

                except Exception as e:
                    logger.error(f"Error in cleanup thread: {e}", exc_info=True)

                # Periodically check for orphaned channels (every 30 seconds)
                if hasattr(self, '_last_orphan_check'):
                    if time.time() - self._last_orphan_check > 30:
                        try:
                            self._check_orphaned_metadata()
                            self._last_orphan_check = time.time()
                        except Exception as orphan_error:
                            logger.error(f"Error checking orphaned metadata: {orphan_error}", exc_info=True)
                else:
                    self._last_orphan_check = time.time()

                gevent.sleep(ConfigHelper.cleanup_check_interval())  # REPLACE: time.sleep(ConfigHelper.cleanup_check_interval())

        thread = threading.Thread(target=cleanup_task, daemon=True)
        thread.name = "ts-proxy-cleanup"
        thread.start()
        logger.info(f"Started TS proxy cleanup thread (interval: {ConfigHelper.cleanup_check_interval()}s)")

    def _check_orphaned_channels(self):
        """Check for orphaned channels in Redis (owner worker crashed)"""
        if not self.redis_client:
            return

        try:
            # Get all active channel keys
            channel_pattern = "ts_proxy:channel:*:metadata"
            channel_keys = self.redis_client.keys(channel_pattern)

            for key in channel_keys:
                try:
                    channel_id = key.decode('utf-8').split(':')[2]

                    # Check if this channel has an owner
                    owner = self.get_channel_owner(channel_id)

                    if not owner:
                        # Check if there are any clients
                        client_set_key = RedisKeys.clients(channel_id)
                        client_count = self.redis_client.scard(client_set_key) or 0

                        if client_count > 0:
                            # Orphaned channel with clients - we could take ownership
                            logger.info(f"Found orphaned channel {channel_id} with {client_count} clients")
                        else:
                            # Orphaned channel with no clients - clean it up
                            logger.info(f"Cleaning up orphaned channel {channel_id}")

                            # If we have it locally, stop it properly to clean up processes
                            if channel_id in self.stream_managers or channel_id in self.client_managers:
                                logger.info(f"Orphaned channel {channel_id} is local - calling stop_channel")
                                self.stop_channel(channel_id)
                            else:
                                # Just clean up Redis keys for remote channels
                                self._clean_redis_keys(channel_id)
                except Exception as e:
                    logger.error(f"Error processing channel key {key}: {e}")

        except Exception as e:
            logger.error(f"Error checking orphaned channels: {e}")

    def _check_orphaned_metadata(self):
        """
        Check for metadata entries that have no owner and no clients.
        This catches zombie channels that weren't cleaned up properly.
        """
        if not self.redis_client:
            return

        try:
            # Get all channel metadata keys
            channel_pattern = "ts_proxy:channel:*:metadata"
            channel_keys = self.redis_client.keys(channel_pattern)

            for key in channel_keys:
                try:
                    channel_id = key.decode('utf-8').split(':')[2]

                    # Get metadata first
                    metadata = self.redis_client.hgetall(key)
                    if not metadata:
                        # Empty metadata - clean it up
                        logger.warning(f"Found empty metadata for channel {channel_id} - cleaning up")
                        # If we have it locally, stop it properly
                        if channel_id in self.stream_managers or channel_id in self.client_managers:
                            self.stop_channel(channel_id)
                        else:
                            self._clean_redis_keys(channel_id)
                        continue

                    # Get owner
                    owner = metadata.get(b'owner', b'').decode('utf-8') if b'owner' in metadata else ''

                    # Check if owner is still alive
                    owner_alive = False
                    if owner:
                        owner_heartbeat_key = f"ts_proxy:worker:{owner}:heartbeat"
                        owner_alive = self.redis_client.exists(owner_heartbeat_key)

                    # Check client count
                    client_set_key = RedisKeys.clients(channel_id)
                    client_count = self.redis_client.scard(client_set_key) or 0

                    # If no owner and no clients, clean it up
                    if not owner_alive and client_count == 0:
                        state = metadata.get(b'state', b'unknown').decode('utf-8') if b'state' in metadata else 'unknown'
                        logger.warning(f"Found orphaned metadata for channel {channel_id} (state: {state}, owner: {owner}, clients: {client_count}) - cleaning up")

                        # If we have it locally, stop it properly to clean up transcode/proxy processes
                        if channel_id in self.stream_managers or channel_id in self.client_managers:
                            logger.info(f"Channel {channel_id} is local - calling stop_channel to clean up processes")
                            self.stop_channel(channel_id)
                        else:
                            # Just clean up Redis keys for remote channels
                            self._clean_redis_keys(channel_id)
                    elif not owner_alive and client_count > 0:
                        # Owner is gone but clients remain - just log for now
                        logger.warning(f"Found orphaned channel {channel_id} with {client_count} clients but no owner - may need ownership takeover")

                except Exception as e:
                    logger.error(f"Error processing metadata key {key}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error checking orphaned metadata: {e}", exc_info=True)

    def _clean_redis_keys(self, channel_id):
        """Clean up all Redis keys for a channel more efficiently"""
        # Release the channel, stream, and profile keys from the channel
        try:
            channel = Channel.objects.get(uuid=channel_id)
            channel.release_stream()
        except:
            stream = Stream.objects.get(stream_hash=channel_id)
            stream.release_stream()

        if not self.redis_client:
            return 0

        try:
            # Define key patterns to scan for
            patterns = [
                f"ts_proxy:channel:{channel_id}:*",  # All channel keys
                RedisKeys.events_channel(channel_id)  # Event channel
            ]

            total_deleted = 0

            for pattern in patterns:
                cursor = 0
                while True:
                    cursor, keys = self.redis_client.scan(cursor, match=pattern, count=100)
                    if keys:
                        self.redis_client.delete(*keys)
                        total_deleted += len(keys)

                    # Exit when cursor returns to 0
                    if cursor == 0:
                        break

            logger.info(f"Cleaned up {total_deleted} Redis keys for channel {channel_id}")
            return total_deleted

        except Exception as e:
            logger.error(f"Error cleaning Redis keys for channel {channel_id}: {e}")
            return 0

    def refresh_channel_registry(self):
        """Refresh TTL for active channels using standard keys"""
        if not self.redis_client:
            return

        # Refresh registry entries for channels we own
        for channel_id in list(self.stream_buffers.keys()):
            # Use standard key pattern
            metadata_key = RedisKeys.channel_metadata(channel_id)

            # Update activity timestamp in metadata only
            self.redis_client.hset(metadata_key, "last_active", str(time.time()))
            self.redis_client.expire(metadata_key, 30)  # Reset TTL on metadata hash
            logger.debug(f"Refreshed metadata TTL for channel {channel_id}")

    def update_channel_state(self, channel_id, new_state, additional_fields=None):
        """Update channel state with proper history tracking and logging"""
        if not self.redis_client:
            return False

        try:
            metadata_key = RedisKeys.channel_metadata(channel_id)

            # Get current state for logging
            current_state = None
            metadata = self.redis_client.hgetall(metadata_key)
            if metadata and b'state' in metadata:
                current_state = metadata[b'state'].decode('utf-8')

            # Only update if state is actually changing
            if current_state == new_state:
                logger.debug(f"Channel {channel_id} state unchanged: {current_state}")
                return True

            # Prepare update data
            update_data = {
                "state": new_state,
                "state_changed_at": str(time.time())
            }

            # Add optional additional fields
            if additional_fields:
                update_data.update(additional_fields)

            # Update the metadata
            self.redis_client.hset(metadata_key, mapping=update_data)

            # Log the transition
            logger.info(f"Channel {channel_id} state transition: {current_state or 'None'} -> {new_state}")
            return True
        except Exception as e:
            logger.error(f"Error updating channel state: {e}")
            return False

    def _cleanup_local_resources(self, channel_id):
        """Clean up local resources for a channel without affecting Redis keys"""
        try:
            # Clean up local objects only
            if channel_id in self.stream_managers:
                if hasattr(self.stream_managers[channel_id], 'stop'):
                    self.stream_managers[channel_id].stop()
                del self.stream_managers[channel_id]
                logger.info(f"Non-owner cleanup: Removed stream manager for channel {channel_id}")

            if channel_id in self.stream_buffers:
                del self.stream_buffers[channel_id]
                logger.info(f"Non-owner cleanup: Removed stream buffer for channel {channel_id}")

            if channel_id in self.client_managers:
                del self.client_managers[channel_id]
                logger.info(f"Non-owner cleanup: Removed client manager for channel {channel_id}")

            return True
        except Exception as e:
            logger.error(f"Error cleaning up local resources: {e}", exc_info=True)
            return False
