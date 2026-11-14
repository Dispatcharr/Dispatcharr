"""HEAD probes on live stream URLs report the container without opening a stream."""

from unittest.mock import MagicMock, patch

from django.http import Http404, JsonResponse
from django.test import RequestFactory, SimpleTestCase

from apps.accounts.models import User


@patch("apps.proxy.live_proxy.views.close_old_connections")
@patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
@patch("apps.proxy.live_proxy.views.ProxyServer")
class LiveStreamHeadProbeTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, query="", *, user=None):
        request = self.factory.head(f"/proxy/ts/stream/channel-uuid{query}")
        if user is None:
            request.user = MagicMock(is_authenticated=False)
        else:
            request.user = user
        return request

    def _channel(self, *, redirect=False):
        channel = MagicMock()
        channel.get_stream_profile.return_value.is_redirect.return_value = redirect
        return channel

    def _assert_no_stream_started(self, mock_proxy_cls):
        mock_proxy_cls.get_instance.assert_not_called()

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
    def test_head_reports_hls(self, mock_get_stream_object, mock_proxy_cls, *_):
        mock_get_stream_object.return_value = self._channel()

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request("?output_format=hls"), "channel-uuid")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.apple.mpegurl")
        self._assert_no_stream_started(mock_proxy_cls)

    @patch("apps.proxy.live_proxy.views._resolve_output_format")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    def test_head_unknown_format_falls_back_to_mpegts(
        self, mock_get_stream_object, mock_resolve_output_format, mock_proxy_cls, *_
    ):
        mock_get_stream_object.return_value = self._channel()
        mock_resolve_output_format.return_value = "not-a-real-format"

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), "channel-uuid")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp2t")
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

    @patch("apps.proxy.live_proxy.views.get_stream_object")
    def test_head_skip_redirect_reports_proxied_format(
        self, mock_get_stream_object, mock_proxy_cls, *_
    ):
        mock_get_stream_object.return_value = self._channel(redirect=True)
        user = MagicMock()
        user.is_authenticated = True
        user.user_level = User.UserLevel.STANDARD

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(
            self._request("?skip_redirect=true&output_format=fmp4", user=user),
            "channel-uuid",
            user=user,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp4")
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


@patch("apps.proxy.live_proxy.views.close_old_connections")
@patch("apps.proxy.live_proxy.views.ProxyServer")
class XcLiveHeadProbeTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _channel(self, *, redirect=False):
        channel = MagicMock()
        channel.uuid = "channel-uuid"
        channel.get_stream_profile.return_value.is_redirect.return_value = redirect
        return channel

    def _user(self):
        user = MagicMock()
        user.is_authenticated = True
        user.custom_properties = {}
        return user

    def _assert_no_stream_started(self, mock_proxy_cls):
        mock_proxy_cls.get_instance.assert_not_called()

    def _head(self, channel_id, *, redirect=False, auth_error=None):
        from apps.proxy.live_proxy.views import stream_xc

        channel = self._channel(redirect=redirect)
        if auth_error is not None:
            auth_result = (None, None, auth_error)
        else:
            auth_result = (self._user(), channel, None)
        request = self.factory.head(f"/live/alice/secret/{channel_id}")
        with patch(
            "apps.proxy.live_proxy.views._xc_live_channel_or_error",
            return_value=auth_result,
        ), patch(
            "apps.proxy.live_proxy.views.get_stream_object",
            return_value=channel,
        ) as mock_get_stream_object:
            response = stream_xc(request, "alice", "secret", channel_id)
        return response, mock_get_stream_object

    def test_head_ts_reports_mpegts(self, mock_proxy_cls, *_):
        response, _get_stream = self._head("5.ts")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp2t")
        self._assert_no_stream_started(mock_proxy_cls)

    def test_head_mp4_reports_fmp4(self, mock_proxy_cls, *_):
        response, _get_stream = self._head("5.mp4")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp4")
        self._assert_no_stream_started(mock_proxy_cls)

    def test_head_m3u8_reports_hls(self, mock_proxy_cls, *_):
        response, _get_stream = self._head("5.m3u8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.apple.mpegurl")
        self._assert_no_stream_started(mock_proxy_cls)

    @patch(
        "apps.proxy.live_proxy.views.CoreSettings.get_default_output_format",
        return_value="mpegts",
    )
    def test_head_without_extension_uses_default_format(self, _default, mock_proxy_cls, *_):
        response, _get_stream = self._head("5")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp2t")
        self._assert_no_stream_started(mock_proxy_cls)

    def test_head_redirect_profile_stays_octet_stream(self, mock_proxy_cls, *_):
        response, _get_stream = self._head("5.ts", redirect=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self._assert_no_stream_started(mock_proxy_cls)

    def test_head_auth_failure_does_not_open_stream(self, mock_proxy_cls, *_):
        response, get_stream = self._head(
            "5.ts",
            auth_error=JsonResponse({"error": "Unauthorized"}, status=401),
        )

        self.assertEqual(response.status_code, 401)
        get_stream.assert_not_called()
        mock_proxy_cls.get_instance.assert_not_called()
