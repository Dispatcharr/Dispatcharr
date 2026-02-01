"""
Tests for the plugin event system.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.plugins.models import PluginConfig
from apps.plugins.tasks import dispatch_event


class PluginEventSubscriptionTests(TestCase):
    """Tests for plugin event subscription and emission."""

    def setUp(self):
        # Create a test plugin config
        self.plugin_config = PluginConfig.objects.create(
            key="test_plugin",
            name="Test Plugin",
            version="1.0.0",
            enabled=True,
        )

    @patch("core.redis_pubsub.get_pubsub_manager")
    def test_subscribe_and_emit_round_trip(self, mock_get_pubsub):
        """Test that subscribing to an event and emitting it dispatches the task."""
        # Create a mock pubsub manager with a real Redis client mock
        mock_pubsub = MagicMock()
        mock_pubsub.is_dummy = False
        mock_redis = MagicMock()
        mock_pubsub.redis_client = mock_redis

        # Set up the mock to track subscriptions
        subscriptions = {}

        def mock_sadd(key, value):
            if key not in subscriptions:
                subscriptions[key] = set()
            subscriptions[key].add(value.encode() if isinstance(value, str) else value)

        def mock_smembers(key):
            return subscriptions.get(key, set())

        mock_redis.sadd = mock_sadd
        mock_redis.smembers = mock_smembers
        mock_get_pubsub.return_value = mock_pubsub

        # Import and use the real methods
        from core.redis_pubsub import RedisPubSubManager

        # Create a real manager with the mock redis client
        manager = RedisPubSubManager(redis_client=mock_redis)

        # Subscribe a plugin to an event
        manager.subscribe("test.event", "test_plugin", "on_test_event")

        # Verify subscription was stored
        self.assertIn(b"test_plugin:on_test_event", subscriptions.get("events:test.event", set()))

        # Emit the event and verify task would be dispatched
        with patch("apps.plugins.tasks.dispatch_event.delay") as mock_delay:
            manager.emit("test.event", {"foo": "bar"})
            mock_delay.assert_called_once_with(
                "test_plugin", "on_test_event", "test.event", {"foo": "bar"}
            )

    @patch("apps.plugins.loader.PluginManager.get")
    def test_disabled_plugin_handler_not_called(self, mock_pm_get):
        """Test that disabled plugin handlers are skipped."""
        # Disable the plugin
        self.plugin_config.enabled = False
        self.plugin_config.save()

        # Create mock plugin with handler
        mock_plugin = MagicMock()
        mock_handler = MagicMock()
        mock_plugin.instance.on_test_event = mock_handler
        mock_pm_get.return_value.get_plugin.return_value = mock_plugin

        # Dispatch the event - should skip because plugin is disabled
        dispatch_event("test_plugin", "on_test_event", "test.event", {"foo": "bar"})

        # Handler should NOT have been called
        mock_handler.assert_not_called()

    @patch("apps.plugins.loader.PluginManager.get")
    def test_handler_exception_triggers_retry(self, mock_pm_get):
        """Test that handler exceptions are re-raised for Celery retry."""
        # Create mock plugin with handler that raises
        mock_plugin = MagicMock()
        mock_handler = MagicMock(side_effect=ValueError("Handler failed"))
        mock_plugin.instance.on_test_event = mock_handler
        mock_pm_get.return_value.get_plugin.return_value = mock_plugin

        # Dispatch the event - should raise for Celery retry
        with self.assertRaises(ValueError) as ctx:
            dispatch_event("test_plugin", "on_test_event", "test.event", {"foo": "bar"})

        self.assertEqual(str(ctx.exception), "Handler failed")
        mock_handler.assert_called_once_with("test.event", {"foo": "bar"})

    @patch("apps.plugins.loader.PluginManager.get")
    def test_missing_plugin_logs_warning(self, mock_pm_get):
        """Test that missing plugin is handled gracefully."""
        mock_pm_get.return_value.get_plugin.return_value = None

        # Should not raise, just log and return
        result = dispatch_event("nonexistent_plugin", "handler", "test.event", {})
        self.assertIsNone(result)

    @patch("apps.plugins.loader.PluginManager.get")
    def test_missing_handler_logs_warning(self, mock_pm_get):
        """Test that missing handler is handled gracefully."""
        mock_plugin = MagicMock()
        mock_plugin.instance = MagicMock(spec=[])  # No handlers
        mock_pm_get.return_value.get_plugin.return_value = mock_plugin

        # Should not raise, just log and return
        result = dispatch_event("test_plugin", "nonexistent_handler", "test.event", {})
        self.assertIsNone(result)


class PluginUnsubscribeTests(TestCase):
    """Tests for plugin unsubscription."""

    @patch("core.redis_pubsub.get_pubsub_manager")
    def test_unsubscribe_removes_all_plugin_subscriptions(self, mock_get_pubsub):
        """Test that unsubscribing removes all subscriptions for a plugin."""
        mock_redis = MagicMock()

        # Set up mock subscriptions
        subscriptions = {
            b"events:event1": {b"test_plugin:handler1", b"other_plugin:handler"},
            b"events:event2": {b"test_plugin:handler2"},
        }

        def mock_scan_iter(pattern):
            return [k for k in subscriptions.keys() if pattern.replace("*", "") in k.decode()]

        def mock_smembers(key):
            # Return a copy to avoid "set changed size during iteration" error
            return set(subscriptions.get(key if isinstance(key, bytes) else key.encode(), set()))

        def mock_srem(key, member):
            key_bytes = key if isinstance(key, bytes) else key.encode()
            if key_bytes in subscriptions:
                subscriptions[key_bytes].discard(member)

        mock_redis.scan_iter = mock_scan_iter
        mock_redis.smembers = mock_smembers
        mock_redis.srem = mock_srem

        from core.redis_pubsub import RedisPubSubManager

        manager = RedisPubSubManager(redis_client=mock_redis)
        manager.unsubscribe("test_plugin")

        # Verify test_plugin subscriptions were removed
        self.assertNotIn(b"test_plugin:handler1", subscriptions[b"events:event1"])
        self.assertNotIn(b"test_plugin:handler2", subscriptions[b"events:event2"])
        # Other plugin should still be there
        self.assertIn(b"other_plugin:handler", subscriptions[b"events:event1"])
