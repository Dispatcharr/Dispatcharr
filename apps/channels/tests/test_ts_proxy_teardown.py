"""Tests for multi-worker channel teardown coordination."""
import time
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer
from apps.proxy.live_proxy.services.channel_service import ChannelService


CHANNEL_ID = "00000000-0000-0000-0000-000000000099"


def _mock_proxy_server(redis_client=None):
    server = MagicMock()
    server.redis_client = redis_client or MagicMock()
    return server


class ChannelTeardownAvailabilityTests(TestCase):
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_teardown_active_when_stopping_key_exists(self, mock_get_instance):
        redis = MagicMock()
        redis.exists.side_effect = lambda key: key == RedisKeys.channel_stopping(CHANNEL_ID)
        mock_get_instance.return_value = _mock_proxy_server(redis)

        self.assertTrue(ChannelService.is_channel_teardown_active(CHANNEL_ID))

    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_teardown_active_when_metadata_state_is_stopping(self, mock_get_instance):
        redis = MagicMock()
        redis.exists.return_value = False
        redis.hget.return_value = ChannelState.STOPPING.encode()
        mock_get_instance.return_value = _mock_proxy_server(redis)

        self.assertTrue(ChannelService.is_channel_teardown_active(CHANNEL_ID))

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.channel_shutdown_delay")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_shutdown_pending_within_delay_window(self, mock_get_instance, mock_delay):
        mock_delay.return_value = 5
        redis = MagicMock()
        redis.exists.return_value = False
        redis.get.return_value = str(time.time() - 2).encode()
        mock_get_instance.return_value = _mock_proxy_server(redis)

        self.assertTrue(ChannelService.is_shutdown_pending(CHANNEL_ID))
        self.assertTrue(ChannelService.is_channel_unavailable_for_new_clients(CHANNEL_ID))

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.channel_shutdown_delay")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_shutdown_pending_expired_after_delay(self, mock_get_instance, mock_delay):
        mock_delay.return_value = 5
        redis = MagicMock()
        redis.exists.return_value = False
        redis.get.return_value = str(time.time() - 10).encode()
        mock_get_instance.return_value = _mock_proxy_server(redis)

        self.assertFalse(ChannelService.is_shutdown_pending(CHANNEL_ID))


class LocalStreamActivityTests(TestCase):
    def _make_server(self):
        with patch("apps.proxy.live_proxy.server.RedisClient.get_client", return_value=MagicMock()):
            server = ProxyServer()
        server.worker_id = "testhost:1"
        server.stream_managers = {}
        server.stream_buffers = {}
        server.client_managers = {}
        server.profile_managers = {}
        server.profile_buffers = {}
        server._live_stream_managers = {}
        server._stopping_channels = set()
        server.redis_client = MagicMock()
        server.stop_all_output_formats = MagicMock()
        server.stop_all_output_profiles = MagicMock()
        return server

    def test_has_local_stream_activity_from_live_registry(self):
        server = self._make_server()
        server._live_stream_managers[CHANNEL_ID] = MagicMock()
        self.assertTrue(server._has_local_stream_activity(CHANNEL_ID))

    @patch.object(ProxyServer, "_join_stream_thread")
    def test_stop_local_stream_activity_stops_live_manager(self, mock_join):
        server = self._make_server()
        manager = MagicMock()
        server._live_stream_managers[CHANNEL_ID] = manager

        server._stop_local_stream_activity(CHANNEL_ID)

        manager.stop.assert_called_once()
        mock_join.assert_called_once_with(CHANNEL_ID)
        self.assertNotIn(CHANNEL_ID, server._live_stream_managers)


