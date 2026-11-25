"""Tests for ts_proxy keepalive and stats-update behavior.

Covers:
  - stream_generator._should_send_keepalive() owner vs non-owner worker paths
  - stream_generator._should_send_keepalive() Redis last_data health check
  - client_manager._do_stats_update() error handling and WebSocket dispatch
  - client_manager.remove_client() non-blocking stats update
  - Keepalive/DVR-timeout timing invariants
"""
import threading
import time
from unittest.mock import MagicMock, patch

from django.test import TestCase


# ---------------------------------------------------------------------------
# _should_send_keepalive: owner worker path
# ---------------------------------------------------------------------------

class OwnerWorkerKeepaliveTests(TestCase):
    """Owner worker has a stream_manager; keepalive logic uses it directly."""

    def _make_generator(self, healthy, at_buffer_head, consecutive_empty):
        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator
        gen = StreamGenerator.__new__(StreamGenerator)
        gen.channel_id = "00000000-0000-0000-0000-000000000001"
        gen.client_id = "test-client"

        buffer = MagicMock()
        buffer.index = 10 if at_buffer_head else 100
        gen.local_index = 10
        gen.buffer = buffer

        stream_manager = MagicMock()
        stream_manager.healthy = healthy
        gen.stream_manager = stream_manager

        gen.consecutive_empty = consecutive_empty
        return gen

    def test_owner_healthy_returns_false(self):
        """Owner worker, healthy stream -> no keepalive."""
        gen = self._make_generator(healthy=True, at_buffer_head=True, consecutive_empty=10)
        self.assertFalse(gen._should_send_keepalive(gen.local_index))

    def test_owner_unhealthy_at_head_returns_true(self):
        """Owner worker, unhealthy stream, at buffer head -> send keepalive."""
        gen = self._make_generator(healthy=False, at_buffer_head=True, consecutive_empty=10)
        self.assertTrue(gen._should_send_keepalive(gen.local_index))

    def test_owner_unhealthy_not_at_head_returns_false(self):
        """Owner worker, unhealthy stream, but NOT at buffer head -> no keepalive."""
        gen = self._make_generator(healthy=False, at_buffer_head=False, consecutive_empty=10)
        self.assertFalse(gen._should_send_keepalive(gen.local_index))

    def test_owner_insufficient_consecutive_empty_returns_false(self):
        """Owner worker, unhealthy, at head but consecutive_empty < 5 -> no keepalive."""
        gen = self._make_generator(healthy=False, at_buffer_head=True, consecutive_empty=3)
        self.assertFalse(gen._should_send_keepalive(gen.local_index))

    def test_owner_exactly_5_consecutive_empty_returns_true(self):
        """consecutive_empty == 5 is the minimum threshold."""
        gen = self._make_generator(healthy=False, at_buffer_head=True, consecutive_empty=5)
        self.assertTrue(gen._should_send_keepalive(gen.local_index))


# ---------------------------------------------------------------------------
# _should_send_keepalive: non-owner worker path
# ---------------------------------------------------------------------------

