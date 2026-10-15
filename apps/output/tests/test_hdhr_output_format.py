"""HDHR lineup stream URLs pin their own output format.

Most HDHR clients expect MPEG-TS from a tuner URL, so
the lineup must not inherit the global Default Output Format.
"""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.test import TestCase

from apps.channels.models import Channel, ChannelGroup
from core.models import CoreSettings, OutputProfile, STREAM_SETTINGS_KEY


def _set_stream_settings(**values):
    obj, _ = CoreSettings.objects.get_or_create(
        key=STREAM_SETTINGS_KEY,
        defaults={"name": "Stream Settings", "value": {}},
    )
    current = obj.value if isinstance(obj.value, dict) else {}
    current.update(values)
    obj.value = current
    obj.save()


class HDHROutputFormatSettingTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_defaults_to_mpegts_when_unset(self):
        CoreSettings.objects.filter(key=STREAM_SETTINGS_KEY).delete()
        self.assertEqual(CoreSettings.get_hdhr_output_format(), "mpegts")

    def test_defaults_to_mpegts_when_key_missing(self):
        _set_stream_settings(default_output_format="fmp4")
        settings = CoreSettings.objects.get(key=STREAM_SETTINGS_KEY)
        settings.value.pop("hdhr_output_format", None)
        settings.save()
        self.assertEqual(CoreSettings.get_hdhr_output_format(), "mpegts")

    def test_returns_fmp4_when_configured(self):
        _set_stream_settings(hdhr_output_format="fmp4")
        self.assertEqual(CoreSettings.get_hdhr_output_format(), "fmp4")

    def test_invalid_values_fall_back_to_mpegts(self):
        for bad in ("hls", "", None, "garbage", 5):
            with self.subTest(value=bad):
                _set_stream_settings(hdhr_output_format=bad)
                self.assertEqual(CoreSettings.get_hdhr_output_format(), "mpegts")

    def test_independent_of_default_output_format(self):
        _set_stream_settings(
            default_output_format="fmp4", hdhr_output_format="mpegts"
        )
        self.assertEqual(CoreSettings.get_default_output_format(), "fmp4")
        self.assertEqual(CoreSettings.get_hdhr_output_format(), "mpegts")


class HDHRLineupOutputFormatTests(TestCase):
    def setUp(self):
        cache.clear()
        self._network_patch = patch(
            "apps.hdhr.api_views.network_access_allowed", return_value=True
        )
        self._network_patch.start()
        group = ChannelGroup.objects.create(name="HDHR Format Group")
        self.channel = Channel.objects.create(
            name="HDHR Format Channel", channel_number=7, channel_group=group
        )
        self.profile = OutputProfile.objects.create(
            name="HDHR Format Profile",
            command="ffmpeg",
            parameters="-i pipe:0 -c copy -f mpegts pipe:1",
            locked=False,
        )

    def tearDown(self):
        self._network_patch.stop()
        cache.clear()

    def _lineup_query(self, path="/hdhr/lineup.json"):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        entries = [e for e in response.json() if e["GuideNumber"] == "7"]
        self.assertEqual(len(entries), 1)
        url = urlparse(entries[0]["URL"])
        self.assertTrue(url.path.endswith(f"/proxy/ts/stream/{self.channel.uuid}"))
        return parse_qs(url.query)

    def test_lineup_uses_mpegts_even_when_global_default_is_fmp4(self):
        _set_stream_settings(default_output_format="fmp4")
        query = self._lineup_query()
        self.assertEqual(query.get("output_format"), ["mpegts"])
        self.assertNotIn("output_profile", query)

    def test_lineup_honours_fmp4_hdhr_format(self):
        _set_stream_settings(
            default_output_format="mpegts", hdhr_output_format="fmp4"
        )
        query = self._lineup_query()
        self.assertEqual(query.get("output_format"), ["fmp4"])

    def test_lineup_combines_default_output_profile_and_format(self):
        _set_stream_settings(
            default_output_format="fmp4",
            hdhr_output_profile_id=self.profile.id,
            hdhr_output_format="mpegts",
        )
        query = self._lineup_query()
        self.assertEqual(query.get("output_profile"), [str(self.profile.id)])
        self.assertEqual(query.get("output_format"), ["mpegts"])

    def test_lineup_with_url_output_profile_keeps_format(self):
        _set_stream_settings(default_output_format="fmp4")
        query = self._lineup_query(
            f"/hdhr/output_profile/{self.profile.id}/lineup.json"
        )
        self.assertEqual(query.get("output_profile"), [str(self.profile.id)])
        self.assertEqual(query.get("output_format"), ["mpegts"])
