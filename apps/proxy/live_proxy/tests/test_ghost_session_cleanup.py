"""
Channel init ownership order: initializing metadata must only be written after
the ownership lock is held, and failed inits must tear down Redis/local state
immediately instead of leaving a dead session behind.
"""

from unittest.mock import MagicMock, patch

from django.http import StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase


def make_proxy_server(redis_client):
    """Build a ProxyServer without running __init__ (no threads, no Redis)."""
    from apps.proxy.live_proxy.server import ProxyServer

    server = ProxyServer.__new__(ProxyServer)
    server.redis_client = redis_client
    server.stream_managers = {}
    server.stream_buffers = {}
    server.client_managers = {}
    server.output_managers = {}
    server.profile_managers = {}
    server.profile_buffers = {}
    server._channel_names = {}
    server._stopping_channels = set()
    server._stopping_since = {}
    server._local_stop_locks = {}
    server._channel_init_locks = {}
    server._channels_setting_up = set()
    server._live_stream_managers = {}
    server.worker_id = "test-host:1"
    return server


CHANNEL_ID = "11111111-2222-3333-4444-555555555555"


def _configure_init_lock_mocks(proxy_server):
    """Wire MagicMock ProxyServer helpers to a real gevent RLock + setup set."""
    import gevent.lock

    lock = gevent.lock.RLock()
    proxy_server._channels_setting_up = set()
    proxy_server._get_channel_init_lock.return_value = lock
    proxy_server._finish_channel_init_lock.side_effect = (
        lambda _channel_id, held_lock: held_lock.release()
    )
    proxy_server._clear_channel_setting_up.side_effect = (
        lambda channel_id: proxy_server._channels_setting_up.discard(channel_id)
    )
    return lock


class CleanupFailedInitTests(SimpleTestCase):
    def test_cleans_redis_and_local_state(self):
        redis = MagicMock()
        redis.get.return_value = None  # no owner
        redis.hget.return_value = "initializing"
        server = make_proxy_server(redis)
        server.stream_buffers[CHANNEL_ID] = object()
        server.client_managers[CHANNEL_ID] = object()
        server._channels_setting_up.add(CHANNEL_ID)
        server._stop_local_stream_activity = MagicMock()
        server.release_ownership = MagicMock()
        server._clean_redis_keys = MagicMock()

        server._cleanup_failed_init(CHANNEL_ID, "boom")

        server._stop_local_stream_activity.assert_called_once_with(CHANNEL_ID)
        server.release_ownership.assert_called_once_with(
            CHANNEL_ID, signal_stopping=False
        )
        server._clean_redis_keys.assert_called_once_with(CHANNEL_ID)
        self.assertNotIn(CHANNEL_ID, server.stream_buffers)
        self.assertNotIn(CHANNEL_ID, server.client_managers)
        self.assertNotIn(CHANNEL_ID, server._channels_setting_up)

    def test_does_not_touch_channel_owned_by_other_worker(self):
        redis = MagicMock()
        redis.get.return_value = "other-host:2"
        server = make_proxy_server(redis)
        server._stop_local_stream_activity = MagicMock()
        server._clean_redis_keys = MagicMock()

        server._cleanup_failed_init(CHANNEL_ID, "boom")

        server._stop_local_stream_activity.assert_not_called()
        server._clean_redis_keys.assert_not_called()

    def test_does_not_clobber_active_state(self):
        redis = MagicMock()
        redis.get.return_value = None
        redis.hget.return_value = "active"
        server = make_proxy_server(redis)
        server._stop_local_stream_activity = MagicMock()
        server._clean_redis_keys = MagicMock()

        server._cleanup_failed_init(CHANNEL_ID, "boom")

        server._stop_local_stream_activity.assert_not_called()
        server._clean_redis_keys.assert_not_called()


