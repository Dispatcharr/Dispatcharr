from django.test import SimpleTestCase

from apps.plugins.keys import normalize_plugin_key


class PluginKeyNormalizationTests(SimpleTestCase):
    def test_matches_development_discovery_for_spaces_case_and_hyphens(self):
        self.assertEqual(normalize_plugin_key("Mixed Case"), "mixed_case")
        self.assertEqual(normalize_plugin_key("epg-janitor"), "epg-janitor")
