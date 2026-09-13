"""DVR captures can be routed through an output profile.

A recording's own ffmpeg runs ``-c copy``, and it fetches the TS proxy
anonymously, so neither the DVR nor a user profile can transcode it. The only
place a recording can be encoded is the proxy's output profile, selected by the
``?output_profile=`` query parameter that ``stream_ts`` already honours.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.channels.tasks import _dvr_capture_url
from core.models import DVR_SETTINGS_KEY, CoreSettings

BASE = "http://127.0.0.1:5656"
UUID = "0f9d1b6e-0000-0000-0000-00000000abcd"
PLAIN = f"{BASE}/proxy/ts/stream/{UUID}"


class DvrCaptureUrlTests(TestCase):
    def test_no_profile_leaves_the_url_untouched(self):
        """The default must be byte-identical to the pre-existing URL."""
        self.assertEqual(_dvr_capture_url(BASE, UUID), PLAIN)
        self.assertEqual(_dvr_capture_url(BASE, UUID, None), PLAIN)

    def test_profile_id_is_appended(self):
        self.assertEqual(
            _dvr_capture_url(BASE, UUID, 6), f"{PLAIN}?output_profile=6"
        )

    def test_zero_is_not_treated_as_a_profile(self):
        """0 is not a valid pk; appending it would resolve to no profile anyway."""
        self.assertEqual(_dvr_capture_url(BASE, UUID, 0), PLAIN)


class DvrOutputProfileSettingTests(TestCase):
    """CoreSettings.get_dvr_output_profile_id coerces whatever is stored."""

    def setUp(self):
        # Settings groups are cached in Redis, and that cache is NOT rolled back
        # with the test transaction. A prior test may have written a value that
        # Redis still holds after the DB row is gone, so deleting alone does not
        # always fire post_delete. Invalidate explicitly, then drop any row.
        CoreSettings.invalidate_group_cache(DVR_SETTINGS_KEY)
        CoreSettings.objects.filter(key=DVR_SETTINGS_KEY).delete()

    def _store(self, value):
        CoreSettings._update_group(
            DVR_SETTINGS_KEY, "DVR Settings", {"output_profile_id": value}
        )

    def test_unset_is_none(self):
        self.assertIsNone(CoreSettings.get_dvr_output_profile_id())

    def test_integer_round_trips(self):
        self._store(6)
        self.assertEqual(CoreSettings.get_dvr_output_profile_id(), 6)

    def test_numeric_string_is_coerced(self):
        """The frontend Select stores ids as strings."""
        self._store("6")
        self.assertEqual(CoreSettings.get_dvr_output_profile_id(), 6)

    def test_unusable_values_fall_back_to_none(self):
        """A bad value must disable the feature, never break scheduling."""
        for bad in ("", "abc", [], {}):
            with self.subTest(stored=bad):
                self._store(bad)
                self.assertIsNone(CoreSettings.get_dvr_output_profile_id())


class DvrCaptureUrlWiringTests(TestCase):
    """The setting actually reaches the URL builder."""

    def test_configured_profile_reaches_the_capture_url(self):
        with patch(
            "core.models.CoreSettings.get_dvr_output_profile_id", return_value=6
        ):
            url = _dvr_capture_url(
                BASE, UUID, CoreSettings.get_dvr_output_profile_id()
            )
        self.assertEqual(url, f"{PLAIN}?output_profile=6")

    def test_run_recording_passes_the_setting_through(self):
        """Guards the call site, which is inside a task too large to invoke here."""
        import inspect

        from apps.channels.tasks import run_recording

        source = inspect.getsource(run_recording)
        self.assertIn("_dvr_capture_url(", source)
        self.assertIn("CoreSettings.get_dvr_output_profile_id()", source)
        self.assertNotIn('f"{base}/proxy/ts/stream/{channel.uuid}"', source)
        self.assertIn("_dvr_ffmpeg_user_agent(", source)


class DvrFfmpegUserAgentTests(TestCase):
    """Redirect captures must talk to the provider with the M3U UA."""

    def setUp(self):
        from django.core.cache import cache

        from apps.channels.models import Channel, ChannelStream, Stream
        from apps.m3u.models import M3UAccount
        from core.models import (
            PROXY_PROFILE_NAME,
            REDIRECT_PROFILE_NAME,
            STREAM_SETTINGS_KEY,
            StreamProfile,
            UserAgent,
        )

        cache.clear()
        CoreSettings.objects.filter(key=STREAM_SETTINGS_KEY).delete()
        CoreSettings.invalidate_default_user_agent_cache()

        self.default_ua = UserAgent.objects.create(
            name="DVR Default UA",
            user_agent="DefaultAgent/1.0",
        )
        self.account_ua = UserAgent.objects.create(
            name="DVR Account UA",
            user_agent="AccountAgent/2.0",
        )
        CoreSettings.objects.create(
            key=STREAM_SETTINGS_KEY,
            name="Stream Settings",
            value={"default_user_agent": self.default_ua.id},
        )

        self.redirect_profile, _ = StreamProfile.objects.get_or_create(
            name=REDIRECT_PROFILE_NAME,
            defaults={
                "command": "",
                "parameters": "",
                "locked": True,
                "is_active": True,
            },
        )
        if not self.redirect_profile.locked:
            self.redirect_profile.locked = True
            self.redirect_profile.save(update_fields=["locked"])
        self.proxy_profile, _ = StreamProfile.objects.get_or_create(
            name=PROXY_PROFILE_NAME,
            defaults={
                "command": "",
                "parameters": "",
                "locked": True,
                "is_active": True,
            },
        )
        if not self.proxy_profile.locked:
            self.proxy_profile.locked = True
            self.proxy_profile.save(update_fields=["locked"])

        self.account = M3UAccount.objects.create(
            name="DVR UA Account",
            server_url="http://example.com",
            user_agent=self.account_ua,
        )
        self.stream = Stream.objects.create(
            name="DVR UA Stream",
            url="http://example.com/live/1.ts",
            m3u_account=self.account,
        )
        self.redirect_channel = Channel.objects.create(
            channel_number=910,
            name="DVR Redirect UA",
            stream_profile=self.redirect_profile,
        )
        ChannelStream.objects.create(
            channel=self.redirect_channel, stream=self.stream, order=0
        )
        self.proxy_channel = Channel.objects.create(
            channel_number=911,
            name="DVR Proxy UA",
            stream_profile=self.proxy_profile,
        )
        ChannelStream.objects.create(
            channel=self.proxy_channel, stream=self.stream, order=0
        )

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()
        CoreSettings.invalidate_default_user_agent_cache()

    def test_proxy_keeps_dispatcharr_dvr_user_agent(self):
        from apps.channels.tasks import _dvr_ffmpeg_user_agent

        self.assertEqual(
            _dvr_ffmpeg_user_agent(self.proxy_channel, 71),
            "Dispatcharr-DVR/recording-71",
        )

    def test_redirect_uses_m3u_account_user_agent(self):
        from apps.channels.tasks import _dvr_ffmpeg_user_agent

        self.assertEqual(
            _dvr_ffmpeg_user_agent(self.redirect_channel, 71),
            "AccountAgent/2.0",
        )

    def test_redirect_falls_back_to_system_default_when_account_has_no_ua(self):
        from apps.channels.tasks import _dvr_ffmpeg_user_agent

        self.account.user_agent = None
        self.account.save(update_fields=["user_agent"])
        self.assertEqual(
            _dvr_ffmpeg_user_agent(self.redirect_channel, 71),
            "DefaultAgent/1.0",
        )

    def test_redirect_skips_inactive_account_for_user_agent(self):
        from apps.channels.models import ChannelStream, Stream
        from apps.channels.tasks import _dvr_ffmpeg_user_agent
        from apps.m3u.models import M3UAccount
        from core.models import UserAgent

        inactive_ua = UserAgent.objects.create(
            name="DVR Inactive UA",
            user_agent="InactiveAgent/9.0",
        )
        inactive_account = M3UAccount.objects.create(
            name="DVR Inactive Account",
            server_url="http://inactive.example.com",
            user_agent=inactive_ua,
            is_active=False,
        )
        inactive_stream = Stream.objects.create(
            name="DVR Inactive Stream",
            url="http://inactive.example.com/live/1.ts",
            m3u_account=inactive_account,
        )
        ChannelStream.objects.filter(channel=self.redirect_channel).update(order=1)
        ChannelStream.objects.create(
            channel=self.redirect_channel, stream=inactive_stream, order=0
        )
        self.assertEqual(
            _dvr_ffmpeg_user_agent(self.redirect_channel, 71),
            "AccountAgent/2.0",
        )

    def test_build_ffmpeg_cmd_accepts_explicit_user_agent(self):
        from apps.channels.tasks import _dvr_build_ffmpeg_cmd

        cmd = _dvr_build_ffmpeg_cmd(
            "http://127.0.0.1:5656/proxy/ts/stream/uuid",
            71,
            "/data/recordings/.dvr_71_hls/index.m3u8",
            "/data/recordings/.dvr_71_hls/seg_%05d.ts",
            0,
            user_agent="AccountAgent/2.0",
        )
        self.assertEqual(cmd[cmd.index("-user_agent") + 1], "AccountAgent/2.0")
        self.assertNotIn("Dispatcharr-DVR/recording-71", cmd)