class InitializeChannelOwnershipOrderTests(SimpleTestCase):
    """Root cause: never write initializing before the ownership lock."""

    def test_no_url_does_not_write_initializing_before_lock(self):
        redis = MagicMock()
        redis.exists.return_value = False
        redis.hgetall.return_value = {}
        redis.get.return_value = None  # no current owner
        server = make_proxy_server(redis)
        server._channel_unavailable_for_new_clients = MagicMock(return_value=False)
        server._has_local_upstream_activity = MagicMock(return_value=False)
        server.try_acquire_ownership = MagicMock(return_value=True)

        with patch("apps.proxy.live_proxy.server.StreamBuffer"), \
                patch("apps.proxy.live_proxy.server.ClientManager"), \
                patch("apps.proxy.live_proxy.server.RedisClient"), \
                patch("apps.proxy.live_proxy.server.close_old_connections"), \
                patch.object(server, "_cleanup_failed_init") as mock_cleanup:
            result = server.initialize_channel(None, CHANNEL_ID)

        self.assertFalse(result)
        # Must fail before acquiring ownership when no URL is available
        server.try_acquire_ownership.assert_not_called()
        mock_cleanup.assert_called_once()
        # No initializing metadata write should have happened
        for call in redis.hset.call_args_list:
            mapping = call.kwargs.get("mapping") or (
                call.args[1] if len(call.args) > 1 else {}
            )
            if isinstance(mapping, dict):
                self.assertNotEqual(mapping.get("state"), "initializing")

    def test_writes_initializing_only_after_ownership(self):
        redis = MagicMock()
        redis.exists.return_value = False
        redis.hgetall.return_value = {}
        redis.get.return_value = None
        redis.hget.return_value = "1"
        redis.ttl.return_value = 3600
        server = make_proxy_server(redis)
        server._channel_unavailable_for_new_clients = MagicMock(return_value=False)
        server._has_local_upstream_activity = MagicMock(return_value=False)
        server.try_acquire_ownership = MagicMock(return_value=True)
        server.am_i_owner = MagicMock(return_value=True)
        server.update_channel_state = MagicMock()

        hset_states = []

        def track_hset(*args, **kwargs):
            mapping = kwargs.get("mapping") or (args[1] if len(args) > 1 else {})
            if isinstance(mapping, dict) and "state" in mapping:
                hset_states.append(mapping["state"])
            # Ownership must already have been acquired before any state write
            server.try_acquire_ownership.assert_called()

        redis.hset.side_effect = track_hset

        with patch("apps.proxy.live_proxy.server.StreamBuffer"), \
                patch("apps.proxy.live_proxy.server.ClientManager"), \
                patch("apps.proxy.live_proxy.server.StreamManager"), \
                patch("apps.proxy.live_proxy.server.RedisClient"), \
                patch("apps.proxy.live_proxy.server.close_old_connections"), \
                patch("apps.proxy.live_proxy.server.log_system_event"), \
                patch("apps.proxy.live_proxy.server.threading.Thread"):
            result = server.initialize_channel(
                "http://example.com/stream.ts",
                CHANNEL_ID,
                user_agent="ua",
                stream_id=1,
            )

        self.assertTrue(result)
        self.assertIn("initializing", hset_states)
        server.try_acquire_ownership.assert_called_once_with(CHANNEL_ID)


