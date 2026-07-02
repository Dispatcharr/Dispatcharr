"""Live proxy must release geventpool checkouts after ORM on stream and URL paths."""

from unittest.mock import MagicMock, patch

from django.http import StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase


class StreamTsDbCleanupTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

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

        client_manager = MagicMock()
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hgetall.return_value = {"state": "active"}
        proxy_server.stream_buffers = {"channel-uuid": MagicMock()}
        proxy_server.client_managers = {"channel-uuid": client_manager}
        proxy_server.check_if_channel_exists.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        mock_proxy_cls.get_instance.return_value = proxy_server

        def _generate():
            yield b"chunk"

        mock_create_generator.return_value = lambda: _generate()

        request = self.factory.get("/proxy/live/channel-uuid/")
        request.user = MagicMock(is_authenticated=False)

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(request, "channel-uuid")

        self.assertIsInstance(response, StreamingHttpResponse)
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
