"""Tests for global and per-M3U-account proxy configuration and routing."""

import os
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.channels.models import Channel, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.serializers import M3UAccountSerializer
from apps.m3u.tasks import fetch_m3u_lines, refresh_account_info
from apps.m3u.utils import (
    build_requests_proxies,
    get_account_effective_proxy,
    normalize_proxy_url,
)
from apps.proxy.live_proxy.input.http_streamer import HTTPStreamReader
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.url_utils import (
    get_proxy_for_stream,
    get_stream_info_for_switch,
    validate_stream_url,
)
from apps.proxy.vod_proxy.multi_worker_connection_manager import (
    RedisBackedVODConnection,
    SerializableConnectionState,
)
from apps.timeshift.views import _open_upstream
from apps.vod.tasks import refresh_categories
from core.models import CoreSettings, STREAM_SETTINGS_KEY, StreamProfile
from core.serializers import CoreSettingsSerializer
from core.xtream_codes import Client as XCClient


def _set_global_proxy(value):
    """Set the global Default Proxy setting under stream_settings."""
    CoreSettings._update_group(
        STREAM_SETTINGS_KEY, "Stream Settings", {"default_proxy": value}
    )


class NormalizeProxyUrlTests(TestCase):
    def test_returns_empty_string_for_empty_or_whitespace(self):
        self.assertEqual(normalize_proxy_url(None), "")
        self.assertEqual(normalize_proxy_url(""), "")
        self.assertEqual(normalize_proxy_url("   "), "")
        self.assertEqual(normalize_proxy_url(None, strict=True), "")
        self.assertEqual(normalize_proxy_url("", strict=True), "")
        self.assertEqual(normalize_proxy_url("   ", strict=True), "")

    def test_accepts_supported_proxy_schemes_and_normalizes(self):
        cases = [
            ("http://proxy.example.com:8080", "http://proxy.example.com:8080"),
            ("  HTTP://proxy.example.com:8080/  ", "http://proxy.example.com:8080"),
            (
                "https://user:pass@proxy.example.com:8443",
                "https://user:pass@proxy.example.com:8443",
            ),
            ("socks4://127.0.0.1:1080", "socks4://127.0.0.1:1080"),
            ("socks4a://127.0.0.1:1080", "socks4a://127.0.0.1:1080"),
            ("socks5://127.0.0.1:1080", "socks5://127.0.0.1:1080"),
            (
                "SOCKS5H://user:secret@10.0.0.1:1080",
                "socks5h://user:secret@10.0.0.1:1080",
            ),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_proxy_url(raw, strict=True), expected)

    def test_rejects_invalid_proxy_urls_in_strict_mode(self):
        invalid_cases = [
            "ftp://proxy.example.com:21",
            "proxy.example.com:8080",
            "http://",
            "http://proxy.example.com:8080/some/path",
            "http://proxy.example.com:8080?foo=bar",
            "http://proxy.example.com:8080#frag",
            "http://proxy example.com:8080",
            "http://proxy.example.com:99999",
        ]
        for raw in invalid_cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    normalize_proxy_url(raw, strict=True)
                self.assertEqual(normalize_proxy_url(raw, strict=False), "")

    def test_build_requests_proxies(self):
        self.assertIsNone(build_requests_proxies(None))
        self.assertIsNone(build_requests_proxies(""))
        self.assertIsNone(build_requests_proxies("invalid-url"))
        self.assertEqual(
            build_requests_proxies("http://proxy.local:8080"),
            {
                "http": "http://proxy.local:8080",
                "https": "http://proxy.local:8080",
            },
        )


