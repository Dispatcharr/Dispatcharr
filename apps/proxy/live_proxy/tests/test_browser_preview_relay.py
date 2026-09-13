"""
Redirect-mode channels relay the stream server-side for admin-UI browser
previews (?preview=1) instead of redirecting, since a browser's embedded
preview player can't follow a Redirect-mode hop directly (mixed-content or
CORS, depending on deployment). Real players never send this marker and
must continue to get the normal redirect, completely unaffected.

See apps/proxy/live_proxy/views.py: _relay_preview_stream() and the
is_preview_request checks in stream_ts().
"""

from unittest.mock import MagicMock, patch

from django.http import HttpResponseRedirect, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase


class StreamTsBrowserPreviewTests(SimpleTestCase):
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

    def _request(self, preview=False):
        path = f"/proxy/ts/stream/{self.channel_id}/"
        params = {"preview": "1"} if preview else {}
        return self.factory.get(path, params)

    def _admin_user(self):
        # `stream_ts()` is wrapped by DRF's @api_view, which replaces
        # request.user with its own authenticated-via-DRF property —
        # setting request.user directly on the raw factory request has
        # no effect once DRF wraps it. Passing `user=` explicitly to
        # stream_ts() bypasses that entirely (see: `if user is None and
        # hasattr(request, "user")...` in stream_ts()).
        return MagicMock(is_authenticated=True, is_staff=True, user_level=10, stream_limit=0)

    def _mock_upstream_response(self, chunks=(b"data-1", b"data-2")):
        """A fake `requests.get(..., stream=True)` response."""
        upstream = MagicMock()
        upstream.raise_for_status.return_value = None
        upstream.headers = {"Content-Type": "video/mp2t"}
        upstream.iter_content.return_value = iter(chunks)
        upstream.close.return_value = None
        return upstream

    # --- Preview requests are relayed, not redirected ---

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.requests.get")
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
    def test_preview_request_relays_instead_of_redirecting(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        mock_validate_stream_url,
        mock_requests_get,
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
        mock_requests_get.return_value = self._mock_upstream_response()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(
            self._request(preview=True), self.channel_id, user=self._admin_user()
        )

        # Relayed, not redirected: the browser only ever talks to our own
        # origin, which is the whole point of the fix.
        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertNotIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response.get("Content-Type"), "video/mp2t")
        self.assertEqual(b"".join(response.streaming_content), b"data-1data-2")

        # The provider is still hit with the correct URL and stream UA.
        mock_requests_get.assert_called_once()
        called_args, called_kwargs = mock_requests_get.call_args
        self.assertEqual(called_args[0], self.provider_url)
        self.assertEqual(called_kwargs["headers"], {"User-Agent": "ua"})
        self.assertTrue(called_kwargs["stream"])

        # No dangling connection slot: same cleanup as a normal redirect.
        channel.release_stream.assert_called_once()
        # Validation is still skipped when the setting is off, same as a
        # real player's request would be.
        mock_validate_stream_url.assert_not_called()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.requests.get")
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
    def test_preview_request_relays_validated_url(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        mock_validate_stream_url,
        mock_requests_get,
        _mock_close,
    ):
        """Same as above, but with Validate Redirect URLs turned on — the
        other of the two return points that needed the preview check."""
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
        mock_requests_get.return_value = self._mock_upstream_response()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(
            self._request(preview=True), self.channel_id, user=self._admin_user()
        )

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertNotIsInstance(response, HttpResponseRedirect)
        mock_validate_stream_url.assert_called_once()
        mock_requests_get.assert_called_once()
        self.assertEqual(mock_requests_get.call_args[0][0], self.provider_url)
        channel.release_stream.assert_called_once()

    # --- Real players are completely unaffected ---

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.requests.get")
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
    def test_non_preview_request_still_redirects_normally(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        mock_validate_stream_url,
        mock_requests_get,
        _mock_close,
    ):
        """A request with no `preview` param — i.e. every real player,
        which never sends this marker — must be completely unaffected by
        this fix and keep getting the plain redirect it always got."""
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

        response = stream_ts(self._request(preview=False), self.channel_id)

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response.url, self.provider_url)
        mock_requests_get.assert_not_called()
        channel.release_stream.assert_called_once()

    # --- Provider failures during relay surface loudly, never silently ---

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.requests.get")
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
    def test_preview_relay_failure_returns_error_not_silent_fallback(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        mock_validate_stream_url,
        mock_requests_get,
        _mock_close,
    ):
        import requests as requests_module

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

        failing_upstream = MagicMock()
        failing_upstream.raise_for_status.side_effect = (
            requests_module.exceptions.HTTPError("403 Client Error")
        )
        failing_upstream.close.return_value = None
        mock_requests_get.return_value = failing_upstream

        from apps.proxy.live_proxy.views import stream_ts
        from django.http import JsonResponse

        response = stream_ts(
            self._request(preview=True), self.channel_id, user=self._admin_user()
        )

        # The outer exception handler in stream_ts() catches this exactly
        # like any other failure in the function: logs it and returns a
        # real 500, rather than serving an empty/broken stream silently.
        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 500)
        failing_upstream.close.assert_called_once()
