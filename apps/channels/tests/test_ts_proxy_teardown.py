"""Tests for multi-worker channel teardown coordination."""
import time
from unittest.mock import ANY, MagicMock, patch

from django.test import TestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer
from apps.proxy.live_proxy.services.channel_service import ChannelService


CHANNEL_ID = "00000000-0000-0000-0000-000000000099"


def _configure_ownership_pipeline(
    redis,
    *,
    stop_exists=0,
    metadata_exists=1,
    client_count=0,
    owner=None,
    disconnect=None,
    state=None,
):
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.execute.return_value = (
        stop_exists,
        metadata_exists,
        client_count,
        owner,
        disconnect,
        state,
    )
    return pipe


def _mock_proxy_server(redis_client=None):
    server = MagicMock()
    server.redis_client = redis_client or MagicMock()
    server._stopping_channels = set()
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
        self.assertFalse(ChannelService.is_channel_unavailable_for_new_clients(CHANNEL_ID))

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.channel_shutdown_delay")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_cancel_pending_shutdown_clears_disconnect_key(self, mock_get_instance, mock_delay):
        mock_delay.return_value = 30
        redis = MagicMock()
        redis.exists.side_effect = lambda key: "last_client_disconnect" in key
        redis.get.return_value = None
        redis.hget.return_value = ChannelState.ACTIVE.encode()
        mock_get_instance.return_value = _mock_proxy_server(redis)

        self.assertTrue(ChannelService.cancel_pending_shutdown(CHANNEL_ID))
        redis.delete.assert_any_call(RedisKeys.last_client_disconnect(CHANNEL_ID))

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.channel_shutdown_delay")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_cancel_pending_shutdown_skips_during_active_stop(self, mock_get_instance, mock_delay):
        mock_delay.return_value = 30
        redis = MagicMock()
        redis.exists.return_value = True
        server = _mock_proxy_server(redis)
        server._stopping_channels = {CHANNEL_ID}
        mock_get_instance.return_value = server

        self.assertFalse(ChannelService.cancel_pending_shutdown(CHANNEL_ID))
        redis.delete.assert_not_called()

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.channel_shutdown_delay")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_cancel_pending_shutdown_skips_real_teardown_without_grace(self, mock_get_instance, mock_delay):
        mock_delay.return_value = 30
        redis = MagicMock()
        redis.exists.side_effect = lambda key: "stopping" in key
        redis.get.return_value = None
        redis.hget.return_value = ChannelState.STOPPING.encode()
        mock_get_instance.return_value = _mock_proxy_server(redis)

        self.assertFalse(ChannelService.cancel_pending_shutdown(CHANNEL_ID))
        redis.hset.assert_not_called()
        redis.delete.assert_not_called()

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.channel_shutdown_delay")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_shutdown_pending_expired_after_delay(self, mock_get_instance, mock_delay):
        mock_delay.return_value = 5
        redis = MagicMock()
        redis.exists.return_value = False
        redis.get.return_value = str(time.time() - 10).encode()
        mock_get_instance.return_value = _mock_proxy_server(redis)

        self.assertFalse(ChannelService.is_shutdown_pending(CHANNEL_ID))