class NonOwnerWorkerKeepaliveTests(TestCase):
    """Non-owner worker has stream_manager=None; health determined from Redis."""

    def _make_generator(self, consecutive_empty=10):
        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator
        gen = StreamGenerator.__new__(StreamGenerator)
        gen.channel_id = "00000000-0000-0000-0000-000000000002"
        gen.client_id = "test-client-nonowner"

        buffer = MagicMock()
        buffer.index = 10
        gen.local_index = 10
        gen.buffer = buffer

        gen.stream_manager = None  # non-owner worker
        gen.consecutive_empty = consecutive_empty

        # Attributes added by health-check throttling (set in __init__)
        gen._last_health_check_time = 0.0
        gen._last_health_check_result = False
        gen._health_check_interval = 2.0
        gen.proxy_server = None

        return gen

    def _mock_proxy_server(self, last_data_value):
        """Return a mock ProxyServer with a redis_client pre-configured."""
        server = MagicMock()
        redis_client = MagicMock()
        server.redis_client = redis_client
        redis_client.get.return_value = last_data_value
        return server

    def test_non_owner_fresh_data_returns_false(self):
        """Non-owner, last_data < 10s ago -> stream healthy -> no keepalive."""
        gen = self._make_generator()
        fresh_ts = str(time.time() - 2.0).encode()
        server = self._mock_proxy_server(fresh_ts)

        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
            MockPS.get_instance.return_value = server
            result = gen._should_send_keepalive(gen.local_index)

        self.assertFalse(result, "Fresh data should NOT trigger keepalive")

    def test_non_owner_stale_data_returns_true(self):
        """Non-owner, last_data >= 10s ago -> stream unhealthy -> send keepalive."""
        gen = self._make_generator()
        stale_ts = str(time.time() - 12.0).encode()
        server = self._mock_proxy_server(stale_ts)

        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
            MockPS.get_instance.return_value = server
            result = gen._should_send_keepalive(gen.local_index)

        self.assertTrue(result, "Stale data (12s) should trigger keepalive")

    def test_non_owner_exactly_at_timeout_returns_true(self):
        """Data age exactly equal to CONNECTION_TIMEOUT (10s) -> send keepalive."""
        gen = self._make_generator()
        ts = str(time.time() - 10.0).encode()
        server = self._mock_proxy_server(ts)

        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
            MockPS.get_instance.return_value = server
            result = gen._should_send_keepalive(gen.local_index)

        self.assertTrue(result, "Data at exactly timeout threshold should trigger keepalive")

    def test_non_owner_no_redis_key_returns_true(self):
        """Non-owner, last_data key missing from Redis -> assume unhealthy."""
        gen = self._make_generator()
        server = self._mock_proxy_server(None)

        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
            MockPS.get_instance.return_value = server
            result = gen._should_send_keepalive(gen.local_index)

        self.assertTrue(result, "Missing last_data key should trigger keepalive")

    def test_non_owner_redis_client_none_returns_false(self):
        """Non-owner, redis_client is None (disconnected) -> conservative, no keepalive."""
        gen = self._make_generator()
        server = MagicMock()
        server.redis_client = None

        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
            MockPS.get_instance.return_value = server
            result = gen._should_send_keepalive(gen.local_index)

        self.assertFalse(result, "No redis_client -> conservative, no keepalive")

    def test_non_owner_redis_exception_returns_false(self):
        """Non-owner, Redis raises an exception -> conservative, no keepalive."""
        gen = self._make_generator()

        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
            MockPS.get_instance.side_effect = Exception("Redis error")
            result = gen._should_send_keepalive(gen.local_index)

        self.assertFalse(result, "Redis error -> conservative, no keepalive")

    def test_non_owner_not_at_buffer_head_returns_false(self):
        """Non-owner, NOT at buffer head -> no keepalive regardless of Redis."""
        gen = self._make_generator()
        gen.buffer.index = 100  # far ahead of local_index=10
        server = self._mock_proxy_server(None)

        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
            MockPS.get_instance.return_value = server
            result = gen._should_send_keepalive(gen.local_index)

        self.assertFalse(result)

    def test_non_owner_insufficient_consecutive_empty_returns_false(self):
        """Non-owner, at head, but consecutive_empty < 5 -> no keepalive."""
        gen = self._make_generator(consecutive_empty=2)
        stale_ts = str(time.time() - 30.0).encode()
        server = self._mock_proxy_server(stale_ts)

        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
            MockPS.get_instance.return_value = server
            result = gen._should_send_keepalive(gen.local_index)

        self.assertFalse(result)


# ---------------------------------------------------------------------------
# _do_stats_update: error handling and WebSocket dispatch
# ---------------------------------------------------------------------------

