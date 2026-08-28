"""DVR captures can be routed through an output profile.

A recording's own ffmpeg runs ``-c copy``, and it fetches the TS proxy
anonymously, so neither the DVR nor a user profile can transcode it. The only
place a recording can be encoded is the proxy's output profile, selected by the
``?output_profile=`` query parameter that ``stream_ts`` already honours.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.channels.tasks import _dvr_capture_url
from core.models import CoreSettings

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
        # with the test transaction — a value stored by one test would otherwise
        # still be readable in the next. Deleting the row fires the post_delete
        # invalidation, so each test starts from the real defaults.
        CoreSettings.objects.filter(key="dvr_settings").delete()

    def _store(self, value):
        CoreSettings._update_group(
            "dvr_settings", "DVR Settings", {"dvr_output_profile_id": value}
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
