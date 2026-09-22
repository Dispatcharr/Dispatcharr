"""HEAD probes for live streams should report format without opening a stream."""

from unittest.mock import MagicMock, patch

from django.http import Http404
from django.test import RequestFactory, SimpleTestCase


class LiveStreamHeadProbeTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, query=""):
        request = self.factory.head(f"/proxy/ts/stream/channel-uuid{query}")
        request.user = MagicMock(is_authenticated=False)
        return request

    def _channel(self, redirect=False):
        channel = MagicMock()
        channel.get_stream_profile.return_value.is_redirect.return_value = redirect
        return channel

    @patch("apps.proxy.live_proxy.views.ProxyServer.get_instance")
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    def test_head_reports_mpegts_without_opening_stream(
        self,
        _network_ok,
        mock_get_stream_object,
        _resolve_output_format,
        mock_generate_stream_url,
        mock_proxy_get_instance,
    ):
        mock_get_stream_object.return_value = self._channel()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), "channel-uuid")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp2t")
        self.assertIn("HEAD", response["Allow"])
        mock_generate_stream_url.assert_not_called()
        mock_proxy_get_instance.assert_not_called()

    @patch("apps.proxy.live_proxy.views.ProxyServer.get_instance")
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="fmp4")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    def test_head_reports_fmp4_without_opening_stream(
        self,
        _network_ok,
        mock_get_stream_object,
        _resolve_output_format,
        mock_generate_stream_url,
        mock_proxy_get_instance,
    ):
        mock_get_stream_object.return_value = self._channel()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(
            self._request("?output_format=fmp4"),
            "channel-uuid",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp4")
        mock_generate_stream_url.assert_not_called()
        mock_proxy_get_instance.assert_not_called()

    @patch("apps.proxy.live_proxy.views.ProxyServer.get_instance")
    @patch("apps.proxy.live_proxy.views._resolve_output_format")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    def test_head_does_not_guess_redirect_container(
        self,
        _network_ok,
        mock_get_stream_object,
        mock_resolve_output_format,
        mock_proxy_get_instance,
    ):
        mock_get_stream_object.return_value = self._channel(redirect=True)

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), "channel-uuid")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        mock_resolve_output_format.assert_not_called()
        mock_proxy_get_instance.assert_not_called()

    @patch(
        "apps.proxy.live_proxy.views.get_stream_object",
        side_effect=Http404("missing"),
    )
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    def test_head_preserves_missing_channel_response(
        self,
        _network_ok,
        _get_stream_object,
    ):
        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), "missing")

        self.assertEqual(response.status_code, 404)
