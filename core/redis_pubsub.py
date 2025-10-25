"""
Redis PubSub utilities for maintaining long-lived connections.
"""
import threading
import time
import logging
import json
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError

logger = logging.getLogger(__name__)

class DummyPubSub:
    """Dummy PubSub implementation when Redis isn't available"""
    def __init__(self):
        pass

    def subscribe(self, *args, **kwargs):
        pass

    def psubscribe(self, *args, **kwargs):
        pass

    def get_message(self, *args, **kwargs):
        return None

    def close(self):
        pass

class RedisPubSubManager:
    """
    A robust Redis PubSub manager that handles disconnections and reconnections.
    """

    def __init__(self, redis_client=None, auto_reconnect=True):
        """
        Initialize the PubSub manager.

        Args:
            redis_client: An existing Redis client to use
            auto_reconnect: Whether to automatically reconnect on failure
        """
        self.redis_client = redis_client
        self.pubsub = None
        self.subscriptions = set()
        self.pattern_subscriptions = set()
        self.auto_reconnect = auto_reconnect
        self.running = True
        self.lock = threading.RLock()
        self.message_handlers = {}  # Map of channels to handler functions
        self.message_thread = None
        self.is_dummy = redis_client is None

    def subscribe(self, channel, handler=None):
        """
        Subscribe to a channel.

        Args:
            channel: The channel to subscribe to
            handler: Optional function to call when messages are received
        """
        if self.is_dummy:
            return

        with self.lock:
            self.subscriptions.add(channel)
            if handler:
                self.message_handlers[channel] = handler

            if self.pubsub:
                self.pubsub.subscribe(channel)
                logger.info(f"Subscribed to channel: {channel}")

    def psubscribe(self, pattern, handler=None):
        """
        Subscribe to a channel pattern.

        Args:
            pattern: The pattern to subscribe to
            handler: Optional function to call when messages are received
        """
        if self.is_dummy:
            return

        with self.lock:
            self.pattern_subscriptions.add(pattern)
            if handler:
                self.message_handlers[pattern] = handler

            if self.pubsub:
                self.pubsub.psubscribe(pattern)
                logger.info(f"Subscribed to pattern: {pattern}")

    def publish(self, channel, message):
        """
        Publish a message to a channel.

        Args:
            channel: The channel to publish to
            message: The message to publish (will be JSON-encoded if not a string)

        Returns:
            Number of clients that received the message
        """
        if self.is_dummy:
            return 0

        try:
            if not isinstance(message, str):
                message = json.dumps(message)
            return self.redis_client.publish(channel, message)
        except Exception as e:
            logger.error(f"Error publishing to {channel}: {e}")
            return 0

    def start_listening(self):
        """
        Start listening for messages in a background thread.
        """
        if self.is_dummy:
            logger.debug("Running with dummy Redis client - not starting listener")
            return

        if not self.message_thread:
            self._connect()
            self.message_thread = threading.Thread(
                target=self._listen_for_messages,
                daemon=True,
                name="redis-pubsub-listener"
            )
            self.message_thread.start()
            logger.info("Started Redis PubSub listener thread")

    def stop(self):
        """
        Stop listening and clean up resources.
        """
        if self.is_dummy:
            return

        self.running = False
        if self.pubsub:
            try:
                self.pubsub.close()
            except:
                pass
        self.pubsub = None

    def _connect(self):
        """
        Establish a new PubSub connection and subscribe to all channels.
        """
        if self.is_dummy:
            self.pubsub = DummyPubSub()
            return

        with self.lock:
            # Close any existing connection
            if self.pubsub:
                try:
                    self.pubsub.close()
                except:
                    pass

            # Create a new PubSub instance - critical: no timeout for subscribe operations
            # This prevents the connection from timing out while waiting for messages
            self.pubsub = self.redis_client.pubsub()

            # Resubscribe to all channels
            if self.subscriptions:
                self.pubsub.subscribe(*self.subscriptions)
                logger.info(f"Resubscribed to channels: {self.subscriptions}")

            # Resubscribe to all patterns
            if self.pattern_subscriptions:
                self.pubsub.psubscribe(*self.pattern_subscriptions)
                logger.info(f"Resubscribed to patterns: {self.pattern_subscriptions}")

    def _listen_for_messages(self):
        """
        Background thread that listens for messages and handles reconnections.
        """
        if self.is_dummy:
            return

        consecutive_errors = 0

        while self.running:
            try:
                # Check if we need to connect
                if not self.pubsub:
                    self._connect()

                # Listen for messages with NO timeout - this is critical!
                message = self.pubsub.get_message(timeout=None)

                if message:
                    # Don't process subscription confirmation messages
                    if message['type'] in ('subscribe', 'psubscribe'):
                        continue

                    channel = message.get('channel')
                    if channel:
                        # Find and call the appropriate handler
                        handler = self.message_handlers.get(channel)
                        if handler:
                            try:
                                handler(message)
                            except Exception as e:
                                logger.error(f"Error in message handler for {channel}: {e}")

                # Reset error counter on success
                consecutive_errors = 0

                # Small sleep to prevent excessive CPU usage
                time.sleep(0.01)

            except (ConnectionError, TimeoutError) as e:
                consecutive_errors += 1

                if not self.auto_reconnect:
                    logger.error(f"PubSub connection error and auto_reconnect is disabled: {e}")
                    break

                # Exponential backoff for reconnection attempts
                backoff = min(consecutive_errors * 0.5, 5)
                logger.warning(f"PubSub connection error, reconnecting in {backoff} seconds: {e}")
                time.sleep(backoff)

                # Reconnect
                self._connect()

            except Exception as e:
                logger.error(f"Unexpected error in PubSub listener: {e}")
                time.sleep(1)  # Prevent tight loop in case of persistent errors

        logger.info("PubSub listener thread stopping")

# Create a singleton instance
pubsub_manager = None

def get_pubsub_manager(redis_client=None):
    """
    Get or create the PubSub manager singleton.

    Args:
        redis_client: Optional Redis client to use

    Returns:
        The PubSub manager instance
    """
    global pubsub_manager

    if pubsub_manager is None:
        pubsub_manager = RedisPubSubManager(redis_client)
        # Only start if redis_client is not None
        if redis_client is not None:
            try:
                pubsub_manager.start_listening()
            except Exception as e:
                logger.error(f"Failed to start PubSub listener: {e}")

    return pubsub_manager
