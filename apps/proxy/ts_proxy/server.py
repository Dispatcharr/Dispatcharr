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
from typing import Dict, Optional, Set
from apps.proxy.config import TSConfig as Config
from apps.channels.models import Channel
from .stream_manager import StreamManager
from .stream_buffer import StreamBuffer
from .client_manager import ClientManager

logger = logging.getLogger("ts_proxy")

class ProxyServer:
    """Manages TS proxy server instance with worker coordination"""

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

        # Connect to Redis
        self.redis_client = None
        try:
            import redis
            from django.conf import settings

            redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
            self.redis_client = redis.from_url(redis_url)
            logger.info(f"Connected to Redis at {redis_url}")
            logger.info(f"Worker ID: {self.worker_id}")
        except Exception as e:
            self.redis_client = None
            logger.error(f"Failed to connect to Redis: {e}")

        # Start cleanup thread
        self.cleanup_interval = getattr(Config, 'CLEANUP_INTERVAL', 60)
        self._start_cleanup_thread()

        # Start event listener for Redis pubsub messages
        self._start_event_listener()

    def _start_event_listener(self):
        """Listen for events from other workers"""
        if not self.redis_client:
            return

        def event_listener():
            try:
                pubsub = self.redis_client.pubsub()
                pubsub.psubscribe("ts_proxy:events:*")

                logger.info(f"Started Redis event listener for client activity")

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
                                if event_type == "client_connected":
                                    logger.debug(f"Owner received client_connected event for channel {channel_id}")
                                    # Reset any disconnect timer
                                    # RENAMED: no_clients_since → last_client_disconnect_time
                                    disconnect_key = f"ts_proxy:channel:{channel_id}:last_client_disconnect_time"
                                    self.redis_client.delete(disconnect_key)

                                elif event_type == "client_disconnected":
                                    logger.debug(f"Owner received client_disconnected event for channel {channel_id}")
                                    # Check if any clients remain
                                    if channel_id in self.client_managers:
                                        # VERIFY REDIS CLIENT COUNT DIRECTLY
                                        client_set_key = f"ts_proxy:channel:{channel_id}:clients"
                                        total = self.redis_client.scard(client_set_key) or 0

                                        if total == 0:
                                            logger.debug(f"No clients left after disconnect event - stopping channel {channel_id}")
                                            # Set the disconnect timer for other workers to see
                                            disconnect_key = f"ts_proxy:channel:{channel_id}:last_client_disconnect_time"
                                            self.redis_client.setex(disconnect_key, 60, str(time.time()))

                                            # Get configured shutdown delay or default
                                            shutdown_delay = getattr(Config, 'CHANNEL_SHUTDOWN_DELAY', 0)

                                            if shutdown_delay > 0:
                                                logger.info(f"Waiting {shutdown_delay}s before stopping channel...")
                                                time.sleep(shutdown_delay)

                                                # Re-check client count before stopping
                                                total = self.redis_client.scard(client_set_key) or 0
                                                if total > 0:
                                                    logger.info(f"New clients connected during shutdown delay - aborting shutdown")
                                                    self.redis_client.delete(disconnect_key)
                                                    return

                                            # Stop the channel directly
                                            self.stop_channel(channel_id)


                                elif event_type == "stream_switch":
                                    logger.info(f"Owner received stream switch request for channel {channel_id}")
                                    # Handle stream switch request
                                    new_url = data.get("url")
                                    user_agent = data.get("user_agent")

                                    if new_url and channel_id in self.stream_managers:
                                        # Update metadata in Redis
                                        if self.redis_client:
                                            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
                                            self.redis_client.hset(metadata_key, "url", new_url)
                                            if user_agent:
                                                self.redis_client.hset(metadata_key, "user_agent", user_agent)

                                            # Set switch status
                                            status_key = f"ts_proxy:channel:{channel_id}:switch_status"
                                            self.redis_client.set(status_key, "switching")

                                        # Perform the stream switch
                                        stream_manager = self.stream_managers[channel_id]
                                        success = stream_manager.update_url(new_url)

                                        if success:
                                            logger.info(f"Stream switch initiated for channel {channel_id}")

                                            # Publish confirmation
                                            switch_result = {
                                                "event": "stream_switched",
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
                                                "event": "stream_switched",
                                                "channel_id": channel_id,
                                                "success": False,
                                                "url": new_url,
                                                "timestamp": time.time()
                                            }
                                            self.redis_client.publish(
                                                f"ts_proxy:events:{channel_id}",
                                                json.dumps(switch_result)
                                            )
                                elif event_type == "channel_stop":
                                    logger.info(f"Received channel stop event for channel {channel_id}")
                                    # First mark channel as stopping in Redis
                                    if self.redis_client:
                                        # Set stopping state in metadata
                                        metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
                                        if self.redis_client.exists(metadata_key):
                                            self.redis_client.hset(metadata_key, mapping={
                                                "state": "stopping", 
                                                "state_changed_at": str(time.time())
                                            })
                                    
                                    # If we have local resources for this channel, clean them up
                                    if channel_id in self.stream_buffers or channel_id in self.client_managers:
                                        # Use existing stop_channel method
                                        logger.info(f"Stopping local resources for channel {channel_id}")
                                        self.stop_channel(channel_id)
                                        
                                    # Acknowledge stop by publishing a response
                                    stop_response = {
                                        "event": "channel_stopped",
                                        "channel_id": channel_id,
                                        "worker_id": self.worker_id,
                                        "timestamp": time.time()
                                    }
                                    self.redis_client.publish(
                                        f"ts_proxy:events:{channel_id}",
                                        json.dumps(stop_response)
                                    )
                                elif event_type == "client_stop":
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
                                            stop_key = f"ts_proxy:channel:{channel_id}:client:{client_id}:stop"
                                            self.redis_client.setex(stop_key, 30, "true")  # 30 second TTL
                                            logger.info(f"Set stop key for client {client_id}")
                    except Exception as e:
                        logger.error(f"Error processing event message: {e}")
            except Exception as e:
                logger.error(f"Error in event listener: {e}")
                time.sleep(5)  # Wait before reconnecting
                # Try to restart the listener
                self._start_event_listener()

        thread = threading.Thread(target=event_listener, daemon=True)
        thread.name = "redis-event-listener"
        thread.start()

    def get_channel_owner(self, channel_id):
        """Get the worker ID that owns this channel with proper error handling"""
        if not self.redis_client:
            return None

        try:
            lock_key = f"ts_proxy:channel:{channel_id}:owner"
            owner = self.redis_client.get(lock_key)
            if owner:
                return owner.decode('utf-8')
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
            lock_key = f"ts_proxy:channel:{channel_id}:owner"

            # Use Redis SETNX for atomic locking - only succeeds if the key doesn't exist
            acquired = self.redis_client.setnx(lock_key, self.worker_id)

            # If acquired, set expiry to prevent orphaned locks
            if acquired:
                self.redis_client.expire(lock_key, ttl)
                logger.info(f"Worker {self.worker_id} acquired ownership of channel {channel_id}")
                return True

            # If not acquired, check if we already own it (might be a retry)
            current_owner = self.redis_client.get(lock_key)
            if current_owner and current_owner.decode('utf-8') == self.worker_id:
                # Refresh TTL
                self.redis_client.expire(lock_key, ttl)
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
            lock_key = f"ts_proxy:channel:{channel_id}:owner"

            # Only delete if we're the current owner to prevent race conditions
            current = self.redis_client.get(lock_key)
            if current and current.decode('utf-8') == self.worker_id:
                self.redis_client.delete(lock_key)
                logger.info(f"Released ownership of channel {channel_id}")
        except Exception as e:
            logger.error(f"Error releasing channel ownership: {e}")

    def extend_ownership(self, channel_id, ttl=30):
        """Extend ownership lease with grace period"""
        if not self.redis_client:
            return False

        try:
            lock_key = f"ts_proxy:channel:{channel_id}:owner"
            current = self.redis_client.get(lock_key)

            # Only extend if we're still the owner
            if current and current.decode('utf-8') == self.worker_id:
                self.redis_client.expire(lock_key, ttl)
                return True
            return False
        except Exception as e:
            logger.error(f"Error extending ownership: {e}")
            return False

    def initialize_channel(self, url, channel_id, user_agent=None, transcode=False):
        """Initialize a channel without redundant active key"""
        try:
            # Create buffer and client manager instances
            buffer = StreamBuffer(channel_id, redis_client=self.redis_client)
            client_manager = ClientManager(
                channel_id,
                redis_client=self.redis_client,
                worker_id=self.worker_id
            )

            # Store in local tracking
            self.stream_buffers[channel_id] = buffer
            self.client_managers[channel_id] = client_manager

            # Get channel URL from Redis if available
            channel_url = url
            channel_user_agent = user_agent

            # First check if channel metadata already exists
            existing_metadata = None
            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"

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

            # Check if channel is already owned
            current_owner = self.get_channel_owner(channel_id)

            # Exit early if another worker owns the channel
            if current_owner and current_owner != self.worker_id:
                logger.info(f"Channel {channel_id} already owned by worker {current_owner}")
                logger.info(f"This worker ({self.worker_id}) will read from Redis buffer only")

                # Create buffer but not stream manager
                buffer = StreamBuffer(channel_id=channel_id, redis_client=self.redis_client)
                self.stream_buffers[channel_id] = buffer

                # Create client manager with channel_id and redis_client
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

                # Create buffer but not stream manager
                buffer = StreamBuffer(channel_id=channel_id, redis_client=self.redis_client)
                self.stream_buffers[channel_id] = buffer

                # Create client manager with channel_id and redis_client
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
                    "state": "initializing"  # Only the owner sets this initial state
                }
                if channel_user_agent:
                    metadata["user_agent"] = channel_user_agent

                # Set channel metadata
                self.redis_client.hset(metadata_key, mapping=metadata)
                self.redis_client.expire(metadata_key, 30)  # 1 hour TTL

            # Create stream buffer
            buffer = StreamBuffer(channel_id=channel_id, redis_client=self.redis_client)
            logger.debug(f"Created StreamBuffer for channel {channel_id}")
            self.stream_buffers[channel_id] = buffer

            # Only the owner worker creates the actual stream manager
            stream_manager = StreamManager(channel_id, channel_url, buffer, user_agent=channel_user_agent, transcode=transcode)
            logger.debug(f"Created StreamManager for channel {channel_id}")
            self.stream_managers[channel_id] = stream_manager

            # Create client manager with channel_id, redis_client AND worker_id
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
                self.update_channel_state(channel_id, "connecting", {
                    "init_time": str(time.time()),
                    "owner": self.worker_id
                })

                # Set connection attempt start time
                attempt_key = f"ts_proxy:channel:{channel_id}:connection_attempt_time"
                self.redis_client.setex(attempt_key, 60, str(time.time()))

                logger.info(f"Channel {channel_id} in connecting state - will start grace period after connection")
            return True

        except Exception as e:
            logger.error(f"Error initializing channel {channel_id}: {e}", exc_info=True)
            # Release ownership on failure
            self.release_ownership(channel_id)
            return False

    def check_if_channel_exists(self, channel_id):
        """Check if a channel exists using standardized key structure"""
        # Check local memory first
        if channel_id in self.stream_managers or channel_id in self.stream_buffers:
            return True

        # Check Redis using the standard key pattern
        if self.redis_client:
            # Primary check - look for channel metadata
            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"

            # If metadata exists, return true
            if self.redis_client.exists(metadata_key):
                return True

            # Additional checks if metadata doesn't exist
            additional_keys = [
                f"ts_proxy:channel:{channel_id}:clients",
                f"ts_proxy:channel:{channel_id}:buffer:index",
                f"ts_proxy:channel:{channel_id}:owner"
            ]

            for key in additional_keys:
                if self.redis_client.exists(key):
                    return True

        return False

    def stop_channel(self, channel_id):
        """Stop a channel with proper ownership handling"""
        try:
            logger.info(f"Stopping channel {channel_id}")
            
            # First set a stopping key that clients will check
            if self.redis_client:
                stop_key = f"ts_proxy:channel:{channel_id}:stopping"
                # Set with 60 second TTL - enough time for clients to notice
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

            # Always clean up local resources
            if channel_id in self.stream_managers:
                del self.stream_managers[channel_id]
                logger.info(f"Removed stream manager for channel {channel_id}")

            if channel_id in self.stream_buffers:
                del self.stream_buffers[channel_id]
                logger.info(f"Removed stream buffer for channel {channel_id}")

            if channel_id in self.client_managers:
                del self.client_managers[channel_id]
                logger.info(f"Removed client manager for channel {channel_id}")

            # Clean up Redis keys
            self._clean_redis_keys(channel_id)

            return True
        except Exception as e:
            logger.error(f"Error stopping channel {channel_id}: {e}", exc_info=True)
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
        for collection in [self.stream_managers, self.stream_buffers,
                         self.client_managers, self.fetch_threads]:
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
                                metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
                                metadata = self.redis_client.hgetall(metadata_key)
                                if metadata and b'state' in metadata:
                                    channel_state = metadata[b'state'].decode('utf-8')

                            # Check if channel has any clients left
                            total_clients = 0
                            if channel_id in self.client_managers:
                                client_manager = self.client_managers[channel_id]
                                total_clients = client_manager.get_total_client_count()

                            # Log client count periodically
                            if time.time() % 30 < 1:  # Every ~30 seconds
                                logger.info(f"Channel {channel_id} has {total_clients} clients, state: {channel_state}")

                            # If in connecting or waiting_for_clients state, check grace period
                            if channel_state in ["connecting", "waiting_for_clients"]:
                                # Get connection ready time from metadata
                                connection_ready_time = None
                                if metadata and b'connection_ready_time' in metadata:
                                    try:
                                        connection_ready_time = float(metadata[b'connection_ready_time'].decode('utf-8'))
                                    except (ValueError, TypeError):
                                        pass

                                # If still connecting, give it more time
                                if channel_state == "connecting":
                                    logger.debug(f"Channel {channel_id} still connecting - not checking for clients yet")
                                    continue

                                # If waiting for clients, check grace period
                                if connection_ready_time:
                                    grace_period = getattr(Config, 'CHANNEL_INIT_GRACE_PERIOD', 20)
                                    time_since_ready = time.time() - connection_ready_time

                                    # Add this debug log
                                    logger.debug(f"GRACE PERIOD CHECK: Channel {channel_id} in {channel_state} state, "
                                                 f"time_since_ready={time_since_ready:.1f}s, grace_period={grace_period}s, "
                                                 f"total_clients={total_clients}")

                                    if time_since_ready <= grace_period:
                                        # Still within grace period
                                        logger.debug(f"Channel {channel_id} in grace period - {time_since_ready:.1f}s of {grace_period}s elapsed")
                                        continue
                                    elif total_clients == 0:
                                        # Grace period expired with no clients
                                        logger.info(f"Grace period expired ({time_since_ready:.1f}s > {grace_period}s) with no clients - stopping channel {channel_id}")
                                        self.stop_channel(channel_id)
                                    else:
                                        # Grace period expired but we have clients - mark channel as active
                                        logger.info(f"Grace period expired with {total_clients} clients - marking channel {channel_id} as active")
                                        old_state = "unknown"
                                        if metadata and b'state' in metadata:
                                            old_state = metadata[b'state'].decode('utf-8')
                                        if self.update_channel_state(channel_id, "active", {
                                            "grace_period_ended_at": str(time.time()),
                                            "clients_at_activation": str(total_clients)
                                        }):
                                            logger.info(f"Channel {channel_id} activated with {total_clients} clients after grace period")
                            # If active and no clients, start normal shutdown procedure
                            elif channel_state not in ["connecting", "waiting_for_clients"] and total_clients == 0:
                                # Check if there's a pending no-clients timeout
                                disconnect_key = f"ts_proxy:channel:{channel_id}:last_client_disconnect_time"
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
                                elif current_time - disconnect_time > getattr(Config, 'CHANNEL_SHUTDOWN_DELAY', 5):
                                    # We've had no clients for the shutdown delay period
                                    logger.warning(f"No clients for {current_time - disconnect_time:.1f}s, stopping channel {channel_id}")
                                    self.stop_channel(channel_id)
                                else:
                                    # Still in shutdown delay period
                                    logger.debug(f"Channel {channel_id} shutdown timer: "
                                                f"{current_time - disconnect_time:.1f}s of "
                                                f"{getattr(Config, 'CHANNEL_SHUTDOWN_DELAY', 5)}s elapsed")
                            else:
                                # There are clients or we're still connecting - clear any disconnect timestamp
                                if self.redis_client:
                                    self.redis_client.delete(f"ts_proxy:channel:{channel_id}:last_client_disconnect_time")

                        else:
                            # === NON-OWNER CHANNEL HANDLING === 
                            # For channels we don't own, check if they've been stopped/cleaned up in Redis
                            if self.redis_client:
                                # Method 1: Check for stopping key
                                stop_key = f"ts_proxy:channel:{channel_id}:stopping"
                                if self.redis_client.exists(stop_key):
                                    logger.debug(f"Non-owner cleanup: Channel {channel_id} has stopping flag in Redis, cleaning up local resources")
                                    self._cleanup_local_resources(channel_id)
                                    continue
                                
                                # Method 2: Check if owner still exists
                                owner_key = f"ts_proxy:channel:{channel_id}:owner"
                                if not self.redis_client.exists(owner_key):
                                    logger.debug(f"Non-owner cleanup: Channel {channel_id} has no owner in Redis, cleaning up local resources")
                                    self._cleanup_local_resources(channel_id)
                                    continue
                                
                                # Method 3: Check if metadata still exists
                                metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
                                if not self.redis_client.exists(metadata_key):
                                    logger.debug(f"Non-owner cleanup: Channel {channel_id} has no metadata in Redis, cleaning up local resources")
                                    self._cleanup_local_resources(channel_id)
                                    continue
                            
                            # Check for local client count - if zero, clean up our local resources
                            if self.client_managers[channel_id].get_client_count() == 0:
                                # We're not the owner, and we have no local clients - clean up our resources
                                logger.debug(f"Non-owner cleanup: Channel {channel_id} has no local clients, cleaning up local resources")
                                self._cleanup_local_resources(channel_id)

                except Exception as e:
                    logger.error(f"Error in cleanup thread: {e}", exc_info=True)

                time.sleep(getattr(Config, 'CLEANUP_CHECK_INTERVAL', 1))

        thread = threading.Thread(target=cleanup_task, daemon=True)
        thread.name = "ts-proxy-cleanup"
        thread.start()
        logger.info(f"Started TS proxy cleanup thread (interval: {getattr(Config, 'CLEANUP_CHECK_INTERVAL', 3)}s)")

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

                    # Skip channels we already have locally
                    if channel_id in self.stream_buffers:
                        continue

                    # Check if this channel has an owner
                    owner = self.get_channel_owner(channel_id)

                    if not owner:
                        # Check if there are any clients
                        client_set_key = f"ts_proxy:channel:{channel_id}:clients"
                        client_count = self.redis_client.scard(client_set_key) or 0

                        if client_count > 0:
                            # Orphaned channel with clients - we could take ownership
                            logger.info(f"Found orphaned channel {channel_id} with {client_count} clients")
                        else:
                            # Orphaned channel with no clients - clean it up
                            logger.info(f"Cleaning up orphaned channel {channel_id}")
                            self._clean_redis_keys(channel_id)
                except Exception as e:
                    logger.error(f"Error processing channel key {key}: {e}")

        except Exception as e:
            logger.error(f"Error checking orphaned channels: {e}")

    def _clean_redis_keys(self, channel_id):
        """Clean up all Redis keys for a channel more efficiently"""
        # Release the channel, stream, and profile keys from the channel
        channel = Channel.objects.get(uuid=channel_id)
        channel.release_stream()

        if not self.redis_client:
            return 0

        try:
            # Define key patterns to scan for
            patterns = [
                f"ts_proxy:channel:{channel_id}:*",  # All channel keys
                f"ts_proxy:events:{channel_id}"      # Event channel
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
        for channel_id in self.stream_managers.keys():
            # Use standard key pattern
            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"

            # Update activity timestamp in metadata only
            self.redis_client.hset(metadata_key, "last_active", str(time.time()))
            self.redis_client.expire(metadata_key, 30)  # Reset TTL on metadata hash
            logger.debug(f"Refreshed metadata TTL for channel {channel_id}")
    def update_channel_state(self, channel_id, new_state, additional_fields=None):
        """Update channel state with proper history tracking and logging"""
        if not self.redis_client:
            return False

        try:
            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"

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
            logger.info(f"Channel {channel_id} state transition: {current_state or 'None'} → {new_state}")
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
