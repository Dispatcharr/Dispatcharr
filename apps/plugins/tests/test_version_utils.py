"""get_plugin_status() must agree with itself across all callers.

My Plugins, Find Plugins, and the update-notification sweep all delegate to
this single helper; a wrong branch here silently desyncs what those surfaces
report as "up to date" vs "update available".
"""

from django.test import SimpleTestCase

from apps.plugins.version_utils import compare_versions, get_plugin_status


class GetPluginStatusTests(SimpleTestCase):
    def test_not_installed_when_installed_version_is_none(self):
        self.assertEqual(
            get_plugin_status(None, "1.0.0", is_managed=True, is_prerelease=True),
            "not_installed",
        )

    def test_unmanaged_overrides_everything_else(self):
        self.assertEqual(
            get_plugin_status(
                "2.0.0",
                "1.0.0",
                is_managed=False,
                is_prerelease=True,
                has_repo_match=False,
            ),
            "unmanaged",
        )

    def test_different_repo_when_managed_but_no_repo_match(self):
        self.assertEqual(
            get_plugin_status(
                "1.0.0", "2.0.0", is_managed=True, has_repo_match=False
            ),
            "different_repo",
        )

    def test_prerelease_even_if_installed_is_numerically_higher(self):
        self.assertEqual(
            get_plugin_status(
                "2.0.0",
                "1.0.0",
                is_managed=True,
                has_repo_match=True,
                is_prerelease=True,
            ),
            "prerelease",
        )

    def test_up_to_date_when_latest_version_is_falsy(self):
        self.assertEqual(
            get_plugin_status("1.0.0", "", is_managed=True),
            "up_to_date",
        )
        self.assertEqual(
            get_plugin_status("1.0.0", None, is_managed=True),
            "up_to_date",
        )

    def test_up_to_date_on_exact_string_match(self):
        self.assertEqual(
            get_plugin_status("1.0.0", "1.0.0", is_managed=True),
            "up_to_date",
        )

    def test_up_to_date_when_numerically_equal_but_string_differs(self):
        self.assertEqual(
            get_plugin_status("1.0", "1.0.0", is_managed=True),
            "up_to_date",
        )

    def test_non_numeric_versions_always_report_update_available(self):
        self.assertEqual(
            get_plugin_status("1.0.0-beta", "1.0.1", is_managed=True),
            "update_available",
        )
        # Even when installed "looks" newer as a string, non-numeric
        # comparisons carry no direction, so it's still "update_available".
        self.assertEqual(
            get_plugin_status("2.0.0-beta", "1.0.1", is_managed=True),
            "update_available",
        )

    def test_numeric_installed_lower_is_update_available(self):
        self.assertEqual(
            get_plugin_status("1.0.0", "2.0.0", is_managed=True),
            "update_available",
        )

    def test_numeric_installed_higher_is_downgrade_available(self):
        self.assertEqual(
            get_plugin_status("2.0.0", "1.0.0", is_managed=True),
            "downgrade_available",
        )

    def test_v_prefixed_versions_compare_correctly(self):
        self.assertEqual(
            get_plugin_status("v1.0.0", "1.0.0", is_managed=True),
            "up_to_date",
        )
        self.assertEqual(
            get_plugin_status("v1.0.0", "v2.0.0", is_managed=True),
            "update_available",
        )

    def test_differing_segment_counts_report_update_available(self):
        self.assertEqual(
            get_plugin_status("1.2", "1.2.1", is_managed=True),
            "update_available",
        )


class CompareVersionsTests(SimpleTestCase):
    def test_returns_zero_when_either_side_is_falsy(self):
        self.assertEqual(compare_versions("", "1.0.0"), 0)
        self.assertEqual(compare_versions("1.0.0", ""), 0)
        self.assertEqual(compare_versions(None, None), 0)

    def test_numeric_ordering(self):
        self.assertLess(compare_versions("1.0.0", "2.0.0"), 0)
        self.assertGreater(compare_versions("2.0.0", "1.0.0"), 0)
        self.assertEqual(compare_versions("1.0.0", "1.0.0"), 0)

    def test_missing_trailing_segments_treated_as_zero(self):
        self.assertEqual(compare_versions("1.2", "1.2.0"), 0)

    def test_non_numeric_segments_fall_back_to_string_equality(self):
        self.assertEqual(compare_versions("1.0.0-beta", "1.0.0-beta"), 0)
        self.assertEqual(compare_versions("1.0.0-beta", "1.0.0-rc"), 1)
