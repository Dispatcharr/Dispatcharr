from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.stalker import (
    DEFAULT_USER_AGENT,
    StalkerClient,
    StalkerError,
    StalkerMalformedLinkError,
    StalkerRecoverableError,
)
from apps.proxy.live_proxy.url_utils import generate_stream_url, resolve_live_stream_url
from core.models import PROXY_PROFILE_NAME, StreamProfile, UserAgent


class StalkerPhase5PreviewTests(TestCase):
    def setUp(self):
        self.user_agent = UserAgent.objects.create(
            name="Portal UA",
            user_agent="DispatcharrTest/1.0",
        )
        self.proxy_profile = StreamProfile.objects.create(
            name=PROXY_PROFILE_NAME,
            locked=True,
        )
        self.account = M3UAccount.objects.create(
            name="Stalker Preview",
            account_type=M3UAccount.Types.STALKER,
            server_url="http://portal.example.com/c/",
            username="demo",
            password="secret",
            user_agent=self.user_agent,
            custom_properties={
                "mac": "00:1A:79:00:00:40",
                "token": "OLD-TOKEN",
            },
        )
        self.account_profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="Default",
            is_default=True,
            is_active=True,
            search_pattern=r"world-news",
            replace_pattern="world-news-hd",
        )
        self.stream = Stream.objects.create(
            name="World News",
            url="http://portal.example.com/stalker_portal/server/load.php",
            m3u_account=self.account,
            stream_hash="stalker-stream-hash",
            custom_properties={
                "portal_url": "http://portal.example.com/stalker_portal/server/load.php",
                "cmd": "ffmpeg http://upstream.example.com/live/world-news",
                "provider_type": "stalker",
            },
        )

    def test_resolve_live_stream_url_returns_stored_url_for_non_stalker_accounts(self):
        standard_account = M3UAccount.objects.create(
            name="Standard Preview",
            account_type=M3UAccount.Types.STADNARD,
            server_url="http://playlist.example.com/playlist.m3u",
        )
        stream = Stream.objects.create(
            name="Standard Stream",
            url="http://playlist.example.com/live/standard.ts",
            m3u_account=standard_account,
            stream_hash="standard-stream-hash",
        )

        with patch("apps.proxy.live_proxy.url_utils.StalkerClient.create_link") as mock_create_link:
            self.assertEqual(
                resolve_live_stream_url(stream),
                "http://playlist.example.com/live/standard.ts",
            )

        mock_create_link.assert_not_called()

    def test_generate_stream_url_uses_stalker_create_link_before_profile_transform(self):
        def fake_resolve_playback_url(client, portal_url, channel_metadata, allow_malformed=False):
            # Cold start accepts a malformed link rather than failing with a 503.
            self.assertTrue(allow_malformed)
            self.assertEqual(
                portal_url,
                "http://portal.example.com/stalker_portal/server/load.php",
            )
            self.assertEqual(
                channel_metadata["cmd"],
                "ffmpeg http://upstream.example.com/live/world-news",
            )
            client.token = "NEW-TOKEN"
            return "http://resolved.example.com/live/world-news"

        with patch.object(Stream, "get_stream", return_value=(self.stream.id, self.account_profile.id, None, True)), patch(
            "apps.proxy.live_proxy.url_utils.M3UAccountProfile.objects.get",
            return_value=self.account_profile,
        ), patch.object(
            Stream, "get_stream_profile", return_value=self.proxy_profile
        ), patch(
            "apps.proxy.live_proxy.url_utils.StalkerClient.resolve_playback_url",
            autospec=True,
            side_effect=fake_resolve_playback_url,
        ), patch(
            "apps.proxy.live_proxy.url_utils.close_old_connections"
        ):
            stream_url, user_agent, input_headers, transcode, stream_profile_id, _slot_reserved, error_reason, _stream_id = generate_stream_url(
                self.stream.stream_hash
            )

        self.assertEqual(
            stream_url,
            "http://resolved.example.com/live/world-news-hd",
        )
        self.assertEqual(user_agent, DEFAULT_USER_AGENT)
        self.assertIsNotNone(input_headers)
        self.assertEqual(input_headers["Authorization"], "Bearer NEW-TOKEN")
        self.assertFalse(transcode)
        self.assertEqual(stream_profile_id, self.proxy_profile.id)
        self.assertIsNone(error_reason)

        self.account.refresh_from_db()
        self.assertEqual(self.account.custom_properties["token"], "NEW-TOKEN")

    def test_create_link_uses_go_pathescape_style_cmd_encoding(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )

        with patch.object(client, "handshake"), patch.object(
            client, "authenticate_with_device_ids", return_value={"id": "1"}
        ), patch.object(
            client, "watchdog_update", return_value={}
        ), patch.object(
            client, "_request", return_value={"js": {"cmd": "ffmpeg http://resolved.example.com/live.ts"}}
        ) as mock_request:
            resolved = client.create_link(
                "http://portal.example.com/stalker_portal/portal.php",
                "ffmpeg http://upstream.example.com/live.php?stream=176913&extension=ts",
            )

        self.assertEqual(resolved, "http://resolved.example.com/live.ts")
        mock_request.assert_called_once_with(
            "GET",
            "http://portal.example.com/stalker_portal/portal.php?action=create_link&type=itv&cmd=ffmpeg%20http:%2F%2Fupstream.example.com%2Flive.php%3Fstream=176913&extension=ts&JsHttpRequest=1-xml",
            with_auth=True,
        )

    def test_resolve_playback_url_skips_device_id_auth_for_mac_only_portals(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )

        with patch.object(client, "handshake"), patch.object(
            client, "authenticate_with_device_ids", return_value={"id": "1"}
        ) as mock_device_auth, patch.object(
            client, "watchdog_update", return_value={}
        ) as mock_watchdog, patch.object(
            client, "get_fresh_channel_cmd",
            return_value="ffmpeg http://upstream.example.com/live.php?stream=176913&extension=ts",
        ) as mock_get_fresh_cmd, patch.object(
            client, "create_link",
            return_value="http://resolved.example.com/live.ts",
        ) as mock_create_link:
            client.resolve_playback_url(
                "http://portal.example.com/stalker_portal/portal.php",
                {"stalker_channel_id": "5001", "cmd": "stale"},
            )

        mock_device_auth.assert_not_called()
        mock_watchdog.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php"
        )
        mock_get_fresh_cmd.assert_not_called()
        mock_create_link.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php",
            "stale",
        )

    def test_resolve_playback_url_uses_device_id_auth_when_ids_are_configured(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
            custom_properties={
                "device_id": "device-1",
                "device_id2": "device-2",
            },
        )

        with patch.object(client, "handshake"), patch.object(
            client, "authenticate_with_device_ids", return_value={"id": "1"}
        ) as mock_device_auth, patch.object(
            client, "watchdog_update", return_value={}
        ), patch.object(
            client, "get_fresh_channel_cmd",
            return_value="ffmpeg http://upstream.example.com/live.php?stream=176913&extension=ts",
        ) as mock_get_fresh_cmd, patch.object(
            client, "create_link",
            return_value="http://resolved.example.com/live.ts",
        ) as mock_create_link:
            client.resolve_playback_url(
                "http://portal.example.com/stalker_portal/portal.php",
                {"stalker_channel_id": "5001", "cmd": "stale"},
            )

        mock_device_auth.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php"
        )
        mock_get_fresh_cmd.assert_not_called()
        mock_create_link.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php",
            "stale",
        )

    def test_resolve_playback_url_falls_back_to_device_id_auth_after_credential_failure(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
            username="demo",
            password="secret",
            custom_properties={
                "device_id": "device-1",
                "device_id2": "device-2",
            },
        )

        with patch.object(client, "handshake"), patch.object(
            client,
            "authenticate",
            side_effect=StalkerError("Portal rejected the provided credentials."),
        ) as mock_authenticate, patch.object(
            client,
            "authenticate_with_device_ids",
            return_value={"id": "1"},
        ) as mock_device_auth, patch.object(
            client, "watchdog_update", return_value={}
        ), patch.object(
            client,
            "create_link",
            return_value="http://resolved.example.com/live.ts",
        ) as mock_create_link:
            resolved = client.resolve_playback_url(
                "http://portal.example.com/stalker_portal/portal.php",
                {"stalker_channel_id": "5001", "cmd": "stale"},
            )

        self.assertEqual(resolved, "http://resolved.example.com/live.ts")
        mock_authenticate.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php"
        )
        mock_device_auth.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php"
        )
        mock_create_link.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php",
            "stale",
        )
        self.assertEqual(client.last_auth_mode, "device")

    def test_resolve_playback_url_prefers_persisted_device_auth_mode(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
            username="demo",
            password="secret",
            custom_properties={
                "device_id": "device-1",
                "device_id2": "device-2",
                "stalker_auth_mode": "device",
            },
        )

        with patch.object(client, "handshake"), patch.object(
            client,
            "authenticate",
        ) as mock_authenticate, patch.object(
            client,
            "authenticate_with_device_ids",
            return_value={"id": "1"},
        ) as mock_device_auth, patch.object(
            client, "watchdog_update", return_value={}
        ), patch.object(
            client,
            "create_link",
            return_value="http://resolved.example.com/live.ts",
        ) as mock_create_link:
            resolved = client.resolve_playback_url(
                "http://portal.example.com/stalker_portal/portal.php",
                {"stalker_channel_id": "5001", "cmd": "stale"},
            )

        self.assertEqual(resolved, "http://resolved.example.com/live.ts")
        mock_authenticate.assert_not_called()
        mock_device_auth.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php"
        )
        mock_create_link.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php",
            "stale",
        )

    def test_prepare_playback_session_ignores_non_critical_watchdog_failures(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )

        with patch.object(
            client,
            "prepare_authenticated_session",
        ) as mock_prepare, patch.object(
            client,
            "watchdog_update",
            side_effect=StalkerError(
                "Request failed: 404 Client Error: Not Found for url: http://portal.example.com/stalker_portal/portal.php?action=get_events"
            ),
        ) as mock_watchdog:
            client.prepare_playback_session(
                "http://portal.example.com/stalker_portal/portal.php"
            )

        mock_prepare.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php"
        )
        mock_watchdog.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php"
        )

    def test_prepare_playback_session_still_fails_for_non_watchdog_errors(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )

        with patch.object(
            client,
            "prepare_authenticated_session",
        ), patch.object(
            client,
            "watchdog_update",
            side_effect=StalkerError("Request failed: 500 Server Error"),
        ):
            with self.assertRaisesMessage(
                StalkerError,
                "Request failed: 500 Server Error",
            ):
                client.prepare_playback_session(
                    "http://portal.example.com/stalker_portal/portal.php"
                )

    def test_prepare_authenticated_session_does_not_fallback_without_device_ids(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
            username="demo",
            password="secret",
        )

        with patch.object(client, "handshake"), patch.object(
            client,
            "authenticate",
            side_effect=StalkerError("Portal rejected the provided credentials."),
        ) as mock_authenticate, patch.object(
            client, "authenticate_with_device_ids"
        ) as mock_device_auth:
            with self.assertRaisesMessage(
                StalkerError,
                "Portal rejected the provided credentials.",
            ):
                client.prepare_authenticated_session(
                    "http://portal.example.com/stalker_portal/portal.php"
                )

        mock_authenticate.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php"
        )
        mock_device_auth.assert_not_called()

    def test_resolve_playback_url_refreshes_channel_cmd_after_cached_link_failure(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )

        with patch.object(client, "handshake"), patch.object(
            client, "watchdog_update", return_value={}
        ), patch.object(
            client,
            "get_fresh_channel_cmd",
            return_value="ffmpeg http://fresh.example.com/live.php?stream=176913&extension=ts",
        ) as mock_get_fresh_cmd, patch.object(
            client,
            "create_link",
            side_effect=[
                StalkerRecoverableError("Portal returned an empty playback link."),
                "http://resolved.example.com/live.ts",
            ],
        ) as mock_create_link:
            resolved = client.resolve_playback_url(
                "http://portal.example.com/stalker_portal/portal.php",
                {"stalker_channel_id": "5001", "cmd": "stale"},
            )

        self.assertEqual(resolved, "http://resolved.example.com/live.ts")
        mock_get_fresh_cmd.assert_called_once_with(
            "http://portal.example.com/stalker_portal/portal.php",
            {"stalker_channel_id": "5001", "cmd": "stale"},
        )
        self.assertEqual(mock_create_link.call_count, 2)

    def _create_link_with_responses(self, resolved_cmds, allow_malformed=False):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )
        responses = [{"js": {"cmd": cmd}} for cmd in resolved_cmds]
        with patch.object(
            client, "_request", side_effect=responses
        ) as mock_request, patch("apps.m3u.stalker.logger.warning") as mock_warning:
            try:
                result = client.create_link(
                    "http://portal.example.com/stalker_portal/portal.php",
                    "ffmpeg http://upstream.example.com/live.php?stream=176913&extension=ts",
                    allow_malformed=allow_malformed,
                )
            except StalkerError as exc:
                result = exc
        return result, mock_request, mock_warning

    def test_create_link_rejects_empty_stream_id_after_retries(self):
        result, mock_request, mock_warning = self._create_link_with_responses(
            ["ffmpeg http://portal.example.com/live.php?stream=&token=abc"] * 3
        )

        self.assertIsInstance(result, StalkerMalformedLinkError)
        self.assertEqual(
            result.resolved_url, "http://portal.example.com/live.php?stream=&token=abc"
        )
        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(mock_warning.call_count, 3)
        # The warning names the portal host only, never the link or its tokens.
        for call in mock_warning.call_args_list:
            logged = " ".join(str(arg) for arg in call.args)
            self.assertNotIn("token=abc", logged)
            self.assertIn("portal.example.com", logged)

    def test_create_link_rejects_url_fragment_in_stream_id(self):
        # Seen in production: the portal pasted part of the source URL into
        # the stream parameter, and the upstream answered HTTP 405.
        garbled = (
            "ffmpeg http://mag.portal.example:80/play/live.php?mac=00:1A:79:00:00:40"
            "&stream=tal.example:80/play/live.php?mac=00:1A:79:00:00:40"
            "&extension=ts&play_token=abc"
        )
        result, mock_request, _ = self._create_link_with_responses([garbled] * 3)

        self.assertIsInstance(result, StalkerMalformedLinkError)
        self.assertEqual(mock_request.call_count, 3)

    def test_create_link_rejects_encoded_newline_in_stream_id(self):
        result, _, _ = self._create_link_with_responses(
            ["ffmpeg http://portal.example.com/live.php?stream=123%0A&token=abc"] * 3
        )

        self.assertIsInstance(result, StalkerMalformedLinkError)

    def test_create_link_can_return_the_malformed_link_when_allowed(self):
        result, mock_request, _ = self._create_link_with_responses(
            ["ffmpeg http://portal.example.com/live.php?stream=&token=abc"] * 3,
            allow_malformed=True,
        )

        self.assertEqual(result, "http://portal.example.com/live.php?stream=&token=abc")
        self.assertEqual(mock_request.call_count, 3)

    def test_malformed_link_skips_command_refresh_and_session_recovery(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )
        with patch.object(client, "prepare_playback_session"), patch.object(
            client, "get_fresh_channel_cmd"
        ) as mock_get_fresh_cmd, patch.object(
            client,
            "create_link",
            side_effect=StalkerMalformedLinkError("bad", resolved_url="http://x/?stream="),
        ) as mock_create_link:
            with self.assertRaises(StalkerMalformedLinkError):
                client.resolve_playback_url(
                    "http://portal.example.com/stalker_portal/portal.php",
                    {"stalker_channel_id": "5001", "cmd": "ffmpeg http://x/ch/1"},
                )

        mock_create_link.assert_called_once()
        mock_get_fresh_cmd.assert_not_called()

    def test_create_link_retries_until_portal_returns_valid_link(self):
        garbled = (
            "ffmpeg http://mag.portal.example:80/play/live.php?mac=00:1A:79:00:00:40"
            "&stream=tal.example:80/play/live.php?mac=00:1A:79:00:00:40"
            "&extension=ts&play_token=abc"
        )
        valid = (
            "ffmpeg http://mag.portal.example:80/play/live.php?mac=00:1A:79:00:00:40"
            "&stream=902105&extension=ts&play_token=abc"
        )
        result, mock_request, _ = self._create_link_with_responses([garbled, valid])

        self.assertEqual(
            result,
            "http://mag.portal.example:80/play/live.php?mac=00:1A:79:00:00:40"
            "&stream=902105&extension=ts&play_token=abc",
        )
        self.assertEqual(mock_request.call_count, 2)

    def test_create_link_accepts_links_without_stream_parameter(self):
        result, mock_request, mock_warning = self._create_link_with_responses(
            ["ffmpeg http://resolved.example.com/live/world-news.ts?token=abc"]
        )

        self.assertEqual(result, "http://resolved.example.com/live/world-news.ts?token=abc")
        self.assertEqual(mock_request.call_count, 1)
        mock_warning.assert_not_called()

    def test_get_fresh_channel_cmd_prefers_current_session_channel_cmd(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )

        with patch.object(
            client,
            "get_all_channels",
            return_value=[
                {
                    "id": "5001",
                    "cmd": "ffmpeg http://fresh.example.com/live.php?stream=200001&extension=ts",
                    "cmds": [{"id": "1001", "ch_id": "7001"}],
                }
            ],
        ):
            fresh_cmd = client.get_fresh_channel_cmd(
                "http://portal.example.com/stalker_portal/portal.php",
                {
                    "stalker_channel_id": "5001",
                    "cmd": "ffmpeg http://stale.example.com/live.php?stream=old&extension=ts",
                    "cmd_id": "1001",
                    "cmd_ch_id": "7001",
                },
            )

        self.assertEqual(
            fresh_cmd,
            "ffmpeg http://fresh.example.com/live.php?stream=200001&extension=ts",
        )

    def test_authenticate_with_device_ids_requires_non_empty_profile_id(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )

        with patch.object(
            client,
            "_request",
            return_value={"js": {"id": None}, "text": "bad device auth"},
        ):
            with self.assertRaisesMessage(StalkerError, "bad device auth"):
                client.authenticate_with_device_ids(
                    "http://portal.example.com/stalker_portal/portal.php"
                )

    def test_authenticate_with_device_ids_omits_placeholder_identity_values(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:00:00:40",
        )

        with patch.object(
            client,
            "_request",
            return_value={"js": {"id": "1"}},
        ) as mock_request:
            client.authenticate_with_device_ids(
                "http://portal.example.com/stalker_portal/portal.php"
            )

        query = mock_request.call_args.kwargs["query"]
        self.assertNotIn("sn", query)
        self.assertNotIn("device_id", query)
        self.assertNotIn("device_id2", query)
        self.assertEqual(query["stb_type"], "MAG254")

    def test_authenticated_headers_match_stalkerhek_cookie_encoding(self):
        client = StalkerClient(
            server_url="http://portal.example.com/stalker_portal/portal.php",
            mac="00:1A:79:36:6A:E9",
            custom_properties={"timezone": "America/Toronto"},
        )
        client.token = "TOKEN-123"

        headers = client._headers(
            "http://portal.example.com/stalker_portal/portal.php",
            with_auth=True,
        )

        self.assertEqual(headers["Authorization"], "Bearer TOKEN-123")
        self.assertEqual(
            headers["Cookie"],
            "PHPSESSID=null; mac=00%3A1A%3A79%3A36%3A6A%3AE9; stb_lang=en; timezone=America%2FToronto;",
        )