class ClientManagerAddClientTests(TestCase):
    @patch("apps.proxy.live_proxy.services.channel_service.ChannelService.cancel_pending_shutdown", return_value=False)
    @patch("apps.proxy.live_proxy.client_manager.send_websocket_update")
    def test_add_client_stores_ip_and_user_agent_in_redis(self, _mock_ws, _mock_cancel):
        from apps.proxy.live_proxy.client_manager import ClientManager

        redis = MagicMock()
        cm = ClientManager(CHANNEL_ID, redis_client=redis, worker_id="worker-1")
        cm.proxy_server = MagicMock()

        result = cm.add_client(
            "client-1",
            "10.0.2.163",
            user_agent="VLC/3.0.21",
        )

        self.assertEqual(result, 1)
        mapping = redis.hset.call_args[1]["mapping"]
        self.assertEqual(mapping["ip_address"], "10.0.2.163")
        self.assertEqual(mapping["user_agent"], "VLC/3.0.21")


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
    @patch.object(ProxyServer, "_has_local_upstream_activity", return_value=True)
    def test_orphan_metadata_stops_local_processes_before_redis(
        self, mock_has_upstream, mock_stop_local, mock_clean_redis
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

        mock_has_upstream.assert_called_with(CHANNEL_ID)
        mock_stop_local.assert_called_once_with(CHANNEL_ID)
        mock_clean_redis.assert_called_once_with(CHANNEL_ID)

    @patch.object(ProxyServer, "_clean_redis_keys")
    @patch.object(ProxyServer, "_broadcast_upstream_stop")
    @patch.object(ProxyServer, "_stop_local_stream_activity")
    @patch.object(ProxyServer, "_has_local_upstream_activity", return_value=False)
    def test_orphan_metadata_remote_channel_broadcasts_stop(
        self, mock_has_upstream, mock_stop_local, mock_broadcast, mock_clean_redis
    ):
        server = self._make_server()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        server.redis_client.keys.return_value = [metadata_key.encode()]
        server.redis_client.hgetall.return_value = {b"owner": b"", b"state": b"unknown"}
        server.redis_client.exists.return_value = False
        server.redis_client.scard.return_value = 0

        server._check_orphaned_metadata()

        mock_broadcast.assert_called_once_with(CHANNEL_ID)
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
    @patch.object(ProxyServer, "_has_local_upstream_activity", return_value=True)
    def test_orphan_channel_stops_local_before_redis(
        self, mock_has_upstream, mock_stop_local, mock_clean_redis
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
        _configure_ownership_pipeline(
            buffer.redis_client,
            owner=b"worker-b",
        )
        manager = StreamManager(
            CHANNEL_ID, "http://example/stream", buffer, worker_id="worker-a"
        )

        self.assertFalse(manager._still_owner())

    def test_still_owner_true_when_owner_lock_expired_but_not_stopping(self):
        buffer = MagicMock()
        _configure_ownership_pipeline(
            buffer.redis_client,
            client_count=0,
            owner=None,
            state=ChannelState.CONNECTING.encode(),
        )
        manager = StreamManager(
            CHANNEL_ID, "http://example/stream", buffer, worker_id="worker-a"
        )

        self.assertTrue(manager._still_owner())

    def test_still_owner_false_when_channel_stopping_key_set(self):
        buffer = MagicMock()
        _configure_ownership_pipeline(
            buffer.redis_client,
            stop_exists=1,
        )
        manager = StreamManager(
            CHANNEL_ID, "http://example/stream", buffer, worker_id="worker-a"
        )

        self.assertFalse(manager._still_owner())

    def test_update_bytes_skipped_after_ownership_lost(self):
        buffer = MagicMock()
        _configure_ownership_pipeline(
            buffer.redis_client,
            owner=b"other-worker",
        )
        manager = StreamManager(
            CHANNEL_ID, "http://example/stream", buffer, worker_id="worker-a"
        )
        manager.bytes_processed = 1000

        manager._update_bytes_processed(500)

        buffer.redis_client.hincrby.assert_not_called()


class StreamBufferStopTests(TestCase):
    def test_stop_discards_local_data_without_redis_writes(self):
        redis = MagicMock()
        buffer = StreamBuffer(channel_id=CHANNEL_ID, redis_client=redis)
        buffer._write_buffer = bytearray(b"x" * 376)

        buffer.stop()

        self.assertTrue(buffer.stopping)
        self.assertEqual(len(buffer._write_buffer), 0)
        redis.incr.assert_not_called()
        redis.setex.assert_not_called()
        redis.delete.assert_not_called()


class StopChannelTeardownTests(TestCase):
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
        server._stopping_since = {}
        server.redis_client = MagicMock()
        server.redis_client.exists.return_value = False
        server.am_i_owner = MagicMock(return_value=False)
        server._collect_channel_stop_event_data = MagicMock(return_value=None)
        server.release_ownership = MagicMock()
        return server

    @patch.object(ProxyServer, "_spawn_channel_stop_event")
    @patch.object(ProxyServer, "_clean_redis_keys")
    @patch.object(ProxyServer, "_stop_local_stream_activity")
    def test_stop_channel_cleans_redis_before_blocking_local_stop(
        self, mock_stop_local, mock_clean_redis, mock_spawn_event
    ):
        server = self._make_server()
        call_order = []

        def stop_local(channel_id):
            call_order.append("local")

        def clean_redis(channel_id):
            call_order.append("redis")

        mock_stop_local.side_effect = stop_local
        mock_clean_redis.side_effect = clean_redis

        server.stop_channel(CHANNEL_ID)

        self.assertEqual(call_order, ["redis", "local"])
        mock_spawn_event.assert_called_once_with(None)

    @patch.object(ProxyServer, "_spawn_channel_stop_event")
    @patch.object(ProxyServer, "_clean_redis_keys")
    @patch.object(ProxyServer, "_stop_local_stream_activity", side_effect=RuntimeError("boom"))
    def test_stop_channel_cleans_redis_in_finally_when_local_stop_fails(
        self, mock_stop_local, mock_clean_redis, mock_spawn_event
    ):
        server = self._make_server()

        result = server.stop_channel(CHANNEL_ID)

        self.assertFalse(result)
        mock_clean_redis.assert_called_once_with(CHANNEL_ID)
        mock_spawn_event.assert_not_called()
        self.assertNotIn(CHANNEL_ID, server._stopping_channels)

    @patch.object(ProxyServer, "_spawn_channel_stop_event")
    @patch.object(ProxyServer, "_clean_redis_keys")
    @patch.object(ProxyServer, "_stop_local_stream_activity")
    def test_stop_channel_owner_releases_after_redis_cleanup(
        self, mock_stop_local, mock_clean_redis, mock_spawn_event
    ):
        server = self._make_server()
        server.am_i_owner.return_value = True
        stop_data = {"channel_id": CHANNEL_ID}
        server._collect_channel_stop_event_data.return_value = stop_data
        call_order = []

        def stop_local(channel_id):
            call_order.append("local")

        def release(channel_id):
            call_order.append("release")

        def clean_redis(channel_id):
            call_order.append("redis")

        mock_stop_local.side_effect = stop_local
        server.release_ownership.side_effect = release
        mock_clean_redis.side_effect = clean_redis

        server.stop_channel(CHANNEL_ID)

        self.assertEqual(call_order, ["redis", "release", "local"])
        server._collect_channel_stop_event_data.assert_called_once_with(CHANNEL_ID)
        mock_spawn_event.assert_called_once_with(stop_data)


class CleanRedisKeysOrderTests(TestCase):
    @patch("apps.proxy.live_proxy.server.Stream.objects.get")
    @patch("apps.proxy.live_proxy.server.Channel.objects.get")
    def test_clean_redis_keys_releases_profile_slot_before_live_keys_deleted(
        self, mock_channel_get, mock_stream_get
    ):
        from apps.channels.models import Channel, Stream

        with patch("apps.proxy.live_proxy.server.RedisClient.get_client", return_value=MagicMock()):
            server = ProxyServer()
        server.redis_client = MagicMock()
        call_order = []

        channel = MagicMock()
        channel.release_stream.return_value = True

        def channel_get(uuid):
            call_order.append("release")
            return channel

        mock_channel_get.side_effect = channel_get
        mock_stream_get.side_effect = Stream.DoesNotExist

        channel_key = f"live:channel:{CHANNEL_ID}:input:buffer:index".encode()

        def scan(cursor, match=None, count=100):
            call_order.append("redis")
            if match == f"live:channel:{CHANNEL_ID}:*":
                return (0, [channel_key])
            return (0, [])

        server.redis_client.scan.side_effect = scan

        server._clean_redis_keys(CHANNEL_ID)

        self.assertEqual(call_order, ["release", "redis", "redis"])
        channel.release_stream.assert_called_once()
        server.redis_client.delete.assert_called_once_with(channel_key)

    @patch("apps.m3u.connection_pool.release_profile_slot")
    @patch("apps.proxy.live_proxy.server.Stream.objects.get")
    @patch("apps.proxy.live_proxy.server.Channel.objects.get")
    def test_clean_redis_keys_releases_profile_from_metadata_when_channel_gone(
        self, mock_channel_get, mock_stream_get, mock_release_slot
    ):
        """Delete-without-stop leaves Redis session; later stop must free the slot."""
        from apps.channels.models import Channel, Stream

        with patch(
            "apps.proxy.live_proxy.server.RedisClient.get_client",
            return_value=MagicMock(),
        ):
            server = ProxyServer()
        server.redis_client = MagicMock()
        mock_channel_get.side_effect = Channel.DoesNotExist
        mock_stream_get.side_effect = Stream.DoesNotExist

        def hget(key, field):
            mapping = {
                ChannelMetadataField.STREAM_ID: b"2243070",
                ChannelMetadataField.M3U_PROFILE: b"50",
                ChannelMetadataField.CHANNEL_ID: b"224",
            }
            return mapping.get(field)

        server.redis_client.hget.side_effect = hget
        server.redis_client.scan.return_value = (0, [])

        server._clean_redis_keys(CHANNEL_ID)

        mock_release_slot.assert_called_once_with(50, server.redis_client)
        server.redis_client.delete.assert_any_call("channel_stream:224")
        server.redis_client.delete.assert_any_call("stream_profile:2243070")


class LocalUpstreamActivityTests(TestCase):
    def _make_server(self):
        with patch("apps.proxy.live_proxy.server.RedisClient.get_client", return_value=MagicMock()):
            server = ProxyServer()
        server.worker_id = "testhost:1"
        server.stream_managers = {}
        server.stream_buffers = {}
        server.client_managers = {}
        server._live_stream_managers = {}
        return server

    def test_upstream_activity_excludes_reader_only_client_manager(self):
        server = self._make_server()
        server.client_managers[CHANNEL_ID] = MagicMock()
        server.stream_buffers[CHANNEL_ID] = MagicMock()
        self.assertFalse(server._has_local_upstream_activity(CHANNEL_ID))

    def test_upstream_activity_from_live_registry(self):
        server = self._make_server()
        server._live_stream_managers[CHANNEL_ID] = MagicMock()
        self.assertTrue(server._has_local_upstream_activity(CHANNEL_ID))


class ClientDisconnectOwnershipTests(TestCase):
    def test_last_client_triggers_stop_when_upstream_active_without_owner_lock(self):
        from apps.proxy.live_proxy.client_manager import ClientManager

        proxy_server = MagicMock()
        proxy_server.worker_id = "testhost:1"
        proxy_server.am_i_owner.return_value = False
        proxy_server._has_local_upstream_activity.return_value = True
        proxy_server.extend_ownership.return_value = False

        redis = MagicMock()
        redis.hget.return_value = b"viewer"
        redis.scard.return_value = 0

        manager = ClientManager(
            channel_id=CHANNEL_ID,
            redis_client=redis,
            worker_id="testhost:1",
        )
        manager.proxy_server = proxy_server
        manager.clients = {"client-1"}
        manager.client_set_key = RedisKeys.clients(CHANNEL_ID)
        manager._notify_owner_of_activity = MagicMock()
        manager._trigger_stats_update = MagicMock()
        manager.get_total_client_count = MagicMock(return_value=0)
        proxy_server._spawn_on_hub = MagicMock()

        manager.remove_client("client-1")

        proxy_server._spawn_on_hub.assert_called_once_with(
            proxy_server.handle_client_disconnect, CHANNEL_ID
        )


class TeardownActiveLocalStopTests(TestCase):
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance")
    def test_teardown_active_when_local_stop_in_progress(self, mock_get_instance):
        server = MagicMock()
        server._stopping_channels = {CHANNEL_ID}
        server.redis_client = MagicMock()
        server.redis_client.exists.return_value = False
        mock_get_instance.return_value = server

        self.assertTrue(ChannelService.is_channel_teardown_active(CHANNEL_ID))


class HandleClientDisconnectUpstreamFirstTests(TestCase):
    def _make_server(self):
        with patch("apps.proxy.live_proxy.server.RedisClient.get_client", return_value=MagicMock()):
            server = ProxyServer()
        server.worker_id = "testhost:1"
        server.client_managers = {CHANNEL_ID: MagicMock()}
        server.stream_managers = {CHANNEL_ID: MagicMock()}
        server._live_stream_managers = {}
        server.profile_managers = {}
        server.output_managers = {}
        server.redis_client = MagicMock()
        server.redis_client.scard.return_value = 0
        server._stopping_channels = set()
        return server

    @patch.object(ProxyServer, "_coordinated_stop_channel")
    @patch.object(ProxyServer, "_stop_upstream_before_redis_cleanup")
    @patch.object(ProxyServer, "_has_local_upstream_activity", return_value=True)
    def test_last_client_uses_coordinated_stop_only(
        self, _mock_upstream, mock_stop_upstream, mock_coordinated
    ):
        server = self._make_server()

        with patch(
            "apps.proxy.live_proxy.server.ConfigHelper.channel_shutdown_delay",
            return_value=0,
        ):
            server.handle_client_disconnect(CHANNEL_ID)

        mock_stop_upstream.assert_not_called()
        mock_coordinated.assert_called_once_with(CHANNEL_ID)


class ShutdownDelayWaitTests(TestCase):
    def _make_server(self):
        with patch("apps.proxy.live_proxy.server.RedisClient.get_client", return_value=MagicMock()):
            with patch.object(ProxyServer, "_start_cleanup_thread"):
                server = ProxyServer()
        server.redis_client = MagicMock()
        server.redis_client.scard.return_value = 0
        return server

    @patch("apps.proxy.live_proxy.server.gevent.sleep")
    @patch("apps.proxy.live_proxy.server.time.time", return_value=1000.0)
    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_shutdown_delay", return_value=30)
    def test_aborts_when_disconnect_key_deleted(self, _mock_delay, _mock_time, mock_sleep):
        server = self._make_server()
        server.redis_client.get.side_effect = [b"1000.0", None]

        result = server._wait_for_shutdown_delay(CHANNEL_ID)

        self.assertFalse(result)
        self.assertGreaterEqual(mock_sleep.call_count, 1)

    @patch("apps.proxy.live_proxy.server.gevent.sleep")
    @patch("apps.proxy.live_proxy.server.time.time", return_value=1000.0)
    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_shutdown_delay", return_value=30)
    def test_aborts_when_clients_reconnect(self, _mock_delay, _mock_time, _mock_sleep):
        server = self._make_server()
        server.redis_client.get.return_value = b"1000.0"
        server.redis_client.scard.side_effect = [0, 1]

        result = server._wait_for_shutdown_delay(CHANNEL_ID)

        self.assertFalse(result)
        server.redis_client.delete.assert_called_with(
            RedisKeys.last_client_disconnect(CHANNEL_ID)
        )

    @patch("apps.proxy.live_proxy.server.gevent.sleep")
    @patch("apps.proxy.live_proxy.server.time.time")
    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_shutdown_delay", return_value=30)
    def test_timer_resets_when_disconnect_timestamp_updated(
        self, _mock_delay, mock_time, mock_sleep
    ):
        server = self._make_server()
        disconnect_key = RedisKeys.last_client_disconnect(CHANNEL_ID)
        current_time = [1000.0]
        disconnect_timestamp = [1000.0]
        poll_count = [0]

        mock_time.side_effect = lambda: current_time[0]

        def get_side_effect(key):
            poll_count[0] += 1
            if poll_count[0] >= 3:
                disconnect_timestamp[0] = 1020.0
            if key == disconnect_key:
                return str(disconnect_timestamp[0]).encode()
            return None

        server.redis_client.get.side_effect = get_side_effect

        def advance_sleep(duration):
            current_time[0] += duration

        mock_sleep.side_effect = advance_sleep

        result = server._wait_for_shutdown_delay(CHANNEL_ID)

        self.assertTrue(result)
        self.assertGreaterEqual(current_time[0], 1050.0)

    @patch.object(ProxyServer, "_coordinated_stop_channel")
    @patch.object(ProxyServer, "_wait_for_shutdown_delay", return_value=True)
    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_shutdown_delay", return_value=30)
    def test_handle_client_disconnect_uses_polling_wait(
        self, _mock_delay, mock_wait, mock_coordinated
    ):
        server = HandleClientDisconnectUpstreamFirstTests()._make_server()
        server.redis_client.get.return_value = b"1700000000.0"

        server.handle_client_disconnect(CHANNEL_ID)

        mock_wait.assert_called_once_with(CHANNEL_ID)
        mock_coordinated.assert_called_once_with(CHANNEL_ID)

    @patch.object(ProxyServer, "_coordinated_stop_channel")
    @patch.object(ProxyServer, "_wait_for_shutdown_delay", return_value=False)
    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_shutdown_delay", return_value=30)
    def test_handle_client_disconnect_skips_stop_when_wait_aborted(
        self, _mock_delay, _mock_wait, mock_coordinated
    ):
        server = HandleClientDisconnectUpstreamFirstTests()._make_server()
        server.redis_client.get.return_value = b"1700000000.0"

        server.handle_client_disconnect(CHANNEL_ID)

        mock_coordinated.assert_not_called()


class InitWaitAbortTests(TestCase):
    def setUp(self):
        self._teardown_patch = patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService.is_channel_teardown_active",
            return_value=False,
        )
        self._teardown_patch.start()

    def tearDown(self):
        self._teardown_patch.stop()

    def _make_generator(self):
        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator

        return StreamGenerator(
            CHANNEL_ID,
            "client-1",
            "127.0.0.1",
            "test-agent",
            channel_initializing=True,
        )

    def test_abort_when_client_removed_locally(self):
        generator = self._make_generator()
        server = MagicMock()
        client_manager = MagicMock()
        client_manager.clients = set()
        server.client_managers = {CHANNEL_ID: client_manager}
        server.redis_client = MagicMock()

        self.assertEqual(generator._init_wait_abort_reason(server, time.time()), "client_gone")

    @patch("apps.proxy.live_proxy.output.ts.generator.ConfigHelper.channel_init_grace_period", return_value=10)
    def test_abort_when_connect_stalled_without_buffer(self, _mock_grace):
        generator = self._make_generator()
        server = MagicMock()
        client_manager = MagicMock()
        client_manager.clients = {"client-1"}
        server.client_managers = {CHANNEL_ID: client_manager}
        buffer = MagicMock()
        buffer.index = 0
        server.stream_buffers = {CHANNEL_ID: buffer}
        server.redis_client = MagicMock()
        server.redis_client.hget.return_value = b"connecting"
        server.redis_client.get.return_value = None

        started = time.time() - 11
        self.assertEqual(generator._init_wait_abort_reason(server, started), "stalled")

    @patch("apps.proxy.live_proxy.output.ts.generator.ConfigHelper.channel_init_grace_period", return_value=30)
    def test_no_stall_abort_within_init_grace_period(self, _mock_grace):
        generator = self._make_generator()
        server = MagicMock()
        client_manager = MagicMock()
        client_manager.clients = {"client-1"}
        server.client_managers = {CHANNEL_ID: client_manager}
        buffer = MagicMock()
        buffer.index = 0
        server.stream_buffers = {CHANNEL_ID: buffer}
        server.redis_client = MagicMock()
        server.redis_client.hget.return_value = b"connecting"
        server.redis_client.get.return_value = None

        started = time.time() - 15
        self.assertIsNone(generator._init_wait_abort_reason(server, started))

    @patch("apps.proxy.live_proxy.output.ts.generator.ConfigHelper.channel_init_grace_period", return_value=30)
    def test_stall_abort_after_init_grace_period(self, _mock_grace):
        generator = self._make_generator()
        server = MagicMock()
        client_manager = MagicMock()
        client_manager.clients = {"client-1"}
        server.client_managers = {CHANNEL_ID: client_manager}
        buffer = MagicMock()
        buffer.index = 0
        server.stream_buffers = {CHANNEL_ID: buffer}
        server.redis_client = MagicMock()
        server.redis_client.hget.return_value = b"connecting"
        server.redis_client.get.return_value = None

        started = time.time() - 31
        self.assertEqual(generator._init_wait_abort_reason(server, started), "stalled")


class PromoteChannelWhenBufferReadyTests(TestCase):
    def _mock_proxy(self, redis_client):
        proxy_server = MagicMock()
        proxy_server.redis_client = redis_client
        return patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance",
            return_value=proxy_server,
        ), proxy_server

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.initial_behind_chunks", return_value=4)
    def test_buffer_ready_with_clients_becomes_active(self, _mock_chunks):
        redis = MagicMock()
        redis.hget.return_value = ChannelState.CONNECTING.encode()
        redis.get.return_value = b"4"
        redis.scard.return_value = 2

        ctx, proxy_server = self._mock_proxy(redis)
        with ctx:
            result = ChannelService.promote_channel_when_buffer_ready(CHANNEL_ID)

        self.assertEqual(result, ChannelState.ACTIVE)
        proxy_server.update_channel_state.assert_called_once()
        args = proxy_server.update_channel_state.call_args[0]
        self.assertEqual(args[1], ChannelState.ACTIVE)
        self.assertEqual(args[2]["clients_at_activation"], "2")

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.initial_behind_chunks", return_value=4)
    def test_buffer_ready_without_clients_becomes_waiting(self, _mock_chunks):
        redis = MagicMock()
        redis.hget.return_value = ChannelState.CONNECTING.encode()
        redis.get.return_value = b"5"
        redis.scard.return_value = 0

        ctx, proxy_server = self._mock_proxy(redis)
        with ctx:
            result = ChannelService.promote_channel_when_buffer_ready(CHANNEL_ID)

        self.assertEqual(result, ChannelState.WAITING_FOR_CLIENTS)
        proxy_server.update_channel_state.assert_called_once_with(
            CHANNEL_ID,
            ChannelState.WAITING_FOR_CLIENTS,
            {
                ChannelMetadataField.CONNECTION_READY_TIME: ANY,
                ChannelMetadataField.BUFFER_CHUNKS: "5",
            },
        )

    @patch("apps.proxy.live_proxy.services.channel_service.ConfigHelper.initial_behind_chunks", return_value=4)
    def test_buffer_not_ready_does_not_promote(self, _mock_chunks):
        redis = MagicMock()
        redis.hget.return_value = ChannelState.CONNECTING.encode()
        redis.get.return_value = b"2"

        ctx, proxy_server = self._mock_proxy(redis)
        with ctx:
            result = ChannelService.promote_channel_when_buffer_ready(CHANNEL_ID)

        self.assertIsNone(result)
        proxy_server.update_channel_state.assert_not_called()

    def test_waiting_for_clients_with_clients_becomes_active(self):
        redis = MagicMock()

        def hget_side_effect(key, field):
            if field == ChannelMetadataField.STATE:
                return ChannelState.WAITING_FOR_CLIENTS.encode()
            if field == ChannelMetadataField.CONNECTION_READY_TIME:
                return b"1700000000.0"
            return None

        redis.hget.side_effect = hget_side_effect
        redis.scard.return_value = 1

        ctx, proxy_server = self._mock_proxy(redis)
        with ctx:
            result = ChannelService.promote_channel_when_buffer_ready(CHANNEL_ID)

        self.assertEqual(result, ChannelState.ACTIVE)
        proxy_server.update_channel_state.assert_called_once_with(
            CHANNEL_ID,
            ChannelState.ACTIVE,
            {"clients_at_activation": "1"},
        )