class DoStatsUpdateTests(TestCase):
    """_do_stats_update runs the actual Redis scan + WebSocket call."""

    def _make_client_manager(self):
        from apps.proxy.live_proxy.client_manager import ClientManager
        cm = ClientManager.__new__(ClientManager)
        cm.channel_id = "00000000-0000-0000-0000-000000000004"
        cm._heartbeat_running = False
        return cm

    def test_do_stats_update_calls_send_websocket_update(self):
        """_do_stats_update must call send_websocket_update with channel_stats."""
        cm = self._make_client_manager()

        with patch("apps.proxy.live_proxy.client_manager.send_websocket_update") as mock_ws, \
             patch(
                 "apps.proxy.live_proxy.channel_status.build_live_channel_stats_data",
                 return_value={"channels": [], "count": 0},
             ), \
             patch("core.utils.RedisClient.get_client", return_value=MagicMock()):
            cm._do_stats_update()

        mock_ws.assert_called_once()
        event_type = mock_ws.call_args[0][1]
        self.assertEqual(event_type, "update")
        payload = mock_ws.call_args[0][2]
        self.assertEqual(payload["type"], "channel_stats")

    def test_do_stats_update_does_not_raise_on_redis_error(self):
        """Redis failure must be swallowed (logged), not propagated."""
        cm = self._make_client_manager()

        with patch("core.utils.RedisClient.get_client", side_effect=Exception("Redis down")):
            try:
                cm._do_stats_update()
            except Exception as e:
                self.fail(f"_do_stats_update raised an exception: {e}")

    def test_do_stats_update_uses_build_live_channel_stats_data(self):
        """Must build live stats via the shared builder."""
        cm = self._make_client_manager()
        mock_redis = MagicMock()

        with patch("apps.proxy.live_proxy.client_manager.send_websocket_update"), \
             patch(
                 "apps.proxy.live_proxy.channel_status.build_live_channel_stats_data",
                 return_value={"channels": [{"channel_id": "ch-1"}], "count": 1},
             ) as mock_build, \
             patch("core.utils.RedisClient.get_client", return_value=mock_redis):
            cm._do_stats_update()

        mock_build.assert_called_once_with(mock_redis)


# ---------------------------------------------------------------------------
# Integration: remove_client must not block on WebSocket
# ---------------------------------------------------------------------------

class ClientRemoveIntegrationTests(TestCase):
    """When remove_client() fires, _trigger_stats_update must not block."""

    def test_remove_client_does_not_block_on_websocket(self):
        """remove_client() must return quickly even if WebSocket is slow."""
        from apps.proxy.live_proxy.client_manager import ClientManager

        cm = ClientManager.__new__(ClientManager)
        cm.channel_id = "00000000-0000-0000-0000-000000000005"
        cm._heartbeat_running = False
        cm.clients = {"test-client-1"}
        cm.last_heartbeat_time = {"test-client-1": time.time()}
        cm.last_active_time = time.time()
        cm.client_set_key = f"live:channel:{cm.channel_id}:clients"
        cm.client_ttl = 60
        cm.worker_id = "worker-1"
        cm.proxy_server = MagicMock()
        cm.proxy_server.am_i_owner.return_value = False
        cm.lock = threading.Lock()

        mock_redis = MagicMock()
        mock_redis.hmget.return_value = (b"unknown", None)
        pipe = MagicMock()
        pipe.execute.return_value = [1, 1, 1]
        mock_redis.pipeline.return_value = pipe
        cm.redis_client = mock_redis

        slow_ws_called = threading.Event()

        def slow_websocket(*args, **kwargs):
            time.sleep(2.0)
            slow_ws_called.set()

        start = time.time()
        with patch("apps.proxy.live_proxy.client_manager.send_websocket_update", side_effect=slow_websocket):
            cm.remove_client("test-client-1")
        elapsed = time.time() - start

        self.assertLess(elapsed, 1.0,
                        f"remove_client() blocked for {elapsed:.2f}s waiting for WebSocket "
                        f"(should dispatch to background thread and return immediately)")

    def test_stream_generator_cleanup_does_not_schedule_owner_shutdown(self):
        """StreamGenerator cleanup should leave shutdown decisions to ClientManager/ProxyServer."""
        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator

        gen = StreamGenerator.__new__(StreamGenerator)
        gen.channel_id = "00000000-0000-0000-0000-000000000006"
        gen.client_id = "test-client-1"
        gen.client_ip = "127.0.0.1"
        gen.client_user_agent = "DispatcharrTest/1.0"
        gen.stream_start_time = time.time() - 1
        gen.bytes_sent = 1234
        gen.channel_name = "Cleanup Test"
        gen.user = None

        client_manager = MagicMock()
        client_manager.clients = {gen.client_id: MagicMock()}
        client_manager.remove_client.return_value = 0
        client_manager.get_total_client_count.return_value = 0

        proxy_server = MagicMock()
        proxy_server.client_managers = {gen.channel_id: client_manager}

        with patch(
            "apps.proxy.live_proxy.output.ts.generator.ProxyServer.get_instance",
            return_value=proxy_server,
        ), patch(
            "apps.proxy.live_proxy.url_utils.release_worker_stream",
            return_value=True,
        ) as mock_release_stream, patch(
            "apps.proxy.live_proxy.output.ts.generator.ConfigHelper.channel_shutdown_delay",
            return_value=0,
        ), patch(
            "apps.proxy.live_proxy.output.ts.generator.log_system_event",
        ), patch(
            "apps.proxy.live_proxy.output.ts.generator.gevent.spawn",
        ) as mock_spawn:
            gen._cleanup()

        client_manager.remove_client.assert_called_once_with(gen.client_id)
        mock_release_stream.assert_called_once_with(gen.channel_id)
        mock_spawn.assert_not_called()
        proxy_server.am_i_owner.assert_not_called()