from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import Stream
from apps.m3u.models import M3UAccount
from apps.m3u.stalker import StalkerClient, StalkerError, StalkerRecoverableError
from apps.proxy.live_proxy.url_utils import resolve_live_stream_url


class StalkerPhase6ResolverHardeningTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Stalker Resolver",
            account_type=M3UAccount.Types.STALKER,
            server_url="http://portal.example.com/c/",
            username="demo",
            password="secret",
            custom_properties={
                "mac": "00:1A:79:00:00:40",
                "token": "OLD-TOKEN",
            },
        )
        self.stream = Stream.objects.create(
            name="World News",
            url="http://portal.example.com/stalker_portal/server/load.php",
            m3u_account=self.account,
            stream_hash="phase6-stream-hash",
            custom_properties={
                "portal_url": "http://portal.example.com/stalker_portal/server/load.php",
                "cmd": "ffmpeg http://upstream.example.com/live/world-news",
                "stalker_channel_id": "5001",
                "provider_type": "stalker",
            },
        )

    def test_resolve_playback_url_retries_once_after_recoverable_create_link_failure(self):
        client = StalkerClient(
            server_url=self.account.server_url,
            mac="00:1A:79:00:00:40",
            username=self.account.username,
            password=self.account.password,
            custom_properties={"token": "OLD-TOKEN"},
        )

        def fake_prepare(portal_url):
            if fake_prepare.calls == 0:
                client.token = "OLD-TOKEN"
            else:
                client.token = "NEW-TOKEN"
            fake_prepare.calls += 1

        fake_prepare.calls = 0

        with patch.object(
            client,
            "prepare_playback_session",
            side_effect=fake_prepare,
        ) as mock_prepare, patch.object(
            client,
            "get_fresh_channel_cmd",
            return_value="ffmpeg http://upstream.example.com/live/world-news",
        ) as mock_get_fresh_cmd, patch.object(
            client,
            "create_link",
            side_effect=[
                StalkerRecoverableError("Portal session expired."),
                "http://resolved.example.com/live/world-news",
            ],
        ) as mock_create_link:
            resolved = client.resolve_playback_url(
                "http://portal.example.com/stalker_portal/server/load.php",
                self.stream.custom_properties,
            )

        self.assertEqual(
            resolved,
            "http://resolved.example.com/live/world-news",
        )
        self.assertEqual(client.token, "NEW-TOKEN")
        self.assertEqual(mock_prepare.call_count, 2)
        mock_get_fresh_cmd.assert_not_called()
        self.assertEqual(mock_create_link.call_count, 2)

    def test_resolve_live_stream_url_persists_refreshed_token_after_session_recovery(self):
        def fake_prepare(client, portal_url):
            fake_prepare.calls += 1
            if fake_prepare.calls == 2:
                client.token = "REFRESHED-TOKEN"

        fake_prepare.calls = 0

        def fake_create_link(client, portal_url, cmd):
            if fake_create_link.calls == 0:
                fake_create_link.calls += 1
                raise StalkerRecoverableError("Portal session expired.")
            fake_create_link.calls += 1
            return "http://resolved.example.com/live/world-news"

        fake_create_link.calls = 0

        with patch.object(
            StalkerClient,
            "prepare_playback_session",
            autospec=True,
            side_effect=fake_prepare,
        ), patch.object(
            StalkerClient,
            "create_link",
            autospec=True,
            side_effect=fake_create_link,
        ):
            resolved = resolve_live_stream_url(self.stream)

        self.assertEqual(
            resolved,
            "http://resolved.example.com/live/world-news",
        )
        self.account.refresh_from_db()
        self.assertEqual(
            self.account.custom_properties["token"],
            "REFRESHED-TOKEN",
        )

    def test_resolve_playback_url_does_not_retry_non_recoverable_errors(self):
        client = StalkerClient(
            server_url=self.account.server_url,
            mac="00:1A:79:00:00:40",
            username=self.account.username,
            password=self.account.password,
            custom_properties={"token": "OLD-TOKEN"},
        )

        with patch.object(client, "prepare_playback_session") as mock_prepare, patch.object(
            client,
            "get_fresh_channel_cmd",
            return_value="ffmpeg http://upstream.example.com/live/world-news",
        ) as mock_get_fresh_cmd, patch.object(
            client,
            "create_link",
            side_effect=StalkerError("Request failed: 500 Server Error"),
        ) as mock_create_link:
            with self.assertRaisesMessage(
                StalkerError,
                "Request failed: 500 Server Error",
            ):
                client.resolve_playback_url(
                    "http://portal.example.com/stalker_portal/server/load.php",
                    self.stream.custom_properties,
                )

        mock_prepare.assert_called_once()
        mock_get_fresh_cmd.assert_not_called()
        mock_create_link.assert_called_once()

    def test_resolve_playback_url_retries_transient_transport_failures_once(self):
        client = StalkerClient(
            server_url=self.account.server_url,
            mac="00:1A:79:00:00:40",
            username=self.account.username,
            password=self.account.password,
            custom_properties={"token": "OLD-TOKEN"},
        )

        with patch.object(client, "prepare_playback_session") as mock_prepare, patch.object(
            client,
            "get_fresh_channel_cmd",
            return_value="ffmpeg http://upstream.example.com/live/world-news",
        ) as mock_get_fresh_cmd, patch.object(
            client,
            "create_link",
            side_effect=[
                StalkerError(
                    "Request failed: HTTPSConnectionPool(host='portal.example.com', port=443): Read timed out."
                ),
                "http://resolved.example.com/live/world-news",
            ],
        ) as mock_create_link:
            resolved = client.resolve_playback_url(
                "http://portal.example.com/stalker_portal/server/load.php",
                self.stream.custom_properties,
            )

        self.assertEqual(
            resolved,
            "http://resolved.example.com/live/world-news",
        )
        self.assertEqual(mock_prepare.call_count, 2)
        mock_get_fresh_cmd.assert_not_called()
        self.assertEqual(mock_create_link.call_count, 2)

    def test_resolve_playback_url_refreshes_cmd_before_retrying_session(self):
        client = StalkerClient(
            server_url=self.account.server_url,
            mac="00:1A:79:00:00:40",
            username=self.account.username,
            password=self.account.password,
            custom_properties={"token": "OLD-TOKEN"},
        )

        with patch.object(
            client,
            "prepare_playback_session",
        ) as mock_prepare, patch.object(
            client,
            "get_fresh_channel_cmd",
            return_value="ffmpeg http://upstream.example.com/live/world-news-fresh",
        ) as mock_get_fresh_cmd, patch.object(
            client,
            "create_link",
            side_effect=[
                StalkerRecoverableError("Portal returned an empty playback link."),
                "http://resolved.example.com/live/world-news",
            ],
        ) as mock_create_link:
            resolved = client.resolve_playback_url(
                "http://portal.example.com/stalker_portal/server/load.php",
                self.stream.custom_properties,
            )

        self.assertEqual(
            resolved,
            "http://resolved.example.com/live/world-news",
        )
        mock_prepare.assert_called_once()
        mock_get_fresh_cmd.assert_called_once_with(
            "http://portal.example.com/stalker_portal/server/load.php",
            self.stream.custom_properties,
        )
        self.assertEqual(mock_create_link.call_count, 2)