class UpstreamStopBroadcastTests(TestCase):
    def _make_server(self):
        with patch("apps.proxy.live_proxy.server.RedisClient.get_client", return_value=MagicMock()):
            server = ProxyServer()
        server.worker_id = "testhost:1"
        server.stream_managers = {}
        server._live_stream_managers = {}
        server.redis_client = MagicMock()
        return server

    @patch.object(ProxyServer, "_stop_local_stream_activity")
    @patch.object(ProxyServer, "_broadcast_upstream_stop")
    @patch.object(ProxyServer, "_has_local_upstream_activity", return_value=True)
    def test_local_upstream_stops_locally_without_broadcast(
        self, _mock_has, mock_broadcast, mock_stop_local
    ):
        server = self._make_server()
        server._stop_upstream_before_redis_cleanup(CHANNEL_ID)
        mock_stop_local.assert_called_once_with(CHANNEL_ID)
        mock_broadcast.assert_not_called()

    @patch.object(ProxyServer, "_stop_local_stream_activity")
    @patch.object(ProxyServer, "_broadcast_upstream_stop")
    @patch.object(ProxyServer, "_has_local_upstream_activity", return_value=False)
    def test_orphan_cleanup_broadcasts_when_no_local_upstream(
        self, _mock_has, mock_broadcast, mock_stop_local
    ):
        server = self._make_server()
        server._stop_upstream_before_redis_cleanup(CHANNEL_ID)
        mock_broadcast.assert_called_once_with(CHANNEL_ID)
        mock_stop_local.assert_not_called()


