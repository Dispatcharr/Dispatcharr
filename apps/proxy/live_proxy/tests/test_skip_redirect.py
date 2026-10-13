"""skip_redirect serves Redirect previews as profile-scoped stream workers."""

from unittest.mock import MagicMock, patch

from django.http import HttpResponseRedirect, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase

from apps.accounts.models import User
from apps.channels.models import Channel, Stream
from apps.proxy.live_proxy.url_utils import (
    parse_preview_worker_id,
    preview_worker_id,
)


class PreviewWorkerIdHelpersTests(SimpleTestCase):
    def test_parse_composite_and_plain_ids(self):
        stream_hash = "a" * 64
        self.assertEqual(
            parse_preview_worker_id(f"{stream_hash}.p12"),
            (stream_hash, 12),
        )
        self.assertEqual(parse_preview_worker_id(stream_hash), (stream_hash, None))
        self.assertEqual(
            parse_preview_worker_id("not-a-composite.pxyz"),
            ("not-a-composite.pxyz", None),
        )
        # Colon form must not parse: those ids break live:channel:{id}:… key parsers.
        self.assertEqual(
            parse_preview_worker_id(f"{stream_hash}:p12"),
            (f"{stream_hash}:p12", None),
        )

    def test_preview_worker_id_format(self):
        self.assertEqual(preview_worker_id("abc", 7), "abc.p7")

    def test_client_supplied_worker_id_is_rejected(self):
        from apps.proxy.live_proxy.views import stream_ts

        factory = RequestFactory()
        request = factory.get("/proxy/ts/stream/abc.p7/?skip_redirect=true")
        request.user = MagicMock(is_authenticated=False)
        with patch(
            "apps.proxy.live_proxy.views.network_access_allowed", return_value=True
        ), patch("apps.proxy.live_proxy.views.ProxyServer"), patch(
            "apps.proxy.live_proxy.views.get_stream_object"
        ) as mock_get_stream_object:
            response = stream_ts(request, "abc.p7")

        self.assertEqual(response.status_code, 404)
        mock_get_stream_object.assert_not_called()


class PickStreamM3UProfileIdTests(SimpleTestCase):
    def _stream(self, *, reusable=True):
        stream = MagicMock(spec=Stream)
        stream.id = 42
        stream.m3u_account = MagicMock(id=1, is_active=True)
        stream._scoped_preview_assignment_is_reusable.return_value = reusable
        return stream

    def _profile(self, profile_id):
        return MagicMock(id=profile_id, is_active=True, is_default=profile_id == 1)

    def _pick(self, stream, redis_client, allowed, capacity):
        from apps.proxy.live_proxy.url_utils import pick_stream_m3u_profile_id

        with patch(
            "core.utils.RedisClient.get_client", return_value=redis_client
        ), patch(
            "apps.proxy.live_proxy.url_utils.pool_has_capacity_for_profile",
            side_effect=lambda profile, _redis: capacity[profile.id],
        ):
            return pick_stream_m3u_profile_id(stream, allowed)

    def test_joins_live_preview_on_full_profile(self):
        stream = self._stream()
        redis_client = MagicMock()
        redis_client.get.side_effect = lambda key: (
            b"1" if key == "stream_profile:42:p1" else None
        )
        allowed = {1: [self._profile(1), self._profile(2)]}

        picked = self._pick(stream, redis_client, allowed, {1: False, 2: True})

        self.assertEqual(picked, 1)

    def test_stale_scoped_key_falls_through_to_next_profile(self):
        stream = self._stream(reusable=False)
        redis_client = MagicMock()
        redis_client.get.return_value = b"1"
        allowed = {1: [self._profile(1), self._profile(2)]}

        picked = self._pick(stream, redis_client, allowed, {1: False, 2: True})

        self.assertEqual(picked, 2)

    def test_none_when_every_profile_is_full(self):
        stream = self._stream()
        redis_client = MagicMock()
        redis_client.get.return_value = None
        allowed = {1: [self._profile(1)]}

        self.assertIsNone(self._pick(stream, redis_client, allowed, {1: False}))

    def test_empty_allowlist_for_account_yields_none(self):
        stream = self._stream()
        self.assertIsNone(self._pick(stream, MagicMock(), {}, {}))


class StreamTsSkipRedirectTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"
        self.provider_url = "http://provider.example/live/1"
        self.stream_hash = "b" * 64

    def _channel(self, *, redirect=True):
        channel = MagicMock(spec=Channel)
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        stream_profile = MagicMock()
        stream_profile.is_redirect.return_value = redirect
        channel.get_stream_profile.return_value = stream_profile
        channel.release_stream.return_value = True
        return channel

    def _stream(self, *, redirect=True):
        stream = MagicMock(spec=Stream)
        stream.id = 42
        stream.name = "Preview Stream"
        stream.stream_hash = self.stream_hash
        stream.m3u_account = MagicMock()
        stream_profile = MagicMock()
        stream_profile.is_redirect.return_value = redirect
        stream.get_stream_profile.return_value = stream_profile
        stream.release_stream.return_value = True
        return stream

    def _proxy_server(self, *, active=False, worker_id=None):
        worker_id = worker_id or self.channel_id
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = active
        proxy_server.redis_client.get.return_value = None
        proxy_server.redis_client.hmget.return_value = (None, None, None)
        proxy_server.redis_client.hgetall.return_value = (
            {"state": "active"} if active else {}
        )
        proxy_server.stream_buffers = {worker_id: MagicMock()} if active else {}
        client_manager = MagicMock()
        client_manager.add_client.return_value = True
        proxy_server.client_managers = {worker_id: client_manager} if active else {}
        proxy_server.check_if_channel_exists.return_value = active
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.try_acquire_ownership.return_value = True
        proxy_server.ensure_output_profile.return_value = True
        proxy_server.am_i_owner.return_value = True
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
        return proxy_server, client_manager

    def _user(self, level):
        user = MagicMock()
        user.is_authenticated = True
        user.user_level = level
        user.stream_limit = 0
        return user

    def _request(self, *, path=None, skip_redirect=False, user=None):
        path = path or f"/proxy/ts/stream/{self.channel_id}/"
        if skip_redirect is True:
            request = self.factory.get(f"{path}?skip_redirect=true")
        elif isinstance(skip_redirect, str):
            request = self.factory.get(f"{path}?skip_redirect={skip_redirect}")
        else:
            request = self.factory.get(path)
        request.user = user or MagicMock(is_authenticated=False)
        return request

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.config.TSConfig.get_validate_redirect_urls", return_value=False)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_plain_redirect_skips_running_channel_check(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        _mock_close,
    ):
        mock_generate_stream_url.return_value = (
            self.provider_url,
            "ua",
            False,
            "None",
            False,
            None,
            42,
        )
        channel = self._channel(redirect=True)
        mock_get_stream_object.return_value = channel
        proxy_server, _ = self._proxy_server(active=True)
        mock_proxy_cls.get_instance.return_value = proxy_server

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response.url, self.provider_url)
        proxy_server._get_channel_init_lock.assert_not_called()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.config.TSConfig.get_validate_redirect_urls", return_value=False)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_streamer_skip_redirect_is_ignored(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        _mock_close,
    ):
        mock_generate_stream_url.return_value = (
            self.provider_url,
            "ua",
            False,
            "None",
            False,
            None,
            42,
        )
        mock_get_stream_object.return_value = self._channel(redirect=True)
        mock_proxy_cls.get_instance.return_value = self._proxy_server()[0]

        from apps.proxy.live_proxy.views import stream_ts

        user = self._user(User.UserLevel.STREAMER)
        response = stream_ts(
            self._request(skip_redirect=True, user=user),
            self.channel_id,
            user=user,
        )

        self.assertIsInstance(response, HttpResponseRedirect)

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.config.TSConfig.get_validate_redirect_urls", return_value=False)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_false_and_empty_values_stay_redirect(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        _mock_close,
    ):
        mock_generate_stream_url.return_value = (
            self.provider_url,
            "ua",
            False,
            "None",
            False,
            None,
            42,
        )
        mock_get_stream_object.return_value = self._channel(redirect=True)
        mock_proxy_cls.get_instance.return_value = self._proxy_server()[0]

        from apps.proxy.live_proxy.views import stream_ts

        user = self._user(User.UserLevel.ADMIN)
        for value in ("false", ""):
            response = stream_ts(
                self._request(skip_redirect=value, user=user),
                self.channel_id,
                user=user,
            )
            self.assertIsInstance(response, HttpResponseRedirect)

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.config.TSConfig.get_validate_redirect_urls", return_value=False)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_xc_path_skip_redirect_is_ignored(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        _mock_validate_setting,
        _mock_close,
    ):
        mock_generate_stream_url.return_value = (
            self.provider_url,
            "ua",
            False,
            "None",
            False,
            None,
            42,
        )
        mock_get_stream_object.return_value = self._channel(redirect=True)
        mock_proxy_cls.get_instance.return_value = self._proxy_server()[0]

        from apps.proxy.live_proxy.views import stream_ts

        user = self._user(User.UserLevel.ADMIN)
        request = self._request(
            path="/live/admin/pass/1.ts",
            skip_redirect=True,
            user=user,
        )
        response = stream_ts(request, self.channel_id, user=user)

        self.assertIsInstance(response, HttpResponseRedirect)

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views._resolve_proxy_profile_id", return_value=99)
    @patch("apps.proxy.live_proxy.views.pick_channel_preview_target")
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.initialize_channel",
        return_value=True,
    )
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_admin_skip_redirect_remaps_to_stream_worker(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_initialize,
        mock_generate_stream_url,
        mock_pick_target,
        _proxy_profile_id,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        stream = self._stream(redirect=True)
        mock_pick_target.return_value = (stream, 5)
        mock_generate_stream_url.return_value = (
            self.provider_url,
            "ua",
            False,
            99,
            True,
            None,
            42,
        )
        mock_get_stream_object.return_value = self._channel(redirect=True)

        worker_id = preview_worker_id(self.stream_hash, 5)
        proxy_server, _ = self._proxy_server(active=False, worker_id=worker_id)
        client_manager = MagicMock()
        client_manager.add_client.return_value = True
        proxy_server.client_managers = {worker_id: client_manager}
        proxy_server.stream_buffers = {worker_id: MagicMock()}
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        user = self._user(User.UserLevel.ADMIN)
        with patch(
            "apps.proxy.live_proxy.views.check_user_stream_limits", return_value=True
        ) as mock_limits:
            response = stream_ts(
                self._request(skip_redirect=True, user=user),
                self.channel_id,
                user=user,
            )

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertEqual(mock_limits.call_args.kwargs.get("media_id"), worker_id)
        mock_pick_target.assert_called_once()
        called_worker_id = mock_generate_stream_url.call_args.args[0]
        self.assertEqual(called_worker_id, worker_id)
        self.assertEqual(
            mock_generate_stream_url.call_args.kwargs.get("override_stream_profile_id"),
            99,
        )
        self.assertEqual(mock_initialize.call_args.args[0], worker_id)
        self.assertFalse(mock_initialize.call_args.args[3])  # transcode=False

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views._resolve_proxy_profile_id", return_value=99)
    @patch("apps.proxy.live_proxy.views.pick_channel_preview_target")
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_admin_skip_redirect_joins_existing_stream_worker(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        _unavailable,
        mock_generate_stream_url,
        mock_pick_target,
        _proxy_profile_id,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        stream = self._stream(redirect=True)
        mock_pick_target.return_value = (stream, 5)
        mock_get_stream_object.return_value = self._channel(redirect=True)

        worker_id = preview_worker_id(self.stream_hash, 5)
        proxy_server, client_manager = self._proxy_server(
            active=True, worker_id=worker_id
        )
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        user = self._user(User.UserLevel.STANDARD)
        response = stream_ts(
            self._request(skip_redirect=True, user=user),
            self.channel_id,
            user=user,
        )

        self.assertIsInstance(response, StreamingHttpResponse)
        mock_generate_stream_url.assert_not_called()
        client_manager.add_client.assert_called_once()


class GenerateStreamUrlOverrideTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("apps.proxy.live_proxy.url_utils._resolve_live_stream_url")
    @patch("apps.proxy.live_proxy.url_utils.get_stream_object")
    def test_stream_hash_honors_override_and_scoped_m3u_profile(
        self,
        mock_get_stream_object,
        mock_resolve_url,
        _mock_close,
    ):
        from apps.proxy.live_proxy.url_utils import generate_stream_url

        stream = MagicMock(spec=Stream)
        stream.id = 7
        stream.name = "Direct"
        stream.m3u_account = MagicMock()
        stream.get_stream.return_value = (7, 3, None, True)
        mock_get_stream_object.return_value = stream

        m3u_profile = MagicMock()
        m3u_profile.m3u_account = stream.m3u_account
        stream.m3u_account.get_user_agent_string.return_value = "ua"
        mock_resolve_url.return_value = "http://provider.example/s.ts"

        worker_id = preview_worker_id("c" * 64, 3)
        with patch(
            "apps.proxy.live_proxy.url_utils.M3UAccountProfile.objects.select_related"
        ) as mock_select:
            mock_select.return_value.get.return_value = m3u_profile
            result = generate_stream_url(
                worker_id,
                override_stream_profile_id=99,
            )

        url, ua, transcode, profile_id, slot_reserved, error, stream_id = result
        self.assertEqual(url, "http://provider.example/s.ts")
        self.assertFalse(transcode)
        self.assertEqual(profile_id, 99)
        stream.get_stream.assert_called_once_with(preferred_profile_id=3)
        self.assertEqual(stream_id, 7)
        self.assertIsNone(error)
