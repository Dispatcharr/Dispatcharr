"""Live proxy must release geventpool checkouts after ORM on stream and URL paths."""

from unittest.mock import MagicMock, patch

from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase


class StreamTsDbCleanupTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _active_proxy(self, client_manager=None):
        client_manager = client_manager or MagicMock()
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hgetall.return_value = {"state": "active"}
        proxy_server.stream_buffers = {"channel-uuid": MagicMock()}
        proxy_server.client_managers = {"channel-uuid": client_manager}
        proxy_server.check_if_channel_exists.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        return proxy_server, client_manager

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients", return_value=False)
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_stream_ts_closes_db_before_streaming_response(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        mock_create_generator,
        mock_close,
    ):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = "channel-uuid"
        channel.name = "Test Channel"
        mock_get_stream_object.return_value = channel

        proxy_server, client_manager = self._active_proxy()
        mock_proxy_cls.get_instance.return_value = proxy_server

        def _generate():
            yield b"chunk"

        mock_create_generator.return_value = lambda: _generate()

        request = self.factory.get("/proxy/live/channel-uuid/")
        request.user = MagicMock(is_authenticated=False)

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(request, "channel-uuid")

        self.assertIsInstance(response, StreamingHttpResponse)
        client_manager.add_client.assert_called_once()
        mock_close.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator", side_effect=RuntimeError("orm blew up"))
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients", return_value=False)
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_stream_ts_closes_db_on_exception(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        _create_generator,
        mock_close,
    ):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = "channel-uuid"
        channel.name = "Test Channel"
        mock_get_stream_object.return_value = channel

        proxy_server, _ = self._active_proxy()
        mock_proxy_cls.get_instance.return_value = proxy_server

        request = self.factory.get("/proxy/live/channel-uuid/")
        request.user = MagicMock(is_authenticated=False)

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(request, "channel-uuid")

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 500)
        mock_close.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients", return_value=False)
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_stream_ts_closes_db_on_early_client_register_failure(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        _create_generator,
        mock_close,
    ):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = "channel-uuid"
        channel.name = "Test Channel"
        mock_get_stream_object.return_value = channel

        client_manager = MagicMock()
        client_manager.add_client.return_value = False
        proxy_server, _ = self._active_proxy(client_manager=client_manager)
        mock_proxy_cls.get_instance.return_value = proxy_server

        request = self.factory.get("/proxy/live/channel-uuid/")
        request.user = MagicMock(is_authenticated=False)

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(request, "channel-uuid")

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 503)
        mock_close.assert_called_once()


class UrlUtilsDbCleanupTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("apps.proxy.live_proxy.url_utils.get_stream_object")
    def test_generate_stream_url_closes_db(self, mock_get_object, mock_close):
        channel = MagicMock()
        channel.get_stream.return_value = (None, None, "no streams", False)
        mock_get_object.return_value = channel

        from apps.proxy.live_proxy.url_utils import generate_stream_url

        result = generate_stream_url("channel-uuid")

        self.assertIsNone(result[0])
        mock_close.assert_called_once()

    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("apps.proxy.live_proxy.url_utils.get_stream_object")
    def test_get_alternate_streams_closes_db(self, mock_get_object, mock_close):
        channel = MagicMock()
        channel.streams.all.return_value.order_by.return_value.exists.return_value = False
        mock_get_object.return_value = channel

        from apps.proxy.live_proxy.url_utils import get_alternate_streams

        result = get_alternate_streams("channel-uuid", current_stream_id=1)

        self.assertEqual(result, [])
        mock_close.assert_called_once()

    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("apps.proxy.live_proxy.url_utils.get_object_or_404")
    def test_get_stream_info_for_switch_closes_db_on_error(self, mock_get_404, mock_close):
        mock_get_404.side_effect = RuntimeError("db error")

        from apps.proxy.live_proxy.url_utils import get_stream_info_for_switch

        result = get_stream_info_for_switch("channel-uuid", target_stream_id=99)

        self.assertIn("error", result)
        mock_close.assert_called_once()

    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("apps.proxy.live_proxy.url_utils.M3UAccountProfile.objects.get")
    def test_get_connections_left_closes_db(self, mock_get, mock_close):
        mock_get.side_effect = Exception("not found")

        from apps.proxy.live_proxy.url_utils import get_connections_left

        result = get_connections_left(999)

        self.assertEqual(result, 0)
        mock_close.assert_called_once()


class TsGeneratorDbCleanupTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.output.ts.generator.close_old_connections")
    @patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer.get_instance")
    def test_ts_cleanup_closes_db(self, mock_proxy_cls, mock_close):
        proxy_server = MagicMock()
        proxy_server.redis_client = None
        proxy_server.client_managers = {}
        mock_proxy_cls.return_value = proxy_server

        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator

        gen = StreamGenerator.__new__(StreamGenerator)
        gen.channel_id = "channel-uuid"
        gen.client_id = "client-1"
        gen.stream_start_time = 0
        gen.channel_name = "Test"
        gen.client_ip = "127.0.0.1"
        gen.client_user_agent = "agent"
        gen.bytes_sent = 0
        gen.user = None

        gen._cleanup()

        mock_close.assert_called_once()


class InitializeChannelDbCleanupTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.services.channel_service.close_old_connections")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer")
    def test_channel_service_initialize_closes_db_on_failure(self, mock_proxy_cls, mock_close):
        proxy_server = MagicMock()
        proxy_server.redis_client = None
        proxy_server.initialize_channel.return_value = False
        mock_proxy_cls.get_instance.return_value = proxy_server

        from apps.proxy.live_proxy.services.channel_service import ChannelService

        result = ChannelService.initialize_channel(
            "channel-uuid",
            "http://example.com/stream.ts",
            "ua",
        )

        self.assertFalse(result)
        mock_close.assert_called_once()

    @patch("apps.proxy.live_proxy.server.close_old_connections")
    @patch("apps.proxy.live_proxy.server.StreamManager", side_effect=RuntimeError("manager init failed"))
    def test_proxy_server_initialize_closes_db_on_stream_manager_failure(
        self, _stream_manager, mock_close
    ):
        from apps.proxy.live_proxy.server import ProxyServer

        proxy = ProxyServer.__new__(ProxyServer)
        proxy.redis_client = MagicMock()
        proxy.redis_client.exists.return_value = False
        proxy.redis_client.hgetall.return_value = {}
        proxy.redis_client.hget.return_value = "initializing"
        proxy.stream_buffers = {}
        proxy.client_managers = {}
        proxy.stream_managers = {}
        proxy._live_stream_managers = {}
        proxy._channel_names = {}
        proxy.worker_id = "worker-1"
        proxy._channel_unavailable_for_new_clients = MagicMock(return_value=False)
        proxy._has_local_upstream_activity = MagicMock(return_value=False)
        proxy.get_channel_owner = MagicMock(return_value=None)
        proxy.try_acquire_ownership = MagicMock(return_value=True)
        proxy.release_ownership = MagicMock()
        proxy.am_i_owner = MagicMock(return_value=True)
        proxy.update_channel_state = MagicMock()
        proxy._stop_local_stream_activity = MagicMock()
        proxy._clean_redis_keys = MagicMock()
        proxy._local_stop_locks = {}
        proxy._channel_init_locks = {}
        proxy._channels_setting_up = set()
        proxy._stopping_channels = set()

        with patch("apps.proxy.live_proxy.server.StreamBuffer"), patch(
            "apps.proxy.live_proxy.server.RedisClient"
        ):
            result = proxy.initialize_channel(
                "http://example.com/stream.ts",
                "channel-uuid",
                user_agent="ua",
                stream_id=1,
            )

        self.assertFalse(result)
        proxy.release_ownership.assert_called_once_with(
            "channel-uuid", signal_stopping=False
        )
        proxy._clean_redis_keys.assert_called_once_with("channel-uuid")
        self.assertGreaterEqual(mock_close.call_count, 1)


class StreamManagerDbCleanupTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.input.manager.Channel.objects")
    def test_stream_manager_init_uses_passed_name_without_orm(self, mock_channel_objects):
        from apps.proxy.live_proxy.input.manager import StreamManager

        buffer = MagicMock()
        buffer.redis_client = None
        buffer.channel_id = "channel-uuid"

        manager = StreamManager.__new__(StreamManager)
        StreamManager.__init__(
            manager,
            "channel-uuid",
            "http://example.com/stream.ts",
            buffer,
            user_agent="ua",
            channel_name="Test Channel",
        )

        self.assertEqual(manager.channel_name, "Test Channel")
        mock_channel_objects.filter.assert_not_called()

    @patch("apps.proxy.live_proxy.input.manager.close_old_connections")
    def test_read_stderr_closes_db_on_exit(self, mock_close):
        from apps.proxy.live_proxy.input.manager import StreamManager

        manager = StreamManager.__new__(StreamManager)
        manager.channel_id = "channel-uuid"
        manager.running = True
        manager.transcode_process = MagicMock()
        manager.transcode_process.stderr = None

        manager._read_stderr()

        mock_close.assert_called_once()


class GeneratorAndStatusDbCleanupTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("apps.proxy.live_proxy.output.ts.generator.Channel.objects")
    def test_ts_generator_init_uses_passed_name_without_orm(self, mock_channel_objects):
        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator

        gen = StreamGenerator(
            "channel-uuid",
            "client-1",
            "127.0.0.1",
            "agent",
            channel_name="CNN",
        )

        self.assertEqual(gen.channel_name, "CNN")
        mock_channel_objects.filter.assert_not_called()

    @patch("apps.proxy.live_proxy.channel_status.close_old_connections")
    @patch("apps.proxy.live_proxy.channel_status.ProxyServer")
    def test_detailed_channel_info_closes_db(self, mock_proxy_cls, mock_close):
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.hgetall.return_value = {
            "state": "active",
            "stream_id": "7",
            "stream_name": "Backup Feed",
            "m3u_profile": "3",
        }
        proxy_server.redis_client.get.return_value = "1"
        mock_proxy_cls.get_instance.return_value = proxy_server

        from apps.proxy.live_proxy.channel_status import ChannelStatus

        with patch(
            "apps.m3u.models.M3UAccountProfile.objects.filter"
        ) as mock_profile_filter:
            mock_profile_filter.return_value.first.return_value = MagicMock(name="Profile A")
            info = ChannelStatus.get_detailed_channel_info("channel-uuid")

        self.assertEqual(info["stream_name"], "Backup Feed")
        mock_close.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.get_stream_object", side_effect=Http404("missing"))
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_stream_ts_closes_db_on_http404(
        self,
        mock_proxy_cls,
        _network_ok,
        _get_stream_object,
        mock_close,
    ):
        mock_proxy_cls.get_instance.return_value = MagicMock()
        request = self.factory.get("/proxy/live/missing/")
        request.user = MagicMock(is_authenticated=False)

        from apps.proxy.live_proxy.views import stream_ts

        # @api_view converts Http404 into a 404 response; finally still releases.
        response = stream_ts(request, "missing")

        self.assertEqual(response.status_code, 404)
        mock_close.assert_called_once()