class StreamManagerStillOwnerTests(TestCase):
    def _make_manager(self, redis_client):
        buffer = MagicMock()
        buffer.redis_client = redis_client
        buffer.channel_id = CHANNEL_ID
        manager = StreamManager(
            CHANNEL_ID,
            "http://example/stream.ts",
            buffer,
            worker_id="testhost:1",
        )
        return manager

    def test_stops_when_metadata_removed(self):
        redis = MagicMock()
        _configure_ownership_pipeline(redis, metadata_exists=0)
        manager = self._make_manager(redis)
        self.assertFalse(manager._still_owner())

    def test_keeps_running_during_connecting_before_client_registered(self):
        redis = MagicMock()
        _configure_ownership_pipeline(
            redis,
            client_count=0,
            owner=b"testhost:1",
            state=ChannelState.CONNECTING.encode(),
        )
        manager = self._make_manager(redis)
        self.assertTrue(manager._still_owner())

    def test_stops_after_disconnect_when_shutdown_delay_is_zero(self):
        redis = MagicMock()
        _configure_ownership_pipeline(
            redis,
            client_count=0,
            owner=b"testhost:1",
            disconnect=b"1700000000.0",
            state=ChannelState.ACTIVE.encode(),
        )
        manager = self._make_manager(redis)
        with patch(
            "apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay",
            return_value=0,
        ):
            self.assertFalse(manager._still_owner())

    def test_keeps_running_during_shutdown_delay(self):
        redis = MagicMock()
        _configure_ownership_pipeline(
            redis,
            client_count=0,
            owner=b"testhost:1",
            disconnect=str(time.time()).encode(),
            state=ChannelState.ACTIVE.encode(),
        )
        manager = self._make_manager(redis)
        with patch(
            "apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay",
            return_value=5,
        ):
            self.assertTrue(manager._still_owner())