class CoreSettingsDefaultProxyTests(TestCase):
    def setUp(self):
        _set_global_proxy("")

    def test_default_proxy_is_empty_by_default(self):
        CoreSettings.objects.filter(key=STREAM_SETTINGS_KEY).delete()
        self.assertEqual(CoreSettings.get_default_proxy(), "")
        self.assertEqual(CoreSettings.get_stream_settings().get("default_proxy"), "")

    def test_serializer_validates_and_normalizes_default_proxy(self):
        setting = CoreSettings.objects.get(key=STREAM_SETTINGS_KEY)
        serializer = CoreSettingsSerializer(
            setting,
            data={"value": {"default_proxy": "  HTTP://proxy.local:8080/  "}},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        saved = serializer.save()
        self.assertEqual(saved.value["default_proxy"], "http://proxy.local:8080")
        self.assertEqual(CoreSettings.get_default_proxy(), "http://proxy.local:8080")

    def test_serializer_clears_default_proxy_when_empty_or_null(self):
        _set_global_proxy("http://proxy.local:8080")
        setting = CoreSettings.objects.get(key=STREAM_SETTINGS_KEY)
        serializer = CoreSettingsSerializer(
            setting,
            data={"value": {"default_proxy": None}},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(CoreSettings.get_default_proxy(), "")

    def test_serializer_rejects_invalid_default_proxy(self):
        setting = CoreSettings.objects.get(key=STREAM_SETTINGS_KEY)
        serializer = CoreSettingsSerializer(
            setting,
            data={"value": {"default_proxy": "ftp://bad-scheme:21"}},
            partial=True,
        )
        self.assertTrue(serializer.is_valid())
        with self.assertRaises(ValidationError):
            serializer.save()


class GetEffectiveProxyTests(TestCase):
    def setUp(self):
        _set_global_proxy("")

    def test_returns_none_when_neither_global_nor_account_proxy_is_set(self):
        account = M3UAccount.objects.create(name="Direct Account")
        self.assertIsNone(account.get_effective_proxy())
        self.assertIsNone(account.get_proxies())

    def test_inherits_global_default_when_account_has_no_override(self):
        _set_global_proxy("http://global-proxy.local:8080")
        account = M3UAccount.objects.create(name="Inheriting Account")
        self.assertEqual(
            account.get_effective_proxy(), "http://global-proxy.local:8080"
        )
        self.assertEqual(
            account.get_proxies(),
            {
                "http": "http://global-proxy.local:8080",
                "https": "http://global-proxy.local:8080",
            },
        )

    def test_inherits_global_default_when_custom_properties_is_none_or_empty(self):
        _set_global_proxy("socks5h://127.0.0.1:1080")
        acc_none = M3UAccount.objects.create(
            name="Null Props Account", custom_properties=None
        )
        acc_empty = M3UAccount.objects.create(
            name="Empty Proxy Account", custom_properties={"proxy": ""}
        )
        self.assertEqual(acc_none.get_effective_proxy(), "socks5h://127.0.0.1:1080")
        self.assertEqual(acc_empty.get_effective_proxy(), "socks5h://127.0.0.1:1080")

    def test_account_override_takes_precedence_over_global_default(self):
        _set_global_proxy("http://global-proxy.local:8080")
        account = M3UAccount.objects.create(
            name="Overridden Account",
            custom_properties={"proxy": "socks5h://account-proxy.local:1080"},
        )
        self.assertEqual(
            account.get_effective_proxy(), "socks5h://account-proxy.local:1080"
        )

    def test_account_override_works_when_global_default_is_unset(self):
        account = M3UAccount.objects.create(
            name="Standalone Proxy Account",
            custom_properties={"proxy": "http://account-proxy.local:8080"},
        )
        self.assertEqual(
            account.get_effective_proxy(), "http://account-proxy.local:8080"
        )

    def test_changing_global_default_updates_inheriting_accounts_only(self):
        overridden = M3UAccount.objects.create(
            name="Overridden Account 2",
            custom_properties={"proxy": "http://specific-proxy.local:8080"},
        )
        plain = M3UAccount.objects.create(name="Plain Account 2")

        self.assertIsNone(plain.get_effective_proxy())
        self.assertEqual(
            overridden.get_effective_proxy(), "http://specific-proxy.local:8080"
        )

        _set_global_proxy("http://new-global.local:3128")
        self.assertEqual(plain.get_effective_proxy(), "http://new-global.local:3128")
        self.assertEqual(
            overridden.get_effective_proxy(), "http://specific-proxy.local:8080"
        )

    def test_invalid_stored_override_falls_back_to_global_default(self):
        _set_global_proxy("http://global-proxy.local:8080")
        account = M3UAccount.objects.create(
            name="Corrupt Override Account",
            custom_properties={"proxy": "not-a-valid-proxy"},
        )
        self.assertEqual(
            account.get_effective_proxy(), "http://global-proxy.local:8080"
        )

    def test_get_account_effective_proxy_ignores_mock_non_string_return(self):
        mock_account = MagicMock()
        self.assertIsNone(get_account_effective_proxy(mock_account))
        self.assertIsNone(get_account_effective_proxy(None))


class M3UAccountSerializerProxyTests(TestCase):
    def setUp(self):
        _set_global_proxy("")

    def test_proxy_field_is_exposed(self):
        account = M3UAccount.objects.create(
            name="Serialized Proxy Account",
            custom_properties={"proxy": "http://proxy.local:8080"},
        )
        data = M3UAccountSerializer(account).data
        self.assertEqual(data["proxy"], "http://proxy.local:8080")

    def test_proxy_defaults_to_null_when_not_set(self):
        account = M3UAccount.objects.create(name="Serialized Plain Account")
        data = M3UAccountSerializer(account).data
        self.assertIsNone(data["proxy"])

    def test_create_stores_proxy_under_custom_properties(self):
        serializer = M3UAccountSerializer(
            data={
                "name": "Created Proxy Account",
                "proxy": "  HTTP://user:pass@proxy.local:8080/  ",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        created = serializer.save()
        self.assertEqual(
            created.custom_properties.get("proxy"),
            "http://user:pass@proxy.local:8080",
        )
        self.assertEqual(
            created.get_effective_proxy(),
            "http://user:pass@proxy.local:8080",
        )

    def test_create_without_proxy_leaves_key_unset(self):
        serializer = M3UAccountSerializer(data={"name": "Created Direct Account"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        created = serializer.save()
        self.assertNotIn("proxy", created.custom_properties or {})

    def test_update_sets_and_clears_proxy_under_custom_properties(self):
        _set_global_proxy("http://global.local:8080")
        account = M3UAccount.objects.create(name="Updatable Account")

        # Set override
        serializer = M3UAccountSerializer(
            account,
            data={"proxy": "socks5h://127.0.0.1:1080"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertEqual(
            updated.custom_properties.get("proxy"), "socks5h://127.0.0.1:1080"
        )
        self.assertEqual(updated.get_effective_proxy(), "socks5h://127.0.0.1:1080")

        # Clear with None -> inherits global
        serializer = M3UAccountSerializer(
            updated, data={"proxy": None}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        cleared = serializer.save()
        self.assertNotIn("proxy", cleared.custom_properties or {})
        self.assertEqual(cleared.get_effective_proxy(), "http://global.local:8080")

        # Set again, then clear with empty string
        serializer = M3UAccountSerializer(
            cleared, data={"proxy": "http://override.local:8080"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        reset_acc = serializer.save()
        serializer = M3UAccountSerializer(
            reset_acc, data={"proxy": ""}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        cleared_again = serializer.save()
        self.assertNotIn("proxy", cleared_again.custom_properties or {})

    def test_proxy_rejects_invalid_url(self):
        account = M3UAccount.objects.create(name="Invalid Proxy Target")
        serializer = M3UAccountSerializer(
            account, data={"proxy": "not_a_proxy_url"}, partial=True
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("proxy", serializer.errors)

    def test_raw_custom_properties_proxy_is_ignored_on_create_and_update(self):
        serializer = M3UAccountSerializer(
            data={
                "name": "Bypass Attempt Account",
                "custom_properties": {"proxy": "http://bypass.local:8080"},
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        created = serializer.save()
        self.assertNotIn("proxy", created.custom_properties or {})

        serializer = M3UAccountSerializer(
            created,
            data={"custom_properties": {"proxy": "http://bypass.local:8080"}},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertNotIn("proxy", updated.custom_properties or {})


class OutboundProviderTrafficProxyTests(TestCase):
    def setUp(self):
        _set_global_proxy("")
        conn_close_patcher = patch("apps.proxy.config.connection.close")
        conn_close_patcher.start()
        self.addCleanup(conn_close_patcher.stop)

    @patch("apps.m3u.tasks.requests.get")
    def test_fetch_m3u_lines_uses_proxies_when_configured(self, mock_get):
        account = M3UAccount.objects.create(
            name="Standard M3U Account",
            account_type="STD",
            server_url="http://provider.local/playlist.m3u",
            custom_properties={"proxy": "http://proxy.local:8080"},
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = account.server_url
        mock_resp.headers = {"Content-Length": "20"}
        mock_resp.iter_content.return_value = [b"#EXTM3U\n#EXTINF:-1,Ch\nhttp://s/1\n"]
        mock_get.return_value = mock_resp

        source, ok = fetch_m3u_lines(account, use_cache=False)
        self.assertTrue(ok)
        self.assertIsNotNone(source)
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(
            kwargs.get("proxies"),
            {
                "http": "http://proxy.local:8080",
                "https": "http://proxy.local:8080",
            },
        )

    def test_xc_client_configures_session_proxies(self):
        client = XCClient(
            "http://xc.local:8080",
            "user",
            "pass",
            user_agent="TestUA",
            proxy="socks5h://127.0.0.1:1080",
        )
        self.assertEqual(
            client.session.proxies.get("http"), "socks5h://127.0.0.1:1080"
        )
        self.assertEqual(
            client.session.proxies.get("https"), "socks5h://127.0.0.1:1080"
        )
        client.close()

    @patch("apps.m3u.tasks.XCClient")
    def test_refresh_account_info_passes_effective_proxy_to_xc_client(
        self, mock_xc_cls
    ):
        _set_global_proxy("http://global-proxy.local:8080")
        account = M3UAccount.objects.create(
            name="XC Account",
            account_type=M3UAccount.Types.XC,
            server_url="http://xc.local:8080",
            username="alice",
            password="secret",
            is_active=True,
        )
        profile = (
            M3UAccountProfile.objects.filter(m3u_account=account).first()
            or M3UAccountProfile.objects.create(
                m3u_account=account,
                name="Default",
                max_streams=1,
                is_active=True,
                is_default=True,
            )
        )
        mock_xc = MagicMock()
        mock_xc.authenticate.return_value = True
        mock_xc.get_account_info.return_value = {"user_info": {"status": "Active"}}
        mock_xc_cls.return_value = mock_xc

        refresh_account_info(profile.id)

        mock_xc_cls.assert_called_once()
        _, kwargs = mock_xc_cls.call_args
        self.assertEqual(kwargs.get("proxy"), "http://global-proxy.local:8080")

    @patch("apps.vod.tasks.XtreamCodesClient")
    def test_vod_refresh_categories_passes_effective_proxy(self, mock_xc_cls):
        account = M3UAccount.objects.create(
            name="VOD XC Account",
            account_type=M3UAccount.Types.XC,
            server_url="http://xc.local:8080",
            username="alice",
            password="secret",
            is_active=True,
            custom_properties={
                "enable_vod": True,
                "proxy": "http://vod-proxy.local:8080",
            },
        )
        mock_xc = MagicMock()
        mock_xc.__enter__.return_value = mock_xc
        mock_xc.get_vod_categories.return_value = []
        mock_xc.get_series_categories.return_value = []
        mock_xc_cls.return_value = mock_xc

        refresh_categories(account.id)

        mock_xc_cls.assert_called_once()
        _, kwargs = mock_xc_cls.call_args
        self.assertEqual(kwargs.get("proxy"), "http://vod-proxy.local:8080")

    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    def test_live_proxy_url_utils_resolve_proxy_for_stream_and_profile(
        self, _mock_close_old_connections
    ):
        stream_profile, _ = StreamProfile.objects.get_or_create(
            name="Proxy",
            defaults={"command": "proxy", "is_active": True},
        )
        account = M3UAccount.objects.create(
            name="Live Proxy Account",
            server_url="http://provider.local",
            custom_properties={"proxy": "http://live-proxy.local:8080"},
        )
        profile = (
            M3UAccountProfile.objects.filter(m3u_account=account).first()
            or M3UAccountProfile.objects.create(
                m3u_account=account,
                name="Default Profile",
                max_streams=1,
                is_active=True,
                is_default=True,
            )
        )
        stream = Stream.objects.create(
            name="Test Stream",
            url="http://provider.local/live/1.ts",
            m3u_account=account,
            stream_hash="hash_live_proxy_test",
        )
        channel = Channel.objects.create(
            name="Test Channel",
            channel_number=101,
            stream_profile=stream_profile,
        )
        channel.streams.add(stream)

        self.assertEqual(
            get_proxy_for_stream(stream_id=stream.id),
            "http://live-proxy.local:8080",
        )
        self.assertEqual(
            get_proxy_for_stream(m3u_profile_id=profile.id),
            "http://live-proxy.local:8080",
        )
        info = get_stream_info_for_switch(
            str(channel.uuid),
            target_stream_id=stream.id,
            target_profile_id=profile.id,
        )
        self.assertEqual(info["proxy"], "http://live-proxy.local:8080")

    @patch("apps.proxy.live_proxy.url_utils.requests.Session")
    def test_validate_stream_url_sets_session_proxies(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.proxies = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = iter([b"data"])
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        ok = validate_stream_url(
            "http://provider.local/live.ts",
            user_agent="TestUA",
            proxy="http://probe-proxy.local:8080",
        )
        self.assertTrue(ok)
        self.assertEqual(
            mock_session.proxies,
            {
                "http": "http://probe-proxy.local:8080",
                "https": "http://probe-proxy.local:8080",
            },
        )

    @patch("apps.proxy.live_proxy.input.http_streamer.requests.Session")
    def test_http_stream_reader_sets_session_proxies(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.proxies = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        reader = HTTPStreamReader(
            url="http://provider.local/live.ts",
            user_agent="TestUA",
            proxy="http://reader-proxy.local:8080",
        )
        reader._read_stream()
        self.assertEqual(
            mock_session.proxies,
            {
                "http": "http://reader-proxy.local:8080",
                "https": "http://reader-proxy.local:8080",
            },
        )

    def test_stream_manager_resolves_proxy_from_stream_id(self):
        account = M3UAccount.objects.create(
            name="Manager Proxy Account",
            custom_properties={"proxy": "http://mgr-proxy.local:8080"},
        )
        stream = Stream.objects.create(
            name="Mgr Stream",
            url="http://provider.local/live/2.ts",
            m3u_account=account,
            stream_hash="hash_mgr_proxy_test",
        )
        mock_buffer = MagicMock()
        mock_buffer.redis_client = None
        mgr = StreamManager(
            "chan-1",
            stream.url,
            mock_buffer,
            user_agent="TestUA",
            stream_id=stream.id,
            channel_name="Test Channel",
        )
        self.assertEqual(mgr._resolve_proxy(), "http://mgr-proxy.local:8080")
        session = mgr._create_session()
        self.assertEqual(session.proxies.get("http"), "http://mgr-proxy.local:8080")
        session.close()

    @patch(
        "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisClient.get_client"
    )
    def test_vod_connection_applies_proxy_to_local_session(self, mock_redis):
        mock_redis.return_value = MagicMock()
        conn = RedisBackedVODConnection("vod-session-1")
        state = SerializableConnectionState(
            session_id="vod-session-1",
            stream_url="http://provider.local/movie.mp4",
            headers={"User-Agent": "TestUA"},
            proxy="http://vod-conn-proxy.local:8080",
        )
        conn._get_connection_state = MagicMock(return_value=state)
        conn._save_connection_state = MagicMock()
        conn.local_session = MagicMock()
        conn.local_session.proxies = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "video/mp4"}
        conn.local_session.get.return_value = mock_resp

        conn.get_stream()

        self.assertEqual(
            conn.local_session.proxies,
            {
                "http": "http://vod-conn-proxy.local:8080",
                "https": "http://vod-conn-proxy.local:8080",
            },
        )

    @patch("apps.timeshift.views.requests.get")
    def test_timeshift_open_upstream_uses_proxies(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        resp = _open_upstream(
            "http://provider.local/timeshift.ts",
            "TestUA",
            None,
            proxy="http://ts-proxy.local:8080",
        )
        self.assertIs(resp, mock_resp)
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(
            kwargs.get("proxies"),
            {
                "http": "http://ts-proxy.local:8080",
                "https": "http://ts-proxy.local:8080",
            },
        )


class EPGSourceProxyTests(TestCase):
    """Tests for EPGSource proxy resolution, serializer persistence, and outbound EPG requests."""

    def setUp(self):
        _set_global_proxy("")

    def tearDown(self):
        _set_global_proxy("")

    def test_epg_source_defaults_to_none_and_inherits_global_proxy(self):
        from apps.epg.models import EPGSource

        source = EPGSource.objects.create(
            name="Standalone XMLTV",
            source_type="xmltv",
            url="http://epg.example.com/guide.xml",
        )
        self.assertIsNone(source.get_effective_proxy())
        self.assertIsNone(source.get_proxies())

        _set_global_proxy("http://global-epg-proxy.local:8080")
        self.assertEqual(
            source.get_effective_proxy(), "http://global-epg-proxy.local:8080"
        )
        self.assertEqual(
            source.get_proxies(),
            {
                "http": "http://global-epg-proxy.local:8080",
                "https": "http://global-epg-proxy.local:8080",
            },
        )

    def test_epg_source_inherits_linked_m3u_account_proxy_and_allows_own_override(self):
        from apps.epg.models import EPGSource

        _set_global_proxy("http://global-proxy.local:8080")
        M3UAccount.objects.create(
            name="My XC Provider",
            account_type=M3UAccount.Types.XC,
            server_url="http://xc.provider.local:8080",
            username="u",
            password="p",
            custom_properties={"proxy": "http://m3u-override.local:8080"},
        )
        source = EPGSource.objects.create(
            name="My XC Provider",
            source_type="xmltv",
            url="http://xc.provider.local:8080/xmltv.php?username=u&password=p",
        )
        # Inherits M3U account override over global default
        self.assertEqual(
            source.get_effective_proxy(), "http://m3u-override.local:8080"
        )

        # Explicit override on EPGSource wins over M3U account override
        source.custom_properties = {"proxy": "socks5://epg-specific.local:1080"}
        source.save(update_fields=["custom_properties"])
        self.assertEqual(
            source.get_effective_proxy(), "socks5://epg-specific.local:1080"
        )

    def test_epg_source_serializer_create_update_and_clear_proxy(self):
        from apps.epg.serializers import EPGSourceSerializer

        serializer = EPGSourceSerializer(
            data={
                "name": "Proxied EPG",
                "source_type": "xmltv",
                "url": "http://epg.example.com/guide.xml",
                "proxy": "  http://epg-proxy.local:8080/  ",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        source = serializer.save()
        self.assertEqual(
            source.custom_properties.get("proxy"),
            "http://epg-proxy.local:8080",
        )
        self.assertEqual(
            EPGSourceSerializer(source).data["proxy"],
            "http://epg-proxy.local:8080",
        )

        # Partial custom_properties update (e.g. auto_apply_epg_logos) preserves proxy
        partial_ser = EPGSourceSerializer(
            source,
            data={"custom_properties": {"auto_apply_epg_logos": True}},
            partial=True,
        )
        self.assertTrue(partial_ser.is_valid(), partial_ser.errors)
        source = partial_ser.save()
        self.assertEqual(
            source.custom_properties.get("proxy"),
            "http://epg-proxy.local:8080",
        )
        self.assertTrue(source.custom_properties.get("auto_apply_epg_logos"))

        # Clearing proxy removes key from custom_properties
        clear_ser = EPGSourceSerializer(
            source,
            data={"proxy": ""},
            partial=True,
        )
        self.assertTrue(clear_ser.is_valid(), clear_ser.errors)
        source = clear_ser.save()
        self.assertNotIn("proxy", source.custom_properties)
        self.assertIsNone(EPGSourceSerializer(source).data["proxy"])

    @patch("apps.epg.tasks.send_epg_update")
    @patch("apps.epg.tasks.requests.get")
    def test_fetch_xmltv_uses_effective_proxy(self, mock_get, _mock_ws):
        from apps.epg.models import EPGSource
        from apps.epg.tasks import fetch_xmltv

        source = EPGSource.objects.create(
            name="XMLTV With Proxy",
            source_type="xmltv",
            url="http://epg.example.com/guide.xml",
            custom_properties={"proxy": "http://xmltv-proxy.local:8080"},
        )
        xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?><tv></tv>'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-length": str(len(xml_bytes))}
        mock_resp.iter_content.return_value = [xml_bytes]
        mock_resp.raw.tell.return_value = len(xml_bytes)
        mock_get.return_value.__enter__.return_value = mock_resp

        result = fetch_xmltv(source)
        self.assertTrue(result)
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(
            kwargs.get("proxies"),
            {
                "http": "http://xmltv-proxy.local:8080",
                "https": "http://xmltv-proxy.local:8080",
            },
        )
        if source.file_path and os.path.exists(source.file_path):
            os.remove(source.file_path)

    @patch("apps.epg.sd_utils.requests.get")
    @patch("apps.epg.sd_utils.requests.post")
    def test_schedules_direct_requests_use_effective_proxy(
        self, mock_post, mock_get
    ):
        from apps.epg.models import EPGSource
        from apps.epg.sd_utils import (
            sd_authorized_request,
            sd_clear_cached_token,
            sd_obtain_token,
        )

        source = EPGSource.objects.create(
            name="SD With Proxy",
            source_type="schedules_direct",
            username="sduser",
            password="sdpass",
            custom_properties={"proxy": "http://sd-proxy.local:8080"},
        )
        sd_clear_cached_token(source.id)
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "code": 0,
                    "token": "tok-proxied",
                    "tokenExpires": 9999999999,
                }
            ),
            raise_for_status=MagicMock(),
            headers={},
            content=b"{}",
        )
        auth = sd_obtain_token(source)
        self.assertTrue(auth.ok)
        _, post_kwargs = mock_post.call_args
        self.assertEqual(
            post_kwargs.get("proxies"),
            {
                "http": "http://sd-proxy.local:8080",
                "https": "http://sd-proxy.local:8080",
            },
        )

        mock_get.return_value = MagicMock(
            status_code=200,
            headers={"Content-Type": "application/json"},
            content=b'{"lineups":[]}',
            json=MagicMock(return_value={"lineups": []}),
        )
        sd_authorized_request(
            "GET",
            "https://json.schedulesdirect.org/20141201/lineups",
            source=source,
            token="tok-proxied",
        )
        _, get_kwargs = mock_get.call_args
        self.assertEqual(
            get_kwargs.get("proxies"),
            {
                "http": "http://sd-proxy.local:8080",
                "https": "http://sd-proxy.local:8080",
            },
        )
        sd_clear_cached_token(source.id)
