"""HLS redirects use opaque capability URLs for both native and XC entry points."""

from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve

from apps.proxy.live_proxy.output.hls.session import SESSION_TOKEN_HEADER
from apps.proxy.live_proxy.views import (
    _authenticate_xc_live_user,
    _resolve_xc_live_channel,
    stream_ts,
    stream_xc,
)


CHANNEL_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TOKEN = "opaque-hls-token"


class HlsURLConfTests(SimpleTestCase):
    def test_opaque_playlist_route(self):
        match = resolve(f"/proxy/hls/{TOKEN}/index.m3u8")
        self.assertEqual(match.url_name, "hls_playlist")
        self.assertEqual(match.namespace, "proxy")
        self.assertEqual(match.kwargs, {"token": TOKEN})

    def test_opaque_segment_route(self):
        match = resolve(f"/proxy/hls/{TOKEN}/7.ts")
        self.assertEqual(match.url_name, "hls_segment")
        self.assertEqual(match.kwargs["token"], TOKEN)
        self.assertEqual(match.kwargs["seq"], 7)

    def test_xc_live_entry_still_matches_m3u8(self):
        match = resolve("/live/alice/secret/5.m3u8")
        self.assertEqual(match.url_name, "xc_live_stream_endpoint")

    def test_no_xc_shaped_hls_follow_up_routes(self):
        match = resolve("/live/alice/secret/5/client_1/index.m3u8")
        # Falls through to the React catch-all, not an HLS view.
        self.assertNotEqual(match.url_name, "hls_playlist")
        self.assertNotIn("hls", (match.url_name or ""))


class StreamTsHlsRedirectTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = CHANNEL_UUID

    def _channel(self):
        channel = MagicMock()
        channel.id = 5
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        stream_profile = MagicMock()
        stream_profile.is_redirect.return_value = False
        channel.get_stream_profile.return_value = stream_profile
        return channel

    def _active_proxy_server(self):
        client_manager = MagicMock()
        client_manager.add_client.return_value = 1
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hgetall.return_value = {"state": "active"}
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: client_manager}
        proxy_server.check_if_channel_exists.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.am_i_owner.return_value = False
        proxy_server.ensure_output_format.return_value = True
        proxy_server._channels_setting_up = set()
        return proxy_server

    def _request(self, path=None):
        request = self.factory.get(path or f"/proxy/ts/stream/{self.channel_id}/")
        request.user = MagicMock(is_authenticated=False)
        return request

    @contextmanager
    def _hls_setup(self, mint_token=TOKEN):
        with ExitStack() as stack:
            stack.enter_context(
                patch("apps.proxy.live_proxy.views.close_old_connections")
            )
            stack.enter_context(
                patch(
                    "apps.proxy.live_proxy.views._resolve_output_format",
                    return_value="hls",
                )
            )
            stack.enter_context(
                patch(
                    "apps.proxy.live_proxy.views._resolve_output_profile",
                    return_value=None,
                )
            )
            stack.enter_context(
                patch(
                    "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
                    return_value=False,
                )
            )
            stack.enter_context(
                patch(
                    "apps.proxy.live_proxy.views.get_stream_object",
                    return_value=self._channel(),
                )
            )
            stack.enter_context(
                patch(
                    "apps.proxy.live_proxy.views.network_access_allowed",
                    return_value=True,
                )
            )
            mock_proxy_cls = stack.enter_context(
                patch("apps.proxy.live_proxy.views.ProxyServer")
            )
            proxy = self._active_proxy_server()
            mock_proxy_cls.get_instance.return_value = proxy
            mint = stack.enter_context(
                patch(
                    "apps.proxy.live_proxy.views.mint_hls_session",
                    return_value=mint_token,
                )
            )
            yield proxy, mint

    def test_hls_redirects_to_opaque_token_path(self):
        with self._hls_setup():
            response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response.url, f"/proxy/hls/{TOKEN}/index.m3u8")
        self.assertEqual(response[SESSION_TOKEN_HEADER], TOKEN)
        self.assertEqual(
            response["Access-Control-Expose-Headers"],
            SESSION_TOKEN_HEADER,
        )
        self.assertNotIn(self.channel_id, response.url)
        self.assertNotIn("/live/", response.url)

    def test_hls_mint_passes_authenticated_user_id(self):
        user = MagicMock()
        user.id = 99
        user.is_authenticated = True
        user.stream_limit = 0

        with self._hls_setup() as (_proxy, mint):
            # stream_ts accepts user= for XC/native callers; DRF would
            # otherwise replace RequestFactory.user with AnonymousUser.
            response = stream_ts(self._request(), self.channel_id, user=user)

        self.assertIsInstance(response, HttpResponseRedirect)
        mint.assert_called_once()
        self.assertEqual(mint.call_args.kwargs.get("user_id"), 99)

    def test_hls_mint_passes_none_user_id_when_anonymous(self):
        with self._hls_setup() as (_proxy, mint):
            response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, HttpResponseRedirect)
        mint.assert_called_once()
        self.assertIsNone(mint.call_args.kwargs.get("user_id"))

    def test_mint_failure_returns_500_and_drops_client(self):
        with self._hls_setup(mint_token=None) as (proxy, _mint):
            response = stream_ts(self._request(), self.channel_id)

        self.assertEqual(response.status_code, 500)
        proxy.client_managers[self.channel_id].remove_client.assert_called_once()


class StreamXcHlsRedirectTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _user(self):
        user = MagicMock()
        user.custom_properties = {"xc_password": "secret"}
        user.user_level = 10
        return user

    def _channel(self):
        channel = MagicMock()
        channel.id = 5
        channel.uuid = CHANNEL_UUID
        return channel

    def test_m3u8_forces_hls_without_xc_redirect_base(self):
        user = self._user()
        channel = self._channel()
        request = self.factory.get("/live/alice/secret/5.m3u8")

        with patch("apps.proxy.live_proxy.views.close_old_connections"), patch(
            "apps.proxy.live_proxy.views.stream_ts",
            return_value=HttpResponseRedirect(f"/proxy/hls/{TOKEN}/index.m3u8"),
        ) as mock_stream_ts, patch(
            "apps.proxy.live_proxy.views._xc_live_channel_or_error",
            return_value=(user, channel, None),
        ):
            response = stream_xc(request, "alice", "secret", "5.m3u8")

        mock_stream_ts.assert_called_once()
        args, kwargs = mock_stream_ts.call_args
        self.assertEqual(args[1], CHANNEL_UUID)
        self.assertEqual(kwargs["force_output_format"], "hls")
        self.assertNotIn("hls_redirect_base", kwargs)
        self.assertEqual(response.url, f"/proxy/hls/{TOKEN}/index.m3u8")

    def test_ts_still_forces_mpegts(self):
        user = self._user()
        channel = self._channel()
        request = self.factory.get("/live/alice/secret/5.ts")

        with patch("apps.proxy.live_proxy.views.close_old_connections"), patch(
            "apps.proxy.live_proxy.views.stream_ts",
            return_value=HttpResponse("ok"),
        ) as mock_stream_ts, patch(
            "apps.proxy.live_proxy.views._xc_live_channel_or_error",
            return_value=(user, channel, None),
        ):
            stream_xc(request, "alice", "secret", "5.ts")

        self.assertEqual(mock_stream_ts.call_args.kwargs["force_output_format"], "mpegts")


class XCLiveAuthHelperTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/live/alice/secret/5.m3u8")

    def test_wrong_password_returns_401(self):
        user = MagicMock()
        user.custom_properties = {"xc_password": "secret"}

        with patch(
            "apps.proxy.live_proxy.views.get_object_or_404", return_value=user
        ), patch(
            "apps.proxy.live_proxy.views.network_access_allowed", return_value=True
        ):
            found, error = _authenticate_xc_live_user(
                self.request, "alice", "wrong"
            )

        self.assertIsNone(found)
        self.assertEqual(error.status_code, 401)

    def test_valid_credentials_return_user(self):
        user = MagicMock()
        user.custom_properties = {"xc_password": "secret"}

        with patch(
            "apps.proxy.live_proxy.views.get_object_or_404", return_value=user
        ), patch(
            "apps.proxy.live_proxy.views.network_access_allowed", return_value=True
        ):
            found, error = _authenticate_xc_live_user(
                self.request, "alice", "secret"
            )

        self.assertIs(found, user)
        self.assertIsNone(error)

    def test_invalid_channel_id_returns_404(self):
        user = MagicMock()
        user.user_level = 10
        channel, error = _resolve_xc_live_channel(user, "not-a-number")
        self.assertIsNone(channel)
        self.assertEqual(error.status_code, 404)
