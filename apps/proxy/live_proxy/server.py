"""
Transport Stream (TS) Proxy Server
Handles live TS stream proxying with support for:
- Stream switching
- Buffer management
- Multiple client connections
- Connection state tracking
"""

import threading
import socket
import random
import time
import os
import json
import gevent
from apps.proxy.config import TSConfig as Config
from apps.channels.models import Channel, Stream
from core.utils import RedisClient, log_system_event
from django.db import close_old_connections
from redis.exceptions import ConnectionError, TimeoutError
from .input.manager import StreamManager
from .input.buffer import StreamBuffer
from .client_manager import ClientManager
from .output.fmp4.manager import FMP4RemuxManager
from .output.profile.manager import OutputProfileManager, PROFILE_STATE_ACTIVE
from .redis_keys import RedisKeys
from .constants import ChannelState, EventType, StreamType
from .config_helper import ConfigHelper
from .utils import get_logger

logger = get_logger()

class ProxyServer:
    """Manages TS proxy server instance with worker coordination"""
    _instance = None
    _INITIALIZING = object()  # sentinel for gevent-safe singleton

    @classmethod
    def get_instance(cls):
        inst = cls._instance
        if inst is not None and inst is not cls._INITIALIZING:
            return inst
        if inst is None:
            cls._instance = cls._INITIALIZING
            try:
                from .server import ProxyServer
                from .input.manager import StreamManager
                from .input.buffer import StreamBuffer
                from .client_manager import ClientManager
                real_instance = ProxyServer()
                cls._instance = real_instance
                return real_instance
            except Exception:
                cls._instance = None  # Reset so next call can retry
                raise
        # Another greenlet is initializing — wait for completion
        while True:
            inst = cls._instance
            if inst is not None and inst is not cls._INITIALIZING:
                return inst
            gevent.sleep(0.05)

    def __init__(self):
        """Initialize proxy server with worker identification"""
        self.stream_managers = {}
        self.stream_buffers = {}
        self.client_managers = {}
        self.output_managers = {}  # {channel_id: {fmt: manager}}
        self.profile_managers = {}  # {channel_id: {profile_id: OutputProfileManager}}
        self.profile_buffers = {}   # {channel_id: {profile_id: StreamBuffer}}
        self._channel_names = {}
        self._stopping_channels = set()  # channels with an active stop_channel call in progress
        self._stopping_since = {}  # channel_id -> time.time() when stop_channel began
        self._local_stop_locks = {}
        # Managers kept until the stream OS thread exits (may outlive stream_managers dict)
        self._live_stream_managers = {}

        # Generate a unique worker ID
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

    def _spawn_on_hub(self, fn, *args, **kwargs):
        """Schedule fn on the gevent hub from any thread without blocking the caller."""
        import gevent

        try:
            hub = gevent.get_hub()
            hub.loop.run_callback_threadsafe(
                lambda: gevent.spawn(fn, *args, **kwargs)
            )
        except Exception as e:
            logger.error(f"Failed to schedule {getattr(fn, '__name__', fn)} on hub: {e}")

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
                        redis_password = os.environ.get("REDIS_PASSWORD", getattr(settings, 'REDIS_PASSWORD', ''))
                        redis_user = os.environ.get("REDIS_USER", getattr(settings, 'REDIS_USER', ''))

                        ssl_params = getattr(settings, 'REDIS_SSL_PARAMS', {})
                        pubsub_client = redis.Redis(
                            host=redis_host,
                            port=redis_port,
                            db=redis_db,
                            password=redis_password if redis_password else None,
                            username=redis_user if redis_user else None,
                            socket_timeout=60,
                            socket_connect_timeout=10,
                            socket_keepalive=True,
                            health_check_interval=30,
                            decode_responses=True,
                            **ssl_params
                        )
                        logger.info("Created fallback Redis PubSub client for event listener")

                    # Test connection before subscribing
                    pubsub_client.ping()

                    # Create a pubsub instance from the client
                    pubsub = pubsub_client.pubsub()
                    pubsub.psubscribe("live:events:*")

                    logger.info(f"Started Redis event listener for client activity")

                    # Reset retry count on successful connection
                    retry_count = 0

                    for message in pubsub.listen():
                        if message["type"] != "pmessage":
                            continue

                        try:
                            channel = message["channel"]
                            data = json.loads(message["data"])

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
                                        # Spawn to avoid blocking the pubsub listener thread
                                        # during the full shutdown path (thread joins, Redis cleanup).
                                        gevent.spawn(self.handle_client_disconnect, channel_id)


                                    elif event_type == EventType.STREAM_SWITCH:
                                        logger.info(f"Owner received {EventType.STREAM_SWITCH} request for channel {channel_id}")
                                        # Handle stream switch request
                                        new_url = data.get("url")
                                        user_agent = data.get("user_agent")
                                        event_stream_id = data.get("stream_id")
                                        event_m3u_profile_id = data.get("m3u_profile_id")

                                        if new_url and channel_id in self.stream_managers:
                                            # Mark the switch as in-progress in Redis so other workers know to wait
                                            if self.redis_client:
                                                status_key = RedisKeys.switch_status(channel_id)
                                                self.redis_client.set(status_key, "switching")

                                            # Perform the stream switch, forwarding stream_id and m3u_profile_id
                                            stream_manager = self.stream_managers[channel_id]
                                            success = stream_manager.update_url(new_url, event_stream_id, event_m3u_profile_id)

                                            if success:
                                                logger.info(f"Stream switch initiated for channel {channel_id}")

                                                # Confirm the URL in metadata now that the switch happened
                                                if self.redis_client:
                                                    metadata_key = RedisKeys.channel_metadata(channel_id)
                                                    self.redis_client.hset(metadata_key, "url", new_url)
                                                    if user_agent:
                                                        self.redis_client.hset(metadata_key, "user_agent", user_agent)

                                                # Publish confirmation
                                                switch_result = {
                                                    "event": EventType.STREAM_SWITCHED,  # Use constant instead of string
                                                    "channel_id": channel_id,
                                                    "success": True,
                                                    "url": new_url,
                                                    "timestamp": time.time()
                                                }
                                                self.redis_client.publish(
                                                    f"live:events:{channel_id}",
                                                    json.dumps(switch_result)
                                                )

                                                # Update status
                                                if self.redis_client:
                                                    self.redis_client.set(status_key, "switched")
                                            else:
                                                logger.error(f"Failed to switch stream for channel {channel_id}")

                                                # Roll back the URL in metadata to what the manager will
                                                # actually reconnect to. The non-owner may have pre-written
                                                # the desired URL; use stream_manager.url (the ground truth)
                                                # so Redis is consistent with the live stream.
                                                if self.redis_client:
                                                    metadata_key = RedisKeys.channel_metadata(channel_id)
                                                    self.redis_client.hset(metadata_key, "url", stream_manager.url)

                                                # Publish failure
                                                switch_result = {
                                                    "event": EventType.STREAM_SWITCHED,
                                                    "channel_id": channel_id,
                                                    "success": False,
                                                    "url": new_url,
                                                    "timestamp": time.time()
                                                }
                                                self.redis_client.publish(
                                                    f"live:events:{channel_id}",
                                                    json.dumps(switch_result)
                                                )
                                    elif event_type == EventType.CHANNEL_STOP:
                                        requester_worker_id = data.get("requester_worker_id")
                                        logger.info(
                                            f"Received {EventType.CHANNEL_STOP} event for channel {channel_id} "
                                            f"from worker {requester_worker_id}"
                                        )

                                        # Initiating worker already runs local stop_channel()
                                        if requester_worker_id and requester_worker_id == self.worker_id:
                                            logger.debug(
                                                f"Ignoring {EventType.CHANNEL_STOP} for {channel_id}; "
                                                f"this worker initiated teardown"
                                            )
                                        elif (
                                            channel_id in self.stream_managers
                                            or channel_id in self._live_stream_managers
                                        ):
                                            logger.info(
                                                f"Owner worker stopping local upstream for channel {channel_id}"
                                            )
                                            self.stop_channel(channel_id)
                                        elif (
                                            channel_id in self.stream_buffers
                                            or channel_id in self.client_managers
                                            or channel_id in self.profile_managers
                                            or channel_id in self.output_managers
                                        ):
                                            logger.info(
                                                f"Non-owner worker cleaning local resources for channel {channel_id}"
                                            )
                                            self._cleanup_local_resources(channel_id)

                                        # Acknowledge stop by publishing a response
                                        stop_response = {
                                            "event": EventType.CHANNEL_STOPPED,
                                            "channel_id": channel_id,
                                            "worker_id": self.worker_id,
                                            "timestamp": time.time()
                                        }
                                        self.redis_client.publish(
                                            f"live:events:{channel_id}",
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

                                    elif event_type == EventType.ENSURE_OUTPUT_FORMAT:
                                        fmt = data.get("fmt")
                                        if fmt:
                                            logger.info(f"Owner received ENSURE_OUTPUT_FORMAT for channel {channel_id}, fmt={fmt}")
                                            self.ensure_output_format(channel_id, fmt)

                                    elif event_type == EventType.ENSURE_OUTPUT_PROFILE:
                                        profile_id = data.get("profile_id")
                                        command = data.get("command")
                                        if profile_id is not None and command:
                                            logger.info(f"Owner received ENSURE_OUTPUT_PROFILE for channel {channel_id}, profile={profile_id}")
                                            self.ensure_output_profile(channel_id, profile_id, command)
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
                    gevent.sleep(final_delay)

                except Exception as e:
                    logger.error(f"Error in event listener: {e}")
                    # Add a short delay to prevent rapid retries on persistent errors
                    gevent.sleep(5)

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
            result = self._execute_redis_command(
                lambda: self.redis_client.get(lock_key)
            )
            if result is None:
                return None
            try:
                return result
            except (AttributeError, UnicodeDecodeError) as e:
                logger.error(f"Error decoding channel owner for {channel_id}: {e}, raw={result!r}")
                return None
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

            # Use atomic SET NX EX for locking with error handling
            acquired = self._execute_redis_command(
                lambda: self.redis_client.set(lock_key, self.worker_id, nx=True, ex=ttl)
            )

            if acquired is None:  # Redis command failed
                logger.warning(f"Redis command failed during ownership acquisition - assuming ownership")
                return True

            if acquired:
                logger.info(f"Worker {self.worker_id} acquired ownership of channel {channel_id}")
                return True

            # If not acquired, check if we already own it (might be a retry)
            current_owner = self._execute_redis_command(
                lambda: self.redis_client.get(lock_key)
            )
            if current_owner and current_owner == self.worker_id:
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
            if current and current == self.worker_id:
                self.redis_client.delete(lock_key)
                logger.info(f"Released ownership of channel {channel_id}")

                # Also ensure channel stopping key is set to signal clients
                stop_key = RedisKeys.channel_stopping(channel_id)
                self.redis_client.setex(stop_key, 30, "true")
                logger.info(f"Set stopping signal for channel {channel_id} clients")

        except Exception as e:
            logger.error(f"Error releasing channel ownership: {e}")

    def extend_ownership(self, channel_id, ttl=30):
        """Extend ownership lease, re-acquiring if key expired"""
        if not self.redis_client:
            return False

        try:
            lock_key = RedisKeys.channel_owner(channel_id)
            current = self.redis_client.get(lock_key)

            if current is None:
                # Key expired, re-acquire if we still run local upstream, but never
                # during coordinated teardown (multi-worker reconnect-during-stop race).
                if channel_id in self.stream_managers or channel_id in self._live_stream_managers:
                    if self._channel_unavailable_for_new_clients(channel_id):
                        logger.info(
                            f"Refusing ownership re-acquisition for {channel_id}; "
                            f"teardown or pending shutdown active"
                        )
                        return False

                    acquired = self.redis_client.set(lock_key, self.worker_id, nx=True, ex=ttl)
                    if acquired:
                        logger.warning(f"Re-acquired expired ownership for channel {channel_id}")
                        return True
                    else:
                        new_owner = self.redis_client.get(lock_key)
                        logger.warning(f"Could not re-acquire ownership for {channel_id}, new owner: {new_owner}")
                        return False
                return False

            if current == self.worker_id:
                self.redis_client.expire(lock_key, ttl)
                return True

            return False
        except Exception as e:
            logger.error(f"Error extending ownership: {e}")
            return False

    def initialize_channel(self, url, channel_id, user_agent=None, transcode=False, stream_id=None):
        """Initialize a channel without redundant active key"""
        try:
            if self._channel_unavailable_for_new_clients(channel_id):
                logger.warning(
                    f"Refusing to initialize channel {channel_id}; "
                    f"teardown or pending shutdown active"
                )
                return False

            if self._has_local_upstream_activity(channel_id):
                logger.warning(
                    f"Stopping lingering local upstream before initializing channel {channel_id}"
                )
                self._stop_local_stream_activity(channel_id)

            if self.redis_client:
                metadata_key = RedisKeys.channel_metadata(channel_id)
                if self.redis_client.exists(metadata_key):
                    metadata = self.redis_client.hgetall(metadata_key)
                    if 'state' in metadata:
                        state = metadata['state']
                        active_states = [ChannelState.INITIALIZING, ChannelState.CONNECTING,
                                        ChannelState.WAITING_FOR_CLIENTS, ChannelState.ACTIVE, ChannelState.BUFFERING]
                        if state in active_states:
                            logger.info(f"Channel {channel_id} already being initialized with state {state}")
                            # Create buffer and client manager only if we don't have them
                            if channel_id not in self.stream_buffers:
                                self.stream_buffers[channel_id] = StreamBuffer(channel_id, redis_client=RedisClient.get_buffer())
                            if channel_id not in self.client_managers:
                                self.client_managers[channel_id] = ClientManager(
                                    channel_id,
                                    redis_client=self.redis_client,
                                    worker_id=self.worker_id
                                )
                            return True

            # Create buffer and client manager instances (or reuse if they exist)
            if channel_id not in self.stream_buffers:
                buffer = StreamBuffer(channel_id, redis_client=RedisClient.get_buffer())
                self.stream_buffers[channel_id] = buffer

            if channel_id not in self.client_managers:
                client_manager = ClientManager(
                    channel_id,
                    redis_client=self.redis_client,
                    worker_id=self.worker_id
                )
                self.client_managers[channel_id] = client_manager

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
                    url_bytes = existing_metadata.get('url')
                    if url_bytes:
                        channel_url = url_bytes

                    ua_bytes = existing_metadata.get('user_agent')
                    if ua_bytes:
                        channel_user_agent = ua_bytes

                # Get stream ID from metadata if not provided
                if not channel_stream_id and 'stream_id' in existing_metadata:
                    try:
                        channel_stream_id = int(existing_metadata['stream_id'])
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
                    buffer = StreamBuffer(channel_id=channel_id, redis_client=RedisClient.get_buffer())
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
                    buffer = StreamBuffer(channel_id=channel_id, redis_client=RedisClient.get_buffer())
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
                    logger.info(f"Verified stream_id {stream_id_value} is set in Redis for channel {channel_id}")
                else:
                    logger.warning(f"Failed to set stream_id in Redis for channel {channel_id}")

            # Create stream buffer
            buffer = StreamBuffer(channel_id=channel_id, redis_client=RedisClient.get_buffer())
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
                _name = Channel.objects.filter(uuid=channel_id).values_list('name', flat=True).first()
                channel_name = _name if _name else str(channel_id)
                self._channel_names[channel_id] = channel_name

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
                    channel_name=channel_name,
                    stream_name=stream_name,
                    stream_id=channel_stream_id
                )
            except Exception as e:
                logger.error(f"Could not log channel start event: {e}")
                close_old_connections()

            # Create client manager with channel_id, redis_client AND worker_id (only if not already exists)
            if channel_id not in self.client_managers:
                client_manager = ClientManager(
                    channel_id=channel_id,
                    redis_client=self.redis_client,
                    worker_id=self.worker_id
                )
                self.client_managers[channel_id] = client_manager

            # Start stream manager thread only for the owner
            self._live_stream_managers[channel_id] = stream_manager
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
                state = metadata.get('state', 'unknown')
                owner = metadata.get('owner', '')

                # States that indicate the channel is running properly or shutting down
                valid_states = [ChannelState.ACTIVE, ChannelState.WAITING_FOR_CLIENTS,
                                ChannelState.CONNECTING, ChannelState.BUFFERING, ChannelState.INITIALIZING,
                                ChannelState.STOPPING]

                # If the channel is in a valid state, check if the owner is still active
                if state in valid_states:
                    # Check if owner still exists by checking heartbeat
                    owner_heartbeat_key = f"live:worker:{owner}:heartbeat"
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
                    if 'state_changed_at' in metadata:
                        state_changed_at = float(metadata['state_changed_at'])
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
                    try:
                        self._clean_redis_keys(channel_id)
                    except Exception as e:
                        logger.error(f"Error cleaning redis keys for channel {channel_id}: {e}")
                    return False

        return False

    def _clean_zombie_channel(self, channel_id, metadata=None):
        """Clean up a zombie channel (channel with Redis keys but no active owner)"""
        try:
            logger.info(f"Cleaning up zombie channel {channel_id}")

            # If we have metadata, log details for debugging
            if metadata:
                state = metadata.get('state', 'unknown')
                owner = metadata.get('owner', 'unknown')
                logger.info(f"Zombie channel details - state: {state}, owner: {owner}")

            self._clean_redis_keys(channel_id)
            return True
        except Exception as e:
            logger.error(f"Error cleaning zombie channel {channel_id}: {e}", exc_info=True)
            return False

    @staticmethod
    def _shutdown_disconnect_ttl():
        delay = ConfigHelper.channel_shutdown_delay()
        return max(int(delay * 2), 60)

    def _wait_for_shutdown_delay(self, channel_id):
        """
        Wait until shutdown_delay has elapsed since the Redis disconnect
        timestamp. Returns False if clients reconnect or the timer is cancelled.
        Uses Redis state so concurrent disconnect handlers and multi-worker
        reconnects always honour the latest last-client disconnect time.
        """
        if not self.redis_client:
            return True

        shutdown_delay = ConfigHelper.channel_shutdown_delay()
        if shutdown_delay <= 0:
            return True

        disconnect_key = RedisKeys.last_client_disconnect(channel_id)
        client_set_key = RedisKeys.clients(channel_id)
        poll_interval = 1.0

        logger.info(
            f"Waiting up to {shutdown_delay}s before stopping channel {channel_id}..."
        )

        while True:
            total = self.redis_client.scard(client_set_key) or 0
            if total > 0:
                logger.info(
                    f"New clients connected during shutdown delay for "
                    f"{channel_id} - aborting shutdown"
                )
                self.redis_client.delete(disconnect_key)
                return False

            disconnect_value = self.redis_client.get(disconnect_key)
            if not disconnect_value:
                logger.info(
                    f"Shutdown delay cancelled for {channel_id} - aborting shutdown"
                )
                return False

            try:
                if isinstance(disconnect_value, bytes):
                    disconnect_value = disconnect_value.decode()
                disconnect_time = float(disconnect_value)
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid disconnect timestamp for {channel_id}, aborting wait"
                )
                return False

            elapsed = time.time() - disconnect_time
            if elapsed >= shutdown_delay:
                total = self.redis_client.scard(client_set_key) or 0
                if total > 0:
                    logger.info(
                        f"Clients connected at end of shutdown delay for "
                        f"{channel_id} - aborting shutdown"
                    )
                    self.redis_client.delete(disconnect_key)
                    return False
                return True

            elapsed_display = max(0.0, elapsed)
            remaining = max(0.0, shutdown_delay - elapsed)
            logger.debug(
                f"Channel {channel_id[:8]} shutdown timer: "
                f"{elapsed_display:.1f}s of {shutdown_delay}s elapsed "
                f"({remaining:.1f}s remaining)"
            )
            gevent.sleep(min(poll_interval, remaining))

    def handle_client_disconnect(self, channel_id):
        """
        Handle client disconnect event - check if channel should shut down and
        whether any output profile managers can be stopped.
        """
        # We may have no local client_manager (the owner can run the stream/profile
        # for clients connected to *other* workers). Only bail if we have nothing
        # to manage for this channel at all.
        if (channel_id not in self.client_managers
                and channel_id not in self.stream_managers
                and channel_id not in self._live_stream_managers
                and channel_id not in self.profile_managers
                and channel_id not in self.output_managers
                and not self._has_local_upstream_activity(channel_id)):
            return

        try:
            client_set_key = RedisKeys.clients(channel_id)
            total = self.redis_client.scard(client_set_key) or 0

            logger.debug(
                f"handle_client_disconnect: channel={channel_id[:8]} total={total} "
                f"profile_managers={list(self.profile_managers.get(channel_id, {}).keys())} "
                f"output_managers={list(self.output_managers.get(channel_id, {}).keys())}"
            )

            # Check which output formats/profiles still have active clients
            if self.output_managers.get(channel_id) or self.profile_managers.get(channel_id):
                if total > 0:
                    remaining_ids = self.redis_client.smembers(client_set_key)
                    remaining_list = [
                        cid.decode() if isinstance(cid, bytes) else cid
                        for cid in remaining_ids
                    ]
                    pipe = self.redis_client.pipeline(transaction=False)
                    for cid in remaining_list:
                        pipe.hget(RedisKeys.client_metadata(channel_id, cid), "output_format")
                        pipe.hget(RedisKeys.client_metadata(channel_id, cid), "output_profile_id")
                    results = pipe.execute()
                    active_formats = set()
                    active_profiles = set()
                    active_manager_keys = set()
                    for i in range(0, len(results), 2):
                        fmt = results[i]
                        pid = results[i + 1]
                        if fmt:
                            fmt_str = fmt.decode() if isinstance(fmt, bytes) else fmt
                            active_formats.add(fmt_str)
                            pid_str = (pid.decode() if isinstance(pid, bytes) else pid) if pid else ''
                            if pid_str:
                                try:
                                    active_manager_keys.add(f"{fmt_str}:p{int(pid_str)}")
                                except ValueError:
                                    pass
                            else:
                                active_manager_keys.add(fmt_str)
                        if pid:
                            pid_str = pid.decode() if isinstance(pid, bytes) else pid
                            if pid_str:
                                try:
                                    active_profiles.add(int(pid_str))
                                except ValueError:
                                    pass
                else:
                    active_formats = set()
                    active_profiles = set()
                    active_manager_keys = set()

                logger.debug(
                    f"handle_client_disconnect: channel={channel_id[:8]} "
                    f"active_profiles={active_profiles} active_manager_keys={active_manager_keys}"
                )

                for fmt in list(self.output_managers.get(channel_id, {}).keys()):
                    if fmt not in active_manager_keys:
                        logger.info(f"[output:{fmt}] No clients remain, stopping manager for channel {channel_id}")
                        self.stop_output_format(channel_id, fmt)

                for pid in list(self.profile_managers.get(channel_id, {}).keys()):
                    if pid not in active_profiles:
                        logger.info(f"[Profile:{pid}] No clients remain, stopping transcode for channel {channel_id}")
                        self.stop_output_profile(channel_id, pid)

            if total == 0:
                logger.debug(f"No clients left after disconnect event - stopping channel {channel_id}")

                shutdown_delay = ConfigHelper.channel_shutdown_delay()
                disconnect_key = RedisKeys.last_client_disconnect(channel_id)

                if shutdown_delay > 0:
                    if not self.redis_client.get(disconnect_key):
                        self.redis_client.setex(
                            disconnect_key,
                            self._shutdown_disconnect_ttl(),
                            str(time.time()),
                        )
                    if not self._wait_for_shutdown_delay(channel_id):
                        return
                else:
                    self.redis_client.setex(
                        disconnect_key,
                        self._shutdown_disconnect_ttl(),
                        str(time.time()),
                    )

                # Coordinated stop runs local teardown + Redis cleanup once.
                # Do not call _stop_upstream_before_redis_cleanup here — it races
                # with stop_channel and can leave stop_channel blocked on stderr join
                # before _clean_redis_keys ever runs (orphaned buffer:index keys).
                self._coordinated_stop_channel(channel_id)
        except Exception as e:
            logger.error(f"Error handling client disconnect for channel {channel_id}: {e}")

    def _channel_unavailable_for_new_clients(self, channel_id):
        """True when new clients or ownership re-acquisition should be refused."""
        from .services.channel_service import ChannelService
        return ChannelService.is_channel_unavailable_for_new_clients(channel_id)

    def _channel_teardown_active(self, channel_id):
        """True when a coordinated stop is in progress (Redis-visible to all workers)."""
        from .services.channel_service import ChannelService
        return ChannelService.is_channel_teardown_active(channel_id)

    def _coordinated_stop_channel(self, channel_id):
        """Stop a channel with Redis markers and pubsub visible to all uWSGI workers."""
        from .services.channel_service import ChannelService
        return ChannelService.stop_channel(channel_id)

    def _force_clear_channel_clients(self, channel_id):
        """Remove all client entries from Redis for a wedged channel."""
        if not self.redis_client:
            return 0
        removed = ClientManager.clear_all_clients(self.redis_client, channel_id)
        if removed:
            logger.warning(f"Force-cleared {removed} client(s) from channel {channel_id}")
        return removed

    # ------------------------------------------------------------------
    # Output format lifecycle
    # ------------------------------------------------------------------

    def get_buffer(self, channel_id, profile=None):
        """
        Resolve the source buffer for a given channel and optional profile.

        With no profile, returns the raw input StreamBuffer.
        With a profile_id, returns that profile's transcoded output StreamBuffer.
        Raises KeyError if the profile buffer is not yet active.
        """
        if profile is not None:
            channel_profiles = self.profile_buffers.get(channel_id, {})
            if profile not in channel_profiles:
                raise KeyError(f"Profile '{profile}' not active for channel {channel_id}")
            return channel_profiles[profile]
        return self.stream_buffers.get(channel_id)

    def ensure_output_format(self, channel_id, fmt, source_buffer=None) -> bool:
        """
        Start an output format manager for this channel if not already running.
        Only the TS-owning worker starts the manager; non-owners read the shared buffer.
        Returns True if a manager is active (locally or on another worker).
        """
        if channel_id in self.output_managers and fmt in self.output_managers[channel_id]:
            return True

        if not self.redis_client:
            return False

        state = self.redis_client.get(RedisKeys.output_state(channel_id, fmt))
        if state == 'active':
            owner_val = self.redis_client.get(RedisKeys.output_owner(channel_id, fmt))
            if owner_val and owner_val != self.worker_id:
                logger.info(f"[output:{fmt}] Channel {channel_id}: manager active on another worker")
                return True
            # State says active but we have no local manager - stale state from a dead manager.
            # Fall through to restart if we can.
            logger.warning(
                f"[output:{fmt}] Channel {channel_id}: stale active state detected "
                f"(owner={owner_val}), restarting manager"
            )

        if not self.am_i_owner(channel_id):
            # Ask the TS-owning worker to start the manager, then poll until active.
            logger.info(f"[output:{fmt}] Channel {channel_id}: requesting owner to start manager")
            self.redis_client.publish(
                f"live:events:{channel_id}",
                json.dumps({
                    "event": EventType.ENSURE_OUTPUT_FORMAT,
                    "channel_id": channel_id,
                    "fmt": fmt,
                    "timestamp": time.time(),
                })
            )
            deadline = time.time() + 5
            while time.time() < deadline:
                gevent.sleep(0.1)
                state = self.redis_client.get(RedisKeys.output_state(channel_id, fmt))
                if state == 'active':
                    logger.info(f"[output:{fmt}] Channel {channel_id}: manager started by owner")
                    return True
            logger.warning(f"[output:{fmt}] Channel {channel_id}: owner did not start manager within 5s")
            return False

        ts_buffer = source_buffer
        if ts_buffer is None:
            _, profile_id = self._parse_output_key(fmt)
            if profile_id is not None:
                ts_buffer = self.profile_buffers.get(channel_id, {}).get(profile_id)
        if ts_buffer is None:
            ts_buffer = self.stream_buffers.get(channel_id)
        if not ts_buffer:
            logger.error(f"[output:{fmt}] Channel {channel_id}: no TS buffer, cannot start manager")
            return False

        _OUTPUT_FORMAT_MANAGERS = {
            'fmp4': FMP4RemuxManager,
        }
        base_fmt, _ = self._parse_output_key(fmt)
        manager_cls = _OUTPUT_FORMAT_MANAGERS.get(base_fmt)
        if manager_cls is None:
            logger.error(f"[output:{fmt}] Unknown output format '{base_fmt}'")
            return False
        manager = manager_cls(channel_id, ts_buffer, self.worker_id, fmt=fmt)

        started = manager.start()
        if started:
            self.output_managers.setdefault(channel_id, {})[fmt] = manager
            logger.info(f"[output:{fmt}] Channel {channel_id}: manager started")
        return started

    @staticmethod
    def _parse_output_key(fmt):
        """
        Split a compound output manager key into (base_format, profile_id).
        'fmp4'    -> ('fmp4', None)
        'fmp4:p1' -> ('fmp4', 1)
        'hls:p3' -> ('hls', 3)
        """
        if ':p' in fmt:
            base, _, suffix = fmt.rpartition(':p')
            try:
                return base, int(suffix)
            except ValueError:
                pass
        return fmt, None

    def stop_output_format(self, channel_id, fmt):
        """Stop and remove a specific output format manager for this channel."""
        channel_managers = self.output_managers.get(channel_id, {})
        manager = channel_managers.pop(fmt, None)
        if not channel_managers:
            self.output_managers.pop(channel_id, None)
        if manager:
            try:
                manager.stop()
                logger.info(f"[output:{fmt}] Channel {channel_id}: manager stopped")
            except Exception as e:
                logger.error(f"[output:{fmt}] Channel {channel_id}: error stopping manager: {e}")

    def stop_all_output_formats(self, channel_id):
        """Stop all output format managers for a channel."""
        for fmt in list(self.output_managers.get(channel_id, {}).keys()):
            self.stop_output_format(channel_id, fmt)

    # ------------------------------------------------------------------
    # Output profile lifecycle
    # ------------------------------------------------------------------

    def ensure_output_profile(self, channel_id, profile_id, command) -> bool:
        """
        Start an OutputProfileManager for this (channel, profile) pair if not
        already running.  Only the TS-owning worker starts the process; all
        workers (including non-owners) get a StreamBuffer wired to the same
        Redis keys so they can serve clients.

        Returns True once the profile buffer is available in self.profile_buffers.
        """
        channel_profiles = self.profile_buffers.get(channel_id, {})
        logger.debug(
            f"[Profile:{profile_id}:{channel_id[:8]}] ensure_output_profile() called, "
            f"already_buffered={profile_id in channel_profiles} "
            f"is_owner={self.am_i_owner(channel_id)}"
        )
        if profile_id in channel_profiles:
            existing = self.profile_managers.get(channel_id, {}).get(profile_id)
            if existing is not None:
                # Owner: verify the FFmpeg process is still running.
                if existing._process is not None and existing._process.poll() is None:
                    return True
                logger.warning(
                    f"[Profile:{profile_id}:{channel_id[:8]}] "
                    "Transcode process exited, restarting"
                )
                self.profile_managers.get(channel_id, {}).pop(profile_id, None)
                if not self.profile_managers.get(channel_id):
                    self.profile_managers.pop(channel_id, None)
                self.profile_buffers.get(channel_id, {}).pop(profile_id, None)
                if not self.profile_buffers.get(channel_id):
                    self.profile_buffers.pop(channel_id, None)
                existing.stop()
            else:
                # Non-owner reader buffer: verify the owner's state is still active.
                if not self.redis_client:
                    return True
                state = self.redis_client.get(
                    RedisKeys.output_state(channel_id, f"mpegts:p{profile_id}")
                )
                if state == PROFILE_STATE_ACTIVE:
                    return True
                logger.warning(
                    f"[Profile:{profile_id}:{channel_id[:8]}] "
                    "Reader buffer exists but profile state not active, resetting"
                )
                self.profile_buffers.get(channel_id, {}).pop(profile_id, None)
                if not self.profile_buffers.get(channel_id):
                    self.profile_buffers.pop(channel_id, None)

        if not self.redis_client:
            return False

        # Check if another worker already owns the transcode
        state = self.redis_client.get(RedisKeys.output_state(channel_id, f"mpegts:p{profile_id}"))
        if state == PROFILE_STATE_ACTIVE:
            owner_val = self.redis_client.get(RedisKeys.output_owner(channel_id, f"mpegts:p{profile_id}"))
            if owner_val and owner_val != self.worker_id:
                # Non-owner: create a reader buffer pointing at the same Redis keys
                manager = OutputProfileManager(
                    channel_id, profile_id, command,
                    self.stream_buffers.get(channel_id), self.worker_id
                )
                # start() will fail to acquire lock, but sets manager.output_buffer
                manager.start()
                self.profile_buffers.setdefault(channel_id, {})[profile_id] = manager.output_buffer
                logger.info(
                    f"[Profile:{profile_id}:{channel_id[:8]}] "
                    "Using transcode buffer from owning worker"
                )
                return True
            # State is active but we own it (or owner missing) with no local manager - stale.
            logger.warning(
                f"[Profile:{profile_id}:{channel_id[:8]}] "
                f"Stale active state detected (owner={owner_val}), restarting transcode"
            )

        if not self.am_i_owner(channel_id):
            logger.info(
                f"[Profile:{profile_id}:{channel_id[:8]}] "
                "Not TS owner, requesting owner to start transcode"
            )
            self.redis_client.publish(
                f"live:events:{channel_id}",
                json.dumps({
                    "event": EventType.ENSURE_OUTPUT_PROFILE,
                    "channel_id": channel_id,
                    "profile_id": profile_id,
                    "command": command,
                    "timestamp": time.time(),
                })
            )
            state_key = RedisKeys.output_state(channel_id, f"mpegts:p{profile_id}")
            deadline = time.time() + 5
            while time.time() < deadline:
                gevent.sleep(0.1)
                state = self.redis_client.get(state_key)
                if state == PROFILE_STATE_ACTIVE:
                    # Non-owner: wire up a reader buffer pointing at the same Redis keys.
                    manager = OutputProfileManager(
                        channel_id, profile_id, command,
                        self.stream_buffers.get(channel_id), self.worker_id
                    )
                    manager.start()
                    self.profile_buffers.setdefault(channel_id, {})[profile_id] = manager.output_buffer
                    logger.info(
                        f"[Profile:{profile_id}:{channel_id[:8]}] "
                        "Using transcode buffer from owning worker"
                    )
                    return True
            logger.warning(
                f"[Profile:{profile_id}:{channel_id[:8]}] "
                "Owner did not start transcode within 5s"
            )
            return False

        ts_buffer = self.stream_buffers.get(channel_id)
        if not ts_buffer:
            logger.error(
                f"[Profile:{profile_id}:{channel_id[:8]}] "
                "No TS buffer available, cannot start transcode"
            )
            return False

        manager = OutputProfileManager(
            channel_id, profile_id, command, ts_buffer, self.worker_id
        )
        started = manager.start()
        if started:
            self.profile_managers.setdefault(channel_id, {})[profile_id] = manager
            self.profile_buffers.setdefault(channel_id, {})[profile_id] = manager.output_buffer
            logger.info(f"[Profile:{profile_id}:{channel_id[:8]}] Transcode started")
            return True
        return False

    def stop_output_profile(self, channel_id, profile_id):
        """Stop a profile transcode manager and remove its buffer."""
        logger.debug(f"[Profile:{profile_id}:{channel_id[:8]}] stop_output_profile() called")
        channel_managers = self.profile_managers.get(channel_id, {})
        manager = channel_managers.pop(profile_id, None)
        if not channel_managers:
            self.profile_managers.pop(channel_id, None)

        self.profile_buffers.get(channel_id, {}).pop(profile_id, None)
        if not self.profile_buffers.get(channel_id):
            self.profile_buffers.pop(channel_id, None)

        if manager:
            try:
                manager.stop()
                logger.info(
                    f"[Profile:{profile_id}:{channel_id[:8]}] Transcode stopped"
                )
            except Exception as e:
                logger.error(
                    f"[Profile:{profile_id}:{channel_id[:8]}] Error stopping: {e}"
                )

    def stop_all_output_profiles(self, channel_id):
        """Stop all profile transcode managers for a channel."""
        for pid in list(self.profile_managers.get(channel_id, {}).keys()):
            self.stop_output_profile(channel_id, pid)

    def _collect_channel_stop_event_data(self, channel_id):
        """Snapshot metadata for channel_stop logging before Redis keys are deleted."""
        channel_name = self._channel_names.pop(channel_id, None) or str(channel_id)
        runtime = None
        total_bytes = None
        if self.redis_client:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            metadata = self.redis_client.hgetall(metadata_key)
            if metadata:
                if 'init_time' in metadata:
                    try:
                        init_time = float(metadata['init_time'])
                        runtime = round(time.time() - init_time, 2)
                    except Exception:
                        pass
                if 'total_bytes' in metadata:
                    try:
                        total_bytes = int(metadata['total_bytes'])
                    except Exception:
                        pass
        return {
            'channel_id': channel_id,
            'channel_name': channel_name,
            'runtime': runtime,
            'total_bytes': total_bytes,
        }

    def _spawn_channel_stop_event(self, stop_event_data):
        """Log channel_stop without blocking teardown (DB/connect dispatch can hang)."""
        if not stop_event_data:
            return

        def _log_stop():
            log_system_event('channel_stop', **stop_event_data)

        gevent.spawn(_log_stop)

    def _get_stream_thread(self, channel_id):
        thread_name = f"stream-{channel_id}"
        for thread in threading.enumerate():
            if thread.name == thread_name:
                return thread
        return None

    def _has_local_upstream_activity(self, channel_id):
        """True when this worker runs a local ffmpeg / stream-{uuid} OS thread."""
        if channel_id in self.stream_managers:
            return True
        if channel_id in self._live_stream_managers:
            return True
        thread = self._get_stream_thread(channel_id)
        return thread is not None and thread.is_alive()

    def _broadcast_upstream_stop(self, channel_id):
        """Ask every uWSGI worker to stop local ffmpeg for this channel."""
        from .services.channel_service import ChannelService

        if not self.redis_client:
            return
        try:
            ChannelService.mark_channel_stopping(channel_id, broadcast=True)
            logger.info(
                f"Broadcast upstream stop for channel {channel_id} to all workers"
            )
        except Exception as e:
            logger.error(
                f"Error broadcasting upstream stop for channel {channel_id}: {e}"
            )

    @staticmethod
    def _channel_id_from_metadata_key(key):
        if isinstance(key, bytes):
            key = key.decode('utf-8', errors='replace')
        parts = key.split(':')
        if len(parts) >= 3:
            return parts[2]
        return None

    def _stop_upstream_before_redis_cleanup(self, channel_id):
        """Stop local ffmpeg before deleting Redis keys (prevents delete/recreate loops)."""
        if self._has_local_upstream_activity(channel_id):
            logger.info(
                f"Channel {channel_id} has local upstream activity - stopping processes"
            )
            self._stop_local_stream_activity(channel_id)
            return
        self._broadcast_upstream_stop(channel_id)

    def _join_stream_thread(self, channel_id, timeout=2.0):
        thread = self._get_stream_thread(channel_id)
        if thread and thread.is_alive():
            logger.info(f"Waiting for stream thread to terminate for channel {channel_id}")
            try:
                thread.join(timeout=timeout)
                if thread.is_alive():
                    logger.warning(
                        f"Stream thread for channel {channel_id} did not terminate within {timeout}s"
                    )
            except RuntimeError:
                logger.debug(f"Could not join stream thread for channel {channel_id}")

    def _resolve_stream_manager(self, channel_id):
        manager = self.stream_managers.pop(channel_id, None)
        if manager is None:
            manager = self._live_stream_managers.pop(channel_id, None)
        return manager

    def _signal_upstream_shutdown(self, channel_id):
        """Halt upstream Redis writes immediately without blocking on ffmpeg join."""
        if channel_id in self.stream_buffers:
            self.stream_buffers[channel_id].stopping = True
        for registry in (self.stream_managers, self._live_stream_managers):
            manager = registry.get(channel_id)
            if manager is None:
                continue
            manager.stopping = True
            manager.stop_requested = True
            if getattr(manager, 'buffer', None) is not None:
                manager.buffer.stopping = True

    def _get_local_stop_lock(self, channel_id):
        lock = self._local_stop_locks.get(channel_id)
        if lock is None:
            lock = threading.Lock()
            self._local_stop_locks[channel_id] = lock
        return lock

    def _stop_local_stream_activity(self, channel_id):
        """Stop local ffmpeg/stream threads regardless of registry state."""
        lock = self._get_local_stop_lock(channel_id)
        if not lock.acquire(blocking=False):
            logger.debug(
                f"Local stop already in progress for channel {channel_id}, skipping duplicate"
            )
            return
        try:
            self._stop_local_stream_activity_locked(channel_id)
        finally:
            lock.release()
            self._local_stop_locks.pop(channel_id, None)

    def _stop_local_stream_activity_locked(self, channel_id):
        stream_manager = self._resolve_stream_manager(channel_id)
        if stream_manager is not None:
            if hasattr(stream_manager, 'stop'):
                try:
                    stream_manager.stop()
                except Exception as e:
                    logger.error(f"Error stopping stream manager for channel {channel_id}: {e}")
            logger.info(f"Stopped stream manager for channel {channel_id}")
        elif self._get_stream_thread(channel_id):
            logger.warning(
                f"Found live stream thread for channel {channel_id} without a manager reference"
            )
            if channel_id in self.stream_buffers:
                self.stream_buffers[channel_id].stopping = True

        self._join_stream_thread(channel_id)

        if channel_id in self.stream_buffers:
            buffer = self.stream_buffers.pop(channel_id)
            if hasattr(buffer, 'stop'):
                try:
                    buffer.stop()
                except Exception as e:
                    logger.error(f"Error stopping buffer for channel {channel_id}: {e}")
            logger.info(f"Removed stream buffer for channel {channel_id}")

        if channel_id in self.client_managers:
            try:
                client_manager = self.client_managers.pop(channel_id)
                if hasattr(client_manager, 'stop'):
                    client_manager.stop()
                logger.info(f"Removed client manager for channel {channel_id}")
            except KeyError:
                logger.debug(f"Client manager for channel {channel_id} already removed")

        self.stop_all_output_formats(channel_id)
        self.stop_all_output_profiles(channel_id)
        self.profile_managers.pop(channel_id, None)
        self.profile_buffers.pop(channel_id, None)
        self._live_stream_managers.pop(channel_id, None)

    def _recover_stuck_channel_stops(self):
        """Force cleanup when stop_channel never finishes (e.g. blocked on logging)."""
        if not self._stopping_channels:
            return

        now = time.time()
        stuck_threshold = max(10, ConfigHelper.channel_shutdown_delay() * 2)

        for channel_id in list(self._stopping_channels):
            started = self._stopping_since.get(channel_id, now)
            if now - started < stuck_threshold:
                continue

            logger.error(
                f"Channel {channel_id} stop_channel stuck for {now - started:.0f}s "
                f"- forcing local and Redis cleanup"
            )
            self._stopping_channels.discard(channel_id)
            self._stopping_since.pop(channel_id, None)

            try:
                self._stop_local_stream_activity(channel_id)
                self._clean_redis_keys(channel_id)
            except Exception as e:
                logger.error(f"Error during forced cleanup for channel {channel_id}: {e}")

    def stop_channel(self, channel_id):
        """Stop a channel with proper ownership handling"""
        if channel_id in self._stopping_channels:
            logger.debug(f"stop_channel already in progress for {channel_id}, ignoring duplicate call")
            return
        self._stopping_channels.add(channel_id)
        self._stopping_since[channel_id] = time.time()
        stop_event_data = None
        redis_cleaned = False
        try:
            logger.info(f"Stopping channel {channel_id}")

            if self.redis_client:
                stop_key = RedisKeys.channel_stopping(channel_id)
                if self.redis_client.exists(stop_key):
                    self.redis_client.expire(stop_key, 60)
                else:
                    self.redis_client.setex(stop_key, 60, "true")

            was_owner = self.am_i_owner(channel_id)
            if was_owner:
                logger.info(
                    f"This worker ({self.worker_id}) is the owner - closing provider connection"
                )
                stop_event_data = self._collect_channel_stop_event_data(channel_id)

            # Stop new chunk writes before Redis cleanup; do not block on ffmpeg join yet.
            self._signal_upstream_shutdown(channel_id)

            # Release profile slots and delete Redis keys before any blocking local stop.
            # A concurrent disconnect + cleanup-thread stop used to wedge here behind a
            # 2s stderr join, never reaching scan/delete (bare buffer:index with TTL -1).
            self._clean_redis_keys(channel_id)
            redis_cleaned = True

            if was_owner:
                self.release_ownership(channel_id)

            self._stop_local_stream_activity(channel_id)
            self._spawn_channel_stop_event(stop_event_data)

            return True
        except Exception as e:
            logger.error(f"Error stopping channel {channel_id}: {e}")
            return False
        finally:
            if not redis_cleaned:
                try:
                    self._clean_redis_keys(channel_id)
                except Exception as e:
                    logger.error(
                        f"Error cleaning Redis keys for channel {channel_id} during finally: {e}"
                    )
            self._stopping_channels.discard(channel_id)
            self._stopping_since.pop(channel_id, None)

    def check_inactive_channels(self):
        """Check for inactive channels (no clients) and stop them"""
        channels_to_stop = []

        for channel_id, client_manager in self.client_managers.items():
            if client_manager.get_client_count() == 0:
                channels_to_stop.append(channel_id)

        for channel_id in channels_to_stop:
            logger.info(f"Auto-stopping inactive channel {channel_id}")
            self._coordinated_stop_channel(channel_id)

    def _cleanup_channel(self, channel_id: str) -> None:
        """Remove channel resources"""
        # Removed reference to non-existent fetch_threads collection
        for collection in [self.stream_managers, self.stream_buffers, self.client_managers]:
            collection.pop(channel_id, None)

    def shutdown(self) -> None:
        """Stop all channels and cleanup"""
        for channel_id in list(self.stream_managers.keys()):
            self._coordinated_stop_channel(channel_id)

    def _start_cleanup_thread(self):
        """Start background thread to maintain ownership and clean up resources"""
        def cleanup_task():
            while True:
                try:
                    close_old_connections()
                    # Send worker heartbeat first
                    if self.redis_client:
                        worker_heartbeat_key = f"live:worker:{self.worker_id}:heartbeat"
                        self._execute_redis_command(
                            lambda: self.redis_client.setex(worker_heartbeat_key, 30, str(time.time()))
                        )

                    # Refresh channel registry
                    self.refresh_channel_registry()

                    # Recover channels whose stop_channel call never returned
                    self._recover_stuck_channel_stops()

                    # Create a unified list of all channels we have locally
                    all_local_channels = (
                        set(self.stream_managers.keys())
                        | set(self.client_managers.keys())
                        | set(self._live_stream_managers.keys())
                    )

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
                                if metadata and 'state' in metadata:
                                    channel_state = metadata['state']

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
                            if channel_state in [ChannelState.INITIALIZING, ChannelState.CONNECTING, ChannelState.WAITING_FOR_CLIENTS]:
                                # Check if channel is already stopping
                                if self.redis_client:
                                    stop_key = RedisKeys.channel_stopping(channel_id)
                                    if self.redis_client.exists(stop_key):
                                        logger.debug(f"Channel {channel_id} is already stopping - skipping monitor shutdown")
                                        continue

                                # Get connection_ready_time from metadata (indicates if channel reached ready state)
                                connection_ready_time = None
                                if metadata and 'connection_ready_time' in metadata:
                                    try:
                                        connection_ready_time = float(metadata['connection_ready_time'])
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
                                                connection_attempt_time = float(attempt_value)
                                            except (ValueError, TypeError):
                                                pass

                                    # Also get init time as a fallback
                                    init_time = None
                                    if metadata and 'init_time' in metadata:
                                        try:
                                            init_time = float(metadata['init_time'])
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
                                                self._coordinated_stop_channel(channel_id)
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
                                                self._coordinated_stop_channel(channel_id)
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
                                            disconnect_time = float(disconnect_value)
                                        except (ValueError, TypeError) as e:
                                            logger.error(f"Invalid disconnect time for channel {channel_id}: {e}")

                                current_time = time.time()

                                if not disconnect_time:
                                    # First time seeing zero clients, set timestamp
                                    if self.redis_client:
                                        self.redis_client.setex(
                                            disconnect_key,
                                            self._shutdown_disconnect_ttl(),
                                            str(current_time),
                                        )
                                    logger.warning(f"No clients detected for channel {channel_id}, starting shutdown timer")
                                elif current_time - disconnect_time > ConfigHelper.channel_shutdown_delay():
                                    # We've had no clients for the shutdown delay period
                                    logger.warning(f"No clients for {current_time - disconnect_time:.1f}s, stopping channel {channel_id}")
                                    self._coordinated_stop_channel(channel_id)
                                else:
                                    # Still in shutdown delay period
                                    logger.debug(f"Channel {channel_id} shutdown timer: "
                                                f"{current_time - disconnect_time:.1f}s of "
                                                f"{ConfigHelper.channel_shutdown_delay()}s elapsed")
                            else:
                                # There are clients or we're still connecting - clear any disconnect timestamp
                                if self.redis_client:
                                    self.redis_client.delete(
                                        RedisKeys.last_client_disconnect(channel_id)
                                    )

                        else:
                            # === NON-OWNER CHANNEL HANDLING ===
                            # Safety: if we have a stream_manager, we ARE the real owner
                            # but the Redis key may have expired. Try to re-acquire.
                            if (channel_id in self.stream_managers
                                    or channel_id in self._live_stream_managers):
                                # Ownership was explicitly released by an active stop_channel call -
                                # don't fight the shutdown by trying to re-acquire.
                                if channel_id in self._stopping_channels:
                                    continue

                                if self._channel_unavailable_for_new_clients(channel_id):
                                    logger.info(
                                        f"Channel {channel_id} teardown active with local stream_manager; "
                                        f"finishing stop instead of re-acquiring ownership"
                                    )
                                    self.stop_channel(channel_id)
                                    continue

                                logger.warning(
                                    f"Ownership gap for {channel_id}: this worker has stream_manager "
                                    f"but am_i_owner returned False. Attempting re-acquisition."
                                )
                                reacquired = self.extend_ownership(channel_id)
                                if reacquired:
                                    logger.info(f"Successfully re-acquired ownership for {channel_id}")
                                    continue
                                else:
                                    # Defer cleanup if we still have active clients — give the
                                    # new owner time to spin up its own stream before we tear
                                    # ours down, so viewers don't get disconnected.
                                    has_clients = (
                                        channel_id in self.client_managers
                                        and self.client_managers[channel_id].get_client_count() > 0
                                    )
                                    if has_clients:
                                        logger.warning(
                                            f"Ownership lost for {channel_id} but {self.client_managers[channel_id].get_client_count()} "
                                            f"client(s) still connected — deferring cleanup to next cycle"
                                        )
                                        continue
                                    logger.error(f"Failed to re-acquire ownership for {channel_id}, will clean up")

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

                # Fallback sweep: stop profile managers with no active clients.
                # Only runs every 30s - the primary path (handle_client_disconnect)
                # handles normal disconnects within milliseconds. This only fires if
                # a pubsub event was dropped or the listener was restarting.
                now = time.time()
                if self.profile_managers and self.redis_client and (
                    now - getattr(self, '_last_profile_sweep', 0) >= 30
                ):
                    self._last_profile_sweep = now
                    for ch_id in list(self.profile_managers.keys()):
                        ch_managers = self.profile_managers.get(ch_id, {})
                        if not ch_managers:
                            continue
                        client_set_key = RedisKeys.clients(ch_id)
                        remaining_ids = self.redis_client.smembers(client_set_key)
                        if remaining_ids:
                            remaining_list = [
                                cid.decode() if isinstance(cid, bytes) else cid
                                for cid in remaining_ids
                            ]
                            pipe = self.redis_client.pipeline(transaction=False)
                            for cid in remaining_list:
                                pipe.hget(RedisKeys.client_metadata(ch_id, cid), "output_profile_id")
                            results = pipe.execute()
                            active_profiles = set()
                            for pid_raw in results:
                                if pid_raw:
                                    pid_str = pid_raw.decode() if isinstance(pid_raw, bytes) else pid_raw
                                    if pid_str:
                                        try:
                                            active_profiles.add(int(pid_str))
                                        except ValueError:
                                            pass
                        else:
                            active_profiles = set()

                        for pid in list(ch_managers.keys()):
                            if pid not in active_profiles:
                                logger.info(
                                    f"[Profile:{pid}] Cleanup sweep: no active clients, "
                                    f"stopping transcode for channel {ch_id}"
                                )
                                self.stop_output_profile(ch_id, pid)

                gevent.sleep(ConfigHelper.cleanup_check_interval())

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
            channel_pattern = "live:channel:*:metadata"
            channel_keys = self.redis_client.keys(channel_pattern)

            for key in channel_keys:
                try:
                    channel_id = self._channel_id_from_metadata_key(key)
                    if not channel_id:
                        continue

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

                            self._stop_upstream_before_redis_cleanup(channel_id)
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
            channel_pattern = "live:channel:*:metadata"
            channel_keys = self.redis_client.keys(channel_pattern)

            for key in channel_keys:
                try:
                    channel_id = self._channel_id_from_metadata_key(key)
                    if not channel_id:
                        continue

                    # Skip channel ids that don't follow Dispatcharr's UUID
                    # convention. Those are managed by features outside of
                    # ProxyServer (e.g. timeshift catch-up sessions use a
                    # `timeshift_<channel>_<ts>_<sid>` virtual id and are
                    # owned by the WSGI request that opened them — they
                    # expire naturally via the clients-set TTL).
                    if channel_id.startswith("timeshift_"):
                        continue

                    # Get metadata first
                    metadata = self.redis_client.hgetall(key)
                    if not metadata:
                        # Empty metadata - clean it up
                        logger.warning(f"Found empty metadata for channel {channel_id} - cleaning up")
                        self._stop_upstream_before_redis_cleanup(channel_id)
                        self._clean_redis_keys(channel_id)
                        continue

                    # Get owner
                    owner = metadata.get('owner', '') if 'owner' in metadata else ''

                    # Check if owner is still alive
                    owner_alive = False
                    if owner:
                        owner_heartbeat_key = f"live:worker:{owner}:heartbeat"
                        owner_alive = self.redis_client.exists(owner_heartbeat_key)

                    # Check client count
                    client_set_key = RedisKeys.clients(channel_id)
                    client_count = self.redis_client.scard(client_set_key) or 0

                    # If no owner and no clients, clean it up
                    if not owner_alive and client_count == 0:
                        state = metadata.get('state', 'unknown')
                        logger.warning(f"Found orphaned metadata for channel {channel_id} (state: {state}, owner: {owner}, clients: {client_count}) - cleaning up")

                        self._stop_upstream_before_redis_cleanup(channel_id)
                        self._clean_redis_keys(channel_id)
                    elif not owner_alive and client_count > 0:
                        # SCARD may include ghost entries from a dead worker's
                        # expired metadata hashes. Validate before deciding.
                        stale_ids = ClientManager.remove_ghost_clients(
                            self.redis_client, channel_id
                        )
                        real_count = max(0, client_count - len(stale_ids))
                        if real_count <= 0:
                            # No real clients remain — safe to clean up.
                            state = metadata.get('state', 'unknown')
                            logger.warning(
                                f"Orphaned channel {channel_id} (state: {state}, "
                                f"owner: {owner}) had {client_count} ghost client(s) "
                                f"- cleaning up"
                            )
                            self._stop_upstream_before_redis_cleanup(channel_id)
                            self._clean_redis_keys(channel_id)
                        else:
                            if self._channel_teardown_active(channel_id):
                                logger.warning(
                                    f"Orphaned channel {channel_id} still has "
                                    f"{real_count} client(s) during teardown; forcing cleanup"
                                )
                                self._force_clear_channel_clients(channel_id)
                                self._stop_upstream_before_redis_cleanup(channel_id)
                                self._clean_redis_keys(channel_id)
                            else:
                                logger.warning(
                                    f"Orphaned channel {channel_id} still has "
                                    f"{real_count} live client(s) after ghost removal "
                                    f"- may need ownership takeover"
                                )

                except Exception as e:
                    logger.error(f"Error processing metadata key {key}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error checking orphaned metadata: {e}", exc_info=True)

    def _clean_redis_keys(self, channel_id):
        """Clean up all Redis keys for a channel more efficiently"""
        total_deleted = 0

        try:
            # Release the M3U profile slot while channel_stream / metadata still exist.
            # Scanning live:channel keys first deletes metadata and breaks release_stream()
            # fallback, leaving profile_connections counters stuck (e.g. profile_connections:70 = 1).
            try:
                channel = Channel.objects.get(uuid=channel_id)
                if not channel.release_stream():
                    logger.debug(f"Channel {channel_id}: release_stream found no keys to clean")
            except (Channel.DoesNotExist, Exception):
                try:
                    stream = Stream.objects.get(stream_hash=channel_id)
                    if not stream.release_stream():
                        logger.debug(f"Stream {channel_id}: release_stream found no keys to clean")
                except (Stream.DoesNotExist, Exception):
                    logger.debug(f"No Channel or Stream found for {channel_id}")

            if self.redis_client:
                try:
                    patterns = [
                        f"live:channel:{channel_id}:*",
                        RedisKeys.events_channel(channel_id),
                    ]

                    for pattern in patterns:
                        cursor = 0
                        while True:
                            cursor, keys = self.redis_client.scan(cursor, match=pattern, count=100)
                            if keys:
                                self.redis_client.delete(*keys)
                                total_deleted += len(keys)

                            if cursor == 0:
                                break

                    logger.info(f"Cleaned up {total_deleted} Redis keys for channel {channel_id}")
                except Exception as e:
                    logger.error(f"Error cleaning Redis keys for channel {channel_id}: {e}")
        finally:
            close_old_connections()

        return total_deleted

    def refresh_channel_registry(self):
        """Refresh TTL for active channels using standard keys"""
        if not self.redis_client:
            return

        # Refresh registry entries for channels we own and are actively serving.
        # Skip channels mid-shutdown. Refreshing their TTL keeps zombie metadata alive.
        for channel_id in list(self.stream_buffers.keys()):
            if channel_id in self._stopping_channels:
                continue

            if not self.am_i_owner(channel_id):
                continue

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
            if metadata and 'state' in metadata:
                current_state = metadata['state']

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
            stream_manager = self._resolve_stream_manager(channel_id)
            if stream_manager is not None:
                if hasattr(stream_manager, 'stop'):
                    stream_manager.stop()
                logger.info(f"Non-owner cleanup: Stopped stream manager for channel {channel_id}")
            elif self._get_stream_thread(channel_id):
                logger.warning(
                    f"Non-owner cleanup: Found orphaned stream thread for channel {channel_id}"
                )
                if channel_id in self.stream_buffers:
                    self.stream_buffers[channel_id].stopping = True

            self._join_stream_thread(channel_id)
            self._live_stream_managers.pop(channel_id, None)

            if channel_id in self.stream_buffers:
                buffer = self.stream_buffers.pop(channel_id)
                if hasattr(buffer, 'stop'):
                    try:
                        buffer.stop()
                    except Exception as e:
                        logger.error(f"Non-owner cleanup: Error stopping buffer for {channel_id}: {e}")
                logger.info(f"Non-owner cleanup: Removed stream buffer for channel {channel_id}")

            if channel_id in self.client_managers:
                client_manager = self.client_managers.pop(channel_id)
                if hasattr(client_manager, 'stop'):
                    client_manager.stop()
                logger.info(f"Non-owner cleanup: Removed client manager for channel {channel_id}")

            # Stop profile managers owned by this worker, but only for profiles
            # that no global client still needs. Other workers may read from this
            # worker's FFmpeg output buffer, so we must check Redis before stopping.
            if channel_id in self.profile_managers:
                active_profiles = set()
                if self.redis_client:
                    client_set_key = RedisKeys.clients(channel_id)
                    remaining_ids = self.redis_client.smembers(client_set_key)
                    if remaining_ids:
                        remaining_list = [
                            cid.decode() if isinstance(cid, bytes) else cid
                            for cid in remaining_ids
                        ]
                        pipe = self.redis_client.pipeline(transaction=False)
                        for cid in remaining_list:
                            pipe.hget(RedisKeys.client_metadata(channel_id, cid), "output_profile_id")
                        results = pipe.execute()
                        for pid_raw in results:
                            if pid_raw:
                                pid_str = pid_raw.decode() if isinstance(pid_raw, bytes) else pid_raw
                                if pid_str:
                                    try:
                                        active_profiles.add(int(pid_str))
                                    except ValueError:
                                        pass

                for pid in list(self.profile_managers[channel_id].keys()):
                    if pid not in active_profiles:
                        try:
                            self.profile_managers[channel_id].pop(pid).stop()
                        except Exception:
                            pass

                if not self.profile_managers.get(channel_id):
                    self.profile_managers.pop(channel_id, None)
                    logger.info(f"Non-owner cleanup: Removed profile managers for channel {channel_id}")
                else:
                    logger.debug(
                        f"Non-owner cleanup: Kept profile managers for channel {channel_id} "
                        f"(profiles still needed: {active_profiles})"
                    )

            if channel_id in self.profile_buffers:
                del self.profile_buffers[channel_id]
                logger.info(f"Non-owner cleanup: Removed profile buffers for channel {channel_id}")

            return True
        except Exception as e:
            logger.error(f"Error cleaning up local resources: {e}", exc_info=True)
            return False
