"""Redirect mode honors proxy_settings.validate_redirect_urls."""

from unittest.mock import MagicMock, patch

from django.http import HttpResponseRedirect
from django.test import RequestFactory, SimpleTestCase


class StreamTsRedirectValidationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"
        self.provider_url = "http://provider.example/live/1"

    def _channel(self):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        stream_profile = MagicMock()
        stream_profile.is_redirect.return_value = True
        channel.get_stream_profile.return_value = stream_profile
        channel.release_stream.return_value = True
        return channel

    def _proxy_server(self):
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.get.return_value = None
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.stream_buffers = {}
        proxy_server.client_managers = {}
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.try_acquire_ownership.return_value = True
        proxy_server._channels_setting_up = set()
        import gevent.lock

        lock = gevent.lock.RLock()
        proxy_server._get_channel_init_lock.return_value = lock
        proxy_server._finish_channel_init_lock.side_effect = (
            lambda _cid, held: held.release()
        )
        proxy_server._clear_channel_setting_up.side_effect = (
            lambda cid: proxy_server._channels_setting_up.discard(cid)
        )
        return proxy_server

    def _request(self):
        request = self.factory.get(f"/proxy/ts/stream/{self.channel_id}/")
        request.user = MagicMock(is_authenticated=False)
        return request

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.url_utils.validate_stream_url")
    @patch("apps.proxy.config.TSConfig.get_validate_redirect_urls", return_value=False)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_skips_validation_when_setting_disabled(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        mock_validate_stream_url,
        _mock_close,
    ):
        mock_generate_stream_url.return_value = (
            self.provider_url,
            "ua",
            False,
            "None",
            True,
            None,
            42,
        )
        channel = self._channel()
        mock_get_stream_object.return_value = channel
        mock_proxy_cls.get_instance.return_value = self._proxy_server()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response.url, self.provider_url)
        mock_validate_stream_url.assert_not_called()
        channel.release_stream.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch(
        "apps.proxy.live_proxy.url_utils.validate_stream_url",
        return_value=(True, "http://provider.example/live/1", 200, "Valid (HEAD request)"),
    )
    @patch("apps.proxy.config.TSConfig.get_validate_redirect_urls", return_value=True)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_validates_when_setting_enabled(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        mock_validate_stream_url,
        _mock_close,
    ):
        mock_generate_stream_url.return_value = (
            self.provider_url,
            "ua",
            False,
            "None",
            True,
            None,
            42,
        )
        channel = self._channel()
        mock_get_stream_object.return_value = channel
        mock_proxy_cls.get_instance.return_value = self._proxy_server()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response.url, self.provider_url)
        mock_validate_stream_url.assert_called_once()
        channel.release_stream.assert_called_once()
