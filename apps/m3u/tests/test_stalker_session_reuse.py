"""Tests for reusing a StalkerClient session across repeated resolve calls.

Before this fix, ``_resolve_live_stream_context`` built a brand-new
``StalkerClient`` on every call, which meant every retry in the live-proxy
connection loop re-handshook with the portal from scratch (see
``apps/proxy/live_proxy/input/manager.py`` retry loop), even though a session
had just been established seconds earlier. ``get_stream_info_for_switch`` now
accepts an optional ``stalker_client_cache`` dict, owned by the caller, that
lets repeated calls for the same (account, mac) reuse the same client instance
instead of re-authenticating every time.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.stalker import StalkerClient
from apps.proxy.live_proxy.url_utils import get_stream_info_for_switch
from core.models import PROXY_PROFILE_NAME, StreamProfile, UserAgent


class StalkerSessionReuseTests(TestCase):
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
            name="Stalker Session Reuse",
            account_type=M3UAccount.Types.STALKER,
            server_url="http://portal.example.com/c/",
            username="demo",
            password="secret",
            user_agent=self.user_agent,
            custom_properties={"mac": "00:1A:79:00:00:40"},
        )
        self.account_profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="Default",
            is_default=True,
            is_active=True,
        )
        self.stream = Stream.objects.create(
            name="World News",
            url="http://portal.example.com/stalker_portal/server/load.php",
            m3u_account=self.account,
            stream_hash="stalker-session-reuse-hash",
            custom_properties={
                "portal_url": "http://portal.example.com/stalker_portal/server/load.php",
                "cmd": "ffmpeg http://upstream.example.com/live/world-news",
                "provider_type": "stalker",
            },
        )

    def _resolve_twice(self, stalker_client_cache):
        seen_clients = []

        def fake_resolve_playback_url(client, portal_url, channel_metadata):
            seen_clients.append(client)
            return "http://resolved.example.com/live/world-news"

        with patch.object(
            Stream, "get_stream",
            return_value=(self.stream.id, self.account_profile.id, None, True),
        ), patch.object(
            Stream, "get_stream_profile", return_value=self.proxy_profile
        ), patch(
            "apps.proxy.live_proxy.url_utils.StalkerClient.resolve_playback_url",
            autospec=True,
            side_effect=fake_resolve_playback_url,
        ), patch(
            "apps.proxy.live_proxy.url_utils.close_old_connections"
        ):
            get_stream_info_for_switch(
                self.stream.stream_hash,
                stalker_client_cache=stalker_client_cache,
            )
            get_stream_info_for_switch(
                self.stream.stream_hash,
                stalker_client_cache=stalker_client_cache,
            )

        return seen_clients

    def test_reuses_same_stalker_client_across_calls_when_cache_is_shared(self):
        cache = {}
        seen_clients = self._resolve_twice(cache)

        self.assertEqual(len(seen_clients), 2)
        self.assertIs(seen_clients[0], seen_clients[1])
        self.assertIsInstance(seen_clients[0], StalkerClient)
        self.assertIn((self.account.id, "00:1A:79:00:00:40"), cache)
        self.assertIs(cache[(self.account.id, "00:1A:79:00:00:40")], seen_clients[0])

    def test_creates_a_new_stalker_client_each_call_without_a_cache(self):
        seen_clients = self._resolve_twice(stalker_client_cache=None)

        self.assertEqual(len(seen_clients), 2)
        self.assertIsNot(seen_clients[0], seen_clients[1])


class StalkerMalformedLinkSwitchTests(StalkerSessionReuseTests):
    """Failover must not hand a malformed Stalker link to the stream manager."""

    def test_switch_reports_an_error_for_a_malformed_link(self):
        from apps.m3u.stalker import StalkerMalformedLinkError

        with patch.object(
            Stream, "get_stream",
            return_value=(self.stream.id, self.account_profile.id, None, True),
        ), patch.object(
            Stream, "get_stream_profile", return_value=self.proxy_profile
        ), patch(
            "apps.proxy.live_proxy.url_utils.StalkerClient.resolve_playback_url",
            side_effect=StalkerMalformedLinkError(
                "Portal returned a malformed playback link.",
                resolved_url="http://portal.example.com/live.php?stream=bad:80/x",
            ),
        ), patch(
            "apps.proxy.live_proxy.url_utils.close_old_connections"
        ):
            info = get_stream_info_for_switch(self.stream.stream_hash)

        self.assertIn("error", info)
        self.assertNotIn("url", info)