class StreamTsEarlyOwnershipTests(SimpleTestCase):
    """Play setup must take ownership before generate_stream_url."""

    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_follower_skips_stream_reservation_when_ownership_lost(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        channel.get_stream_profile.return_value.is_redirect.return_value = False
        mock_get_stream_object.return_value = channel

        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False

        proxy_server = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.try_acquire_ownership.return_value = False
        _configure_init_lock_mocks(proxy_server)
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: MagicMock()}
        proxy_server.am_i_owner.return_value = False
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.ensure_output_profile.return_value = True
        mock_proxy_cls.get_instance.return_value = proxy_server

        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(
            self.factory.get(f"/proxy/ts/stream/{self.channel_id}/"),
            self.channel_id,
        )

        self.assertIsInstance(response, StreamingHttpResponse)
        proxy_server.try_acquire_ownership.assert_called_once_with(self.channel_id)
        mock_generate_url.assert_not_called()
        mock_channel_service.initialize_channel.assert_not_called()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_owner_reserves_stream_after_acquiring_ownership(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        channel.get_stream_profile.return_value.is_redirect.return_value = False
        mock_get_stream_object.return_value = channel

        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False
        mock_channel_service.initialize_channel.return_value = True
        mock_generate_url.return_value = (
            "http://upstream/stream.ts", "UA", False, "profile", True, None,
        )

        proxy_server = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.redis_client.get.return_value = None
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.try_acquire_ownership.return_value = True
        _configure_init_lock_mocks(proxy_server)
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: MagicMock()}
        proxy_server.am_i_owner.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.ensure_output_profile.return_value = True
        mock_proxy_cls.get_instance.return_value = proxy_server

        # After ownership, setup-needed re-check still sees a cold channel
        with patch(
            "apps.proxy.live_proxy.views._channel_setup_needed",
            return_value=(True, None, False),
        ):
            mock_create_generator.return_value = lambda: iter([b"chunk"])
            from apps.proxy.live_proxy.views import stream_ts

            response = stream_ts(
                self.factory.get(f"/proxy/ts/stream/{self.channel_id}/"),
                self.channel_id,
            )

        self.assertIsInstance(response, StreamingHttpResponse)
        proxy_server.try_acquire_ownership.assert_called_once_with(self.channel_id)
        mock_generate_url.assert_called()
        mock_channel_service.initialize_channel.assert_called_once()
        # Ownership was transferred to the channel lifecycle, not released as a failed init
        proxy_server.release_ownership.assert_not_called()
        self.assertNotIn(self.channel_id, proxy_server._channels_setting_up)

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_same_worker_follower_skips_when_setting_up(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        """Second client on the same worker must not reserve another profile slot."""
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        channel.get_stream_profile.return_value.is_redirect.return_value = False
        mock_get_stream_object.return_value = channel
        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False

        proxy_server = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.check_if_channel_exists.return_value = False
        _configure_init_lock_mocks(proxy_server)
        # Owner already claimed setup on this worker
        proxy_server._channels_setting_up.add(self.channel_id)
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: MagicMock()}
        proxy_server.am_i_owner.return_value = False
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.ensure_output_profile.return_value = True
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        with patch(
            "apps.proxy.live_proxy.views._channel_setup_needed",
            return_value=(True, None, False),
        ):
            response = stream_ts(
                self.factory.get(f"/proxy/ts/stream/{self.channel_id}/"),
                self.channel_id,
            )

        self.assertIsInstance(response, StreamingHttpResponse)
        proxy_server.try_acquire_ownership.assert_not_called()
        mock_generate_url.assert_not_called()
        mock_channel_service.initialize_channel.assert_not_called()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_claim_lock_released_before_stream_url_fetch(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        """Followers must not block on generate_stream_url; claim lock ends first."""
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        channel.get_stream_profile.return_value.is_redirect.return_value = False
        mock_get_stream_object.return_value = channel
        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False
        mock_channel_service.initialize_channel.return_value = True

        call_order = []

        def _generate(*_args, **_kwargs):
            call_order.append("generate_stream_url")
            return ("http://upstream/stream.ts", "UA", False, "profile", True, None)

        mock_generate_url.side_effect = _generate

        proxy_server = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.redis_client.get.return_value = None
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.try_acquire_ownership.return_value = True
        lock = _configure_init_lock_mocks(proxy_server)

        def _finish(_channel_id, held_lock):
            call_order.append("finish_init_lock")
            held_lock.release()

        proxy_server._finish_channel_init_lock.side_effect = _finish
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: MagicMock()}
        proxy_server.am_i_owner.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.ensure_output_profile.return_value = True
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        with patch(
            "apps.proxy.live_proxy.views._channel_setup_needed",
            return_value=(True, None, False),
        ):
            from apps.proxy.live_proxy.views import stream_ts

            response = stream_ts(
                self.factory.get(f"/proxy/ts/stream/{self.channel_id}/"),
                self.channel_id,
            )

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertEqual(call_order[0], "finish_init_lock")
        self.assertIn("generate_stream_url", call_order)
        self.assertLess(
            call_order.index("finish_init_lock"),
            call_order.index("generate_stream_url"),
        )
        self.assertFalse(lock.locked())

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_owner_init_failure_clears_setting_up_and_releases_ownership(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        """If init fails after claim, do not leave setting_up or ownership behind."""
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        channel.get_stream_profile.return_value.is_redirect.return_value = False
        channel.release_stream.return_value = True
        mock_get_stream_object.return_value = channel
        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False
        mock_channel_service.initialize_channel.return_value = False
        mock_generate_url.return_value = (
            "http://upstream/stream.ts", "UA", False, "profile", True, None,
        )

        proxy_server = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.redis_client.get.return_value = None
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.try_acquire_ownership.return_value = True
        _configure_init_lock_mocks(proxy_server)
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: MagicMock()}
        proxy_server.am_i_owner.return_value = True
        mock_proxy_cls.get_instance.return_value = proxy_server

        with patch(
            "apps.proxy.live_proxy.views._channel_setup_needed",
            return_value=(True, None, False),
        ):
            from apps.proxy.live_proxy.views import stream_ts
            from django.http import JsonResponse

            response = stream_ts(
                self.factory.get(f"/proxy/ts/stream/{self.channel_id}/"),
                self.channel_id,
            )

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(self.channel_id, proxy_server._channels_setting_up)
        proxy_server.release_ownership.assert_called_once_with(
            self.channel_id, signal_stopping=False
        )
        mock_create_generator.assert_not_called()
