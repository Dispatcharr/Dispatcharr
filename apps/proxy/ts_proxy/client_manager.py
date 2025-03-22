"""Client connection management for TS streams"""

import threading
import logging
import time
import json
from typing import Set, Optional
from apps.proxy.config import TSConfig as Config
from redis.exceptions import ConnectionError, TimeoutError
from .constants import EventType
from .config_helper import ConfigHelper
from .redis_keys import RedisKeys
from .utils import get_logger

logger = get_logger()

class ClientManager:
    """Manages client connections with no duplicates"""

    def __init__(self, channel_id=None, redis_client=None, heartbeat_interval=1, worker_id=None):
        self.channel_id = channel_id
        self.redis_client = redis_client
        self.clients = set()
        self.lock = threading.Lock()
        self.last_active_time = time.time()
        self.worker_id = worker_id  # Store worker ID as instance variable

        # STANDARDIZED KEYS: Move client set under channel namespace
        self.client_set_key = RedisKeys.clients(channel_id)
        self.client_ttl = ConfigHelper.get('CLIENT_RECORD_TTL', 60)
        self.heartbeat_interval = ConfigHelper.get('CLIENT_HEARTBEAT_INTERVAL', 10)
        self.last_heartbeat_time = {}

        # Start heartbeat thread for local clients
        self._start_heartbeat_thread()
        self._registered_clients = set()  # Track already registered client IDs

    def _start_heartbeat_thread(self):
        """Start thread to regularly refresh client presence in Redis"""
        def heartbeat_task():
            while True:
                try:
                    # Wait for the interval
                    time.sleep(self.heartbeat_interval)

                    # Send heartbeat for all local clients
                    with self.lock:
                        if not self.clients or not self.redis_client:
                            continue

                        # IMPROVED GHOST DETECTION: Check for stale clients before sending heartbeats
                        current_time = time.time()
                        clients_to_remove = set()

                        # First identify clients that should be removed
                        for client_id in self.clients:
                            client_key = f"ts_proxy:channel:{self.channel_id}:clients:{client_id}"

                            # Check if client exists in Redis at all
                            exists = self.redis_client.exists(client_key)
                            if not exists:
                                logger.debug(f"Client {client_id} no longer exists in Redis, removing locally")
                                clients_to_remove.add(client_id)
                                continue

                            # Check for stale activity using last_active field
                            last_active = self.redis_client.hget(client_key, "last_active")
                            if last_active:
                                last_active_time = float(last_active.decode('utf-8'))
                                ghost_timeout = self.heartbeat_interval * getattr(Config, 'GHOST_CLIENT_MULTIPLIER', 5.0)

                                if current_time - last_active_time > ghost_timeout:
                                    logger.debug(f"Client {client_id} inactive for {current_time - last_active_time:.1f}s, removing as ghost")
                                    clients_to_remove.add(client_id)

                        # Remove ghost clients in a separate step
                        for client_id in clients_to_remove:
                            self.remove_client(client_id)

                        if clients_to_remove:
                            logger.info(f"Removed {len(clients_to_remove)} ghost clients from channel {self.channel_id}")

                        # Now send heartbeats only for remaining clients
                        pipe = self.redis_client.pipeline()
                        current_time = time.time()

                        for client_id in self.clients:
                            # Skip clients we just marked for removal
                            if client_id in clients_to_remove:
                                continue

                            # Skip if we just sent a heartbeat recently
                            if client_id in self.last_heartbeat_time:
                                time_since_heartbeat = current_time - self.last_heartbeat_time[client_id]
                                if time_since_heartbeat < self.heartbeat_interval * 0.5:  # Only heartbeat at half interval minimum
                                    continue

                            # Only update clients that remain
                            client_key = f"ts_proxy:channel:{self.channel_id}:clients:{client_id}"
                            pipe.hset(client_key, "last_active", str(current_time))
                            pipe.expire(client_key, self.client_ttl)

                            # Keep client in the set with TTL
                            pipe.sadd(self.client_set_key, client_id)
                            pipe.expire(self.client_set_key, self.client_ttl)

                            # Track last heartbeat locally
                            self.last_heartbeat_time[client_id] = current_time

                        # Execute all commands atomically
                        pipe.execute()

                        # Only notify if we have real clients
                        if self.clients and not all(c in clients_to_remove for c in self.clients):
                            self._notify_owner_of_activity()

                except Exception as e:
                    logger.error(f"Error in client heartbeat thread: {e}")

        thread = threading.Thread(target=heartbeat_task, daemon=True)
        thread.name = f"client-heartbeat-{self.channel_id}"
        thread.start()
        logger.debug(f"Started client heartbeat thread for channel {self.channel_id} (interval: {self.heartbeat_interval}s)")

    def _execute_redis_command(self, command_func):
        """Execute Redis command with error handling"""
        if not self.redis_client:
            return None

        try:
            return command_func()
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis connection error in ClientManager: {e}")
            return None
        except Exception as e:
            logger.error(f"Redis command error in ClientManager: {e}")
            return None

    def _notify_owner_of_activity(self):
        """Notify channel owner that clients are active on this worker"""
        if not self.redis_client or not self.clients:
            return

        try:
            worker_id = self.worker_id or "unknown"

            # STANDARDIZED KEY: Worker info under channel namespace
            worker_key = f"ts_proxy:channel:{self.channel_id}:worker:{worker_id}"
            self._execute_redis_command(
                lambda: self.redis_client.setex(worker_key, self.client_ttl, str(len(self.clients)))
            )

            # STANDARDIZED KEY: Activity timestamp under channel namespace
            activity_key = f"ts_proxy:channel:{self.channel_id}:activity"
            self._execute_redis_command(
                lambda: self.redis_client.setex(activity_key, self.client_ttl, str(time.time()))
            )
        except Exception as e:
            logger.error(f"Error notifying owner of client activity: {e}")

    def add_client(self, client_id, client_ip, user_agent=None):
        """Add a client with duplicate prevention"""
        if client_id in self._registered_clients:
            logger.debug(f"Client {client_id} already registered, skipping")
            return False

        self._registered_clients.add(client_id)

        # Use a function to get the client key
        client_key = f"ts_proxy:channel:{self.channel_id}:clients:{client_id}"

        # Prepare client data
        current_time = str(time.time())
        client_data = {
            "user_agent": user_agent or "unknown",
            "ip_address": client_ip,
            "connected_at": current_time,
            "last_active": current_time,
            "worker_id": self.worker_id or "unknown"
        }

        try:
            with self.lock:
                # Store client in local set
                self.clients.add(client_id)

                # Store in Redis
                if self.redis_client:
                    # FIXED: Store client data just once with proper key
                    self.redis_client.hset(client_key, mapping=client_data)
                    self.redis_client.expire(client_key, self.client_ttl)

                    # Add to the client set
                    self.redis_client.sadd(self.client_set_key, client_id)
                    self.redis_client.expire(self.client_set_key, self.client_ttl)

                    # Clear any initialization timer
                    init_key = f"ts_proxy:channel:{self.channel_id}:init_time"
                    self.redis_client.delete(init_key)

                    self._notify_owner_of_activity()

                    # Publish client connected event with user agent
                    event_data = {
                        "event": EventType.CLIENT_CONNECTED,  # Use constant instead of string
                        "channel_id": self.channel_id,
                        "client_id": client_id,
                        "worker_id": self.worker_id or "unknown",
                        "timestamp": time.time()
                    }

                    if user_agent:
                        event_data["user_agent"] = user_agent
                        logger.debug(f"Storing user agent '{user_agent}' for client {client_id}")
                    else:
                        logger.debug(f"No user agent provided for client {client_id}")

                    self.redis_client.publish(
                        RedisKeys.events_channel(self.channel_id),  # Use RedisKeys instead of string
                        json.dumps(event_data)
                    )

                # Get total clients across all workers
                total_clients = self.get_total_client_count()
                logger.info(f"New client connected: {client_id} (local: {len(self.clients)}, total: {total_clients})")

                self.last_heartbeat_time[client_id] = time.time()

                return len(self.clients)

        except Exception as e:
            logger.error(f"Error adding client {client_id}: {e}")
            return False

    def remove_client(self, client_id):
        """Remove a client from this channel and Redis"""
        with self.lock:
            if client_id in self.clients:
                self.clients.remove(client_id)

            if client_id in self.last_heartbeat_time:
                del self.last_heartbeat_time[client_id]

            self.last_active_time = time.time()

            if self.redis_client:
                # Remove from channel's client set
                self.redis_client.srem(self.client_set_key, client_id)

                # STANDARDIZED KEY: Delete individual client keys
                client_key = f"ts_proxy:channel:{self.channel_id}:clients:{client_id}"
                self.redis_client.delete(client_key)

                # Check if this was the last client
                remaining = self.redis_client.scard(self.client_set_key) or 0
                if remaining == 0:
                    logger.warning(f"Last client removed: {client_id} - channel may shut down soon")

                    # Trigger disconnect time tracking even if we're not the owner
                    disconnect_key = RedisKeys.last_client_disconnect(self.channel_id)
                    self.redis_client.setex(disconnect_key, 60, str(time.time()))

                self._notify_owner_of_activity()

                # Publish client disconnected event
                event_data = json.dumps({
                    "event": EventType.CLIENT_DISCONNECTED,  # Use constant instead of string
                    "channel_id": self.channel_id,
                    "client_id": client_id,
                    "worker_id": self.worker_id or "unknown",
                    "timestamp": time.time(),
                    "remaining_clients": remaining
                })
                self.redis_client.publish(RedisKeys.events_channel(self.channel_id), event_data)

            total_clients = self.get_total_client_count()
            logger.info(f"Client disconnected: {client_id} (local: {len(self.clients)}, total: {total_clients})")

        return len(self.clients)

    def get_client_count(self):
        """Get local client count"""
        with self.lock:
            return len(self.clients)

    def get_total_client_count(self):
        """Get total client count across all workers"""
        if not self.redis_client:
            return len(self.clients)

        try:
            # Count members in the client set
            return self.redis_client.scard(self.client_set_key) or 0
        except Exception as e:
            logger.error(f"Error getting total client count: {e}")
            return len(self.clients)  # Fall back to local count

    def refresh_client_ttl(self):
        """Refresh TTL for active clients to prevent expiration"""
        if not self.redis_client:
            return

        try:
            # Refresh TTL for all clients belonging to this worker
            for client_id in self.clients:
                # STANDARDIZED: Use channel namespace for client keys
                client_key = f"ts_proxy:channel:{self.channel_id}:clients:{client_id}"
                self.redis_client.expire(client_key, self.client_ttl)

            # Refresh TTL on the set itself
            self.redis_client.expire(self.client_set_key, self.client_ttl)
        except Exception as e:
            logger.error(f"Error refreshing client TTL: {e}")
