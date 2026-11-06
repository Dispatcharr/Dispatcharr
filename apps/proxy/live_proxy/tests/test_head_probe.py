"""HEAD probes on live stream URLs report the container without opening a stream."""

from unittest.mock import MagicMock, patch

from django.http import Http404
from django.test import RequestFactory, SimpleTestCase


@patch("apps.proxy.live_proxy.views.close_old_connections")
@patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
@patch("apps.proxy.live_proxy.views.ProxyServer")
class LiveStreamHeadProbeTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, query=""):
        request = self.factory.head(f"/proxy/ts/stream/channel-uuid{query}")
        request.user = MagicMock(is_authenticated=False)
        return request

    def _channel(self, *, redirect=False):
        channel = MagicMock()
        channel.get_stream_profile.return_value.is_redirect.return_value = redirect
        return channel

    def _assert_no_stream_started(self, mock_proxy_cls):
        self.assertEqual(mock_proxy_cls.get_instance.return_value.method_calls, [])

    @patch("apps.proxy.live_proxy.views.get_stream_object")
    def test_head_reports_mpegts(self, mock_get_stream_object, mock_proxy_cls, *_):
        mock_get_stream_object.return_value = self._channel()

        from apps.proxy.live_proxy.views import stream_ts

        with patch(
            "apps.proxy.live_proxy.views.CoreSettings.get_default_output_format",
            return_value="mpegts",
        ):
            response = stream_ts(self._request(), "channel-uuid")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp2t")
        self._assert_no_stream_started(mock_proxy_cls)

    @patch("apps.proxy.live_proxy.views.get_stream_object")
    def test_head_reports_fmp4(self, mock_get_stream_object, mock_proxy_cls, *_):
        mock_get_stream_object.return_value = self._channel()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request("?output_format=fmp4"), "channel-uuid")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp4")
        self._assert_no_stream_started(mock_proxy_cls)

    @patch("apps.proxy.live_proxy.views.get_stream_object")
    def test_head_does_not_claim_container_for_hls(
        self, mock_get_stream_object, mock_proxy_cls, *_
    ):
        mock_get_stream_object.return_value = self._channel()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request("?output_format=hls"), "channel-uuid")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self._assert_no_stream_started(mock_proxy_cls)

    @patch("apps.proxy.live_proxy.views._resolve_output_format")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    def test_head_does_not_claim_container_for_redirect(
        self, mock_get_stream_object, mock_resolve_output_format, mock_proxy_cls, *_
    ):
        mock_get_stream_object.return_value = self._channel(redirect=True)

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), "channel-uuid")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        mock_resolve_output_format.assert_not_called()
        self._assert_no_stream_started(mock_proxy_cls)

    @patch(
        "apps.proxy.live_proxy.views.get_stream_object",
        side_effect=Http404("missing"),
    )
    def test_head_missing_channel_is_404(self, _get_stream_object, mock_proxy_cls, *_):
        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), "missing")

        self.assertEqual(response.status_code, 404)
        self._assert_no_stream_started(mock_proxy_cls)

    def test_head_respects_network_access(self, _proxy_cls, mock_network_allowed, *_):
        mock_network_allowed.return_value = False

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), "channel-uuid")

        self.assertEqual(response.status_code, 403)