class PreActiveNoClientsTimeoutTests(TestCase):
    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_client_wait_period", return_value=5)
    def test_buffer_ready_uses_client_wait_period(self, _mock_client_wait):
        should_stop, timeout, reason = ProxyServer._pre_active_no_clients_should_stop(
            connection_ready_time=1000.0,
            start_time=900.0,
            now=1006.0,
        )
        self.assertTrue(should_stop)
        self.assertEqual(timeout, 5)
        self.assertEqual(reason, "client_wait")

    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_client_wait_period", return_value=5)
    def test_buffer_ready_within_client_wait_period(self, _mock_client_wait):
        should_stop, timeout, reason = ProxyServer._pre_active_no_clients_should_stop(
            connection_ready_time=1000.0,
            start_time=900.0,
            now=1003.0,
        )
        self.assertFalse(should_stop)
        self.assertEqual(timeout, 5)
        self.assertEqual(reason, "client_wait")

    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_init_grace_period", return_value=60)
    def test_startup_uses_init_grace_period(self, _mock_init_grace):
        should_stop, timeout, reason = ProxyServer._pre_active_no_clients_should_stop(
            connection_ready_time=None,
            start_time=1000.0,
            now=1070.0,
        )
        self.assertTrue(should_stop)
        self.assertEqual(timeout, 60)
        self.assertEqual(reason, "startup")

    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_init_grace_period", return_value=60)
    def test_startup_within_init_grace_period(self, _mock_init_grace):
        should_stop, timeout, reason = ProxyServer._pre_active_no_clients_should_stop(
            connection_ready_time=None,
            start_time=1000.0,
            now=1030.0,
        )
        self.assertFalse(should_stop)
        self.assertEqual(timeout, 60)
        self.assertEqual(reason, "startup")

    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_shutdown_delay", return_value=30)
    @patch("apps.proxy.live_proxy.server.ConfigHelper.channel_client_wait_period", return_value=5)
    def test_buffer_ready_does_not_use_shutdown_delay(self, mock_client_wait, mock_shutdown_delay):
        should_stop, _, reason = ProxyServer._pre_active_no_clients_should_stop(
            connection_ready_time=1000.0,
            start_time=900.0,
            now=1006.0,
        )
        self.assertTrue(should_stop)
        self.assertEqual(reason, "client_wait")
        mock_client_wait.assert_called_once()
        mock_shutdown_delay.assert_not_called()