class OrphanMetadataCleanupTests(TestCase):
    def _make_server(self):
        with patch("apps.proxy.live_proxy.server.RedisClient.get_client", return_value=MagicMock()):
            server = ProxyServer()
        server.worker_id = "testhost:1"
        server.stream_managers = {}
        server.stream_buffers = {}
        server.client_managers = {}
        server.profile_managers = {}
        server.profile_buffers = {}
        server._live_stream_managers = {}
        server._stopping_channels = set()
        server.redis_client = MagicMock()
        return server

    @patch.object(ProxyServer, "_clean_redis_keys")
    @patch.object(ProxyServer, "_stop_local_stream_activity")
    @patch.object(ProxyServer, "_has_local_stream_activity", return_value=True)
    def test_orphan_metadata_stops_local_processes_before_redis(
        self, mock_has_local, mock_stop_local, mock_clean_redis
    ):
        server = self._make_server()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        server.redis_client.keys.return_value = [metadata_key.encode()]
        server.redis_client.hgetall.return_value = {
            b"owner": b"",
            b"state": b"unknown",
        }
        server.redis_client.exists.return_value = False
        server.redis_client.scard.return_value = 0

        server._check_orphaned_metadata()

        mock_has_local.assert_called_with(CHANNEL_ID)
        mock_stop_local.assert_called_once_with(CHANNEL_ID)
        mock_clean_redis.assert_called_once_with(CHANNEL_ID)

    @patch.object(ProxyServer, "_clean_redis_keys")
    @patch.object(ProxyServer, "_stop_local_stream_activity")
    @patch.object(ProxyServer, "_has_local_stream_activity", return_value=False)
    def test_orphan_metadata_remote_channel_only_cleans_redis(
        self, mock_has_local, mock_stop_local, mock_clean_redis
    ):
        server = self._make_server()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        server.redis_client.keys.return_value = [metadata_key.encode()]
        server.redis_client.hgetall.return_value = {b"owner": b"", b"state": b"unknown"}
        server.redis_client.exists.return_value = False
        server.redis_client.scard.return_value = 0

        server._check_orphaned_metadata()

        mock_stop_local.assert_not_called()
        mock_clean_redis.assert_called_once_with(CHANNEL_ID)


class OrphanChannelCleanupTests(TestCase):
    def _make_server(self):
        with patch("apps.proxy.live_proxy.server.RedisClient.get_client", return_value=MagicMock()):
            server = ProxyServer()
        server.worker_id = "testhost:1"
        server.stream_managers = {}
        server.stream_buffers = {}
        server.client_managers = {}
        server.profile_managers = {}
        server.profile_buffers = {}
        server._live_stream_managers = {}
        server._stopping_channels = set()
        server.redis_client = MagicMock()
        server.get_channel_owner = MagicMock(return_value=None)
        return server

    @patch.object(ProxyServer, "_clean_redis_keys")
    @patch.object(ProxyServer, "_stop_local_stream_activity")
    @patch.object(ProxyServer, "_has_local_stream_activity", return_value=True)
    def test_orphan_channel_stops_local_before_redis(
        self, mock_has_local, mock_stop_local, mock_clean_redis
    ):
        server = self._make_server()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        server.redis_client.keys.return_value = [metadata_key.encode()]
        server.redis_client.scard.return_value = 0

        server._check_orphaned_channels()

        mock_stop_local.assert_called_once_with(CHANNEL_ID)
        mock_clean_redis.assert_called_once_with(CHANNEL_ID)


class StreamManagerOwnershipTests(TestCase):
    def test_still_owner_false_when_different_worker(self):
        buffer = MagicMock()
        buffer.redis_client.get.side_effect = lambda key: (
            None if "stopping" in key else b"worker-b"
        )
        buffer.redis_client.exists.return_value = False
        manager = StreamManager(
            CHANNEL_ID, "http://example/stream", buffer, worker_id="worker-a"
        )

        self.assertFalse(manager._still_owner())

    def test_still_owner_true_when_owner_lock_expired_but_not_stopping(self):
        buffer = MagicMock()
        buffer.redis_client.get.return_value = None
        buffer.redis_client.exists.return_value = False
        manager = StreamManager(
            CHANNEL_ID, "http://example/stream", buffer, worker_id="worker-a"
        )

        self.assertTrue(manager._still_owner())

    def test_still_owner_false_when_channel_stopping_key_set(self):
        buffer = MagicMock()
        buffer.redis_client.exists.return_value = True
        manager = StreamManager(
            CHANNEL_ID, "http://example/stream", buffer, worker_id="worker-a"
        )

        self.assertFalse(manager._still_owner())

    def test_update_bytes_skipped_after_ownership_lost(self):
        buffer = MagicMock()
        buffer.redis_client.get.return_value = b"other-worker"
        buffer.redis_client.exists.return_value = False
        manager = StreamManager(
            CHANNEL_ID, "http://example/stream", buffer, worker_id="worker-a"
        )
        manager.bytes_processed = 1000

        manager._update_bytes_processed(500)

        buffer.redis_client.hincrby.assert_not_called()