# ---------------------------------------------------------------------------
# DVR timeout threshold vs keepalive timing
# ---------------------------------------------------------------------------

class KeepaliveTimingTests(TestCase):
    """Verify that keepalive threshold gives sufficient margin before DVR timeout."""

    def test_keepalive_threshold_less_than_dvr_timeout(self):
        """Default connection_timeout (keepalive trigger) must be < DVR read timeout (15s)."""
        from apps.proxy.config import TSConfig as Config
        connection_timeout = Config.get_connection_timeout()
        dvr_read_timeout = 15  # historical DVR HTTP read idle ceiling
        self.assertLess(
            connection_timeout,
            dvr_read_timeout,
            f"connection_timeout ({connection_timeout}s) must be < DVR timeout ({dvr_read_timeout}s) "
            f"so keepalives fire before DVR times out",
        )

    def test_keepalive_interval_is_short(self):
        """KEEPALIVE_INTERVAL must be short enough to send multiple keepalives in the gap."""
        from apps.proxy.config import TSConfig as Config
        interval = getattr(Config, "KEEPALIVE_INTERVAL", 0.5)
        connection_timeout = Config.get_connection_timeout()
        remaining_window = 15 - connection_timeout
        self.assertGreater(
            remaining_window / interval,
            3,
            f"KEEPALIVE_INTERVAL ({interval}s) is too long: only "
            f"{remaining_window/interval:.1f} keepalives would fit in the "
            f"{remaining_window}s window before DVR timeout",
        )


class ProxyConfigDefaultsTests(TestCase):
    def test_legacy_zero_shutdown_delay_gets_reconnect_grace(self):
        from apps.proxy.config import TSConfig

        with patch.object(
            TSConfig,
            "get_proxy_settings",
            return_value={
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 5,
            },
        ):
            self.assertEqual(TSConfig.get_channel_shutdown_delay(), 5)

    def test_legacy_realtime_buffering_threshold_is_softened(self):
        from apps.proxy.config import TSConfig

        with patch.object(
            TSConfig,
            "get_proxy_settings",
            return_value={"buffering_speed": 1.0},
        ):
            self.assertEqual(TSConfig.get_buffering_speed(), 0.95)
