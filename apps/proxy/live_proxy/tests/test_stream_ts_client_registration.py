"""Regression tests for stream_ts client registration ordering."""

from unittest.mock import MagicMock, patch

from django.http import JsonResponse, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase


class StreamTsClientRegistrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"

    def _channel(self, *, redirect=False):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        stream_profile = MagicMock()
        stream_profile.is_redirect.return_value = redirect
        channel.get_stream_profile.return_value = stream_profile
        return channel

    def _active_proxy_server(self, *, am_i_owner=False, client_manager=None):
        client_manager = client_manager or MagicMock()
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hgetall.return_value = {"state": "active"}
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: client_manager}
        proxy_server.check_if_channel_exists.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.am_i_owner.return_value = am_i_owner
        proxy_server.ensure_output_profile.return_value = True
        return proxy_server, client_manager

    def _request(self):
        request = self.factory.get(f"/proxy/ts/stream/{self.channel_id}/")
        request.user = MagicMock(is_authenticated=False)
        return request

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_active_channel_registers_client_before_ensure_output_profile(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_resolve_output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        profile = MagicMock()
        profile.id = 2
        profile.build_command.return_value = ["ffmpeg"]
        mock_resolve_output_profile.return_value = profile

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)
        call_order = []

        def _add_client(*_args, **_kwargs):
            call_order.append("add_client")
            return 1

        def _ensure_output_profile(*_args, **_kwargs):
            call_order.append("ensure_output_profile")
            return True

        client_manager.add_client.side_effect = _add_client
        proxy_server.ensure_output_profile.side_effect = _ensure_output_profile
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertEqual(call_order, ["add_client", "ensure_output_profile"])

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_active_channel_without_client_manager_returns_503(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        proxy_server, _client_manager = self._active_proxy_server()
        proxy_server.client_managers = {}
        proxy_server.initialize_channel.return_value = True
        proxy_server.redis_client.hmget.return_value = (
            b"http://example/stream",
            b"stream-ua",
            b"None",
        )
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 503)
        proxy_server.ensure_output_profile.assert_not_called()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_ensure_output_profile_failure_removes_registered_client(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_resolve_output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        profile = MagicMock()
        profile.id = 2
        profile.build_command.return_value = ["ffmpeg"]
        mock_resolve_output_profile.return_value = profile

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)
        proxy_server.ensure_output_profile.return_value = False
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 500)
        client_manager.add_client.assert_called_once()
        client_manager.remove_client.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_unhandled_exception_after_registration_removes_client(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_resolve_output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        """A crash between pre-registration and the streaming response (e.g. a
        Redis error inside ensure_output_profile/get_buffer) must not leave a
        phantom client registered - the generic exception handler has to undo
        the earlier add_client() call."""
        profile = MagicMock()
        profile.id = 2
        profile.build_command.return_value = ["ffmpeg"]
        mock_resolve_output_profile.return_value = profile

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)
        proxy_server.ensure_output_profile.side_effect = RuntimeError("redis down")
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 500)
        client_manager.add_client.assert_called_once()
        client_manager.remove_client.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_client_manager_removed_after_registration_cleans_up(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)

        def _pop_manager_after_register(*_args, **_kwargs):
            proxy_server.client_managers.pop(self.channel_id, None)
            return 1

        client_manager.add_client.side_effect = _pop_manager_after_register
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 503)
        client_manager.remove_client.assert_not_called()
        proxy_server.redis_client.srem.assert_called_once()
        proxy_server.redis_client.delete.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService.initialize_channel", return_value=True)
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_owner_init_resolves_output_profile_once(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_resolve_output_profile,
        mock_resolve_output_format,
        _mock_initialize,
        mock_generate_stream_url,
        mock_create_generator,
        _mock_close,
    ):
        mock_generate_stream_url.return_value = (
            "http://example/stream",
            "ua",
            False,
            "None",
            True,
            None,
        )

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=True)
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.get.return_value = None
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        mock_resolve_output_profile.assert_called_once()
        mock_resolve_output_format.assert_called_once()
        client_manager.add_client.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_existing_db_cleanup_test_still_registers_client(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        proxy_server, client_manager = self._active_proxy_server()
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        client_manager.add_client.assert_called_once()
        mock_create_generator.assert_called_once()
