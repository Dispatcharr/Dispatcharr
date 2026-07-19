"""Tests for EPG channel name normalization (prefix/suffix/custom ignore rules)."""
from django.test import TestCase

from apps.channels.epg_matching import (
    build_epg_tvg_id_index,
    clear_normalize_settings_cache,
    normalize_name,
)
from core.models import CoreSettings, EPG_SETTINGS_KEY


class NormalizeNameSettingsTest(TestCase):
    def _set_epg_settings(self, **kwargs):
        obj, _ = CoreSettings.objects.get_or_create(
            key=EPG_SETTINGS_KEY,
            defaults={"name": "EPG Settings", "value": {}},
        )
        current = obj.value if isinstance(obj.value, dict) else {}
        current.update(kwargs)
        obj.value = current
        obj.save()
        clear_normalize_settings_cache()

    def test_default_mode_does_not_apply_ignore_lists(self):
        self._set_epg_settings(
            epg_match_mode="default",
            epg_match_ignore_prefixes=["HD:"],
            epg_match_ignore_suffixes=[" 4K"],
            epg_match_ignore_custom=["Plus"],
        )
        result_default = normalize_name("HD:HBO Plus East 4K")

        self._set_epg_settings(
            epg_match_mode="advanced",
            epg_match_ignore_prefixes=["HD:"],
            epg_match_ignore_suffixes=[" 4K"],
            epg_match_ignore_custom=["Plus"],
        )
        result_advanced = normalize_name("HD:HBO Plus East 4K")

        self.assertNotEqual(result_default, result_advanced)
        self.assertEqual(result_advanced, "hbo")

    def test_advanced_mode_strips_prefix(self):
        self._set_epg_settings(
            epg_match_mode="advanced",
            epg_match_ignore_prefixes=["HD:"],
        )
        self.assertEqual(
            normalize_name("HD:ABC 7 (WXYZ) - Springfield"),
            "abc 7 springfield wxyz",
        )

    def test_advanced_mode_strips_suffix(self):
        self._set_epg_settings(
            epg_match_mode="advanced",
            epg_match_ignore_suffixes=[" 4K"],
        )
        self.assertEqual(
            normalize_name("NBC 5 (KABC) - Metro 4K"),
            "nbc 5 metro kabc",
        )

    def test_advanced_mode_removes_custom_strings(self):
        self._set_epg_settings(
            epg_match_mode="advanced",
            epg_match_ignore_custom=["Plus"],
        )
        self.assertEqual(
            normalize_name("HBO Plus East"),
            "hbo",
        )

    def test_advanced_mode_applies_prefix_suffix_and_custom_in_order(self):
        self._set_epg_settings(
            epg_match_mode="advanced",
            epg_match_ignore_prefixes=["Sling:"],
            epg_match_ignore_suffixes=[" HD"],
            epg_match_ignore_custom=["Plus"],
        )
        self.assertEqual(
            normalize_name("Sling:HBO Plus East HD"),
            "hbo",
        )

    def test_only_first_matching_prefix_is_removed(self):
        self._set_epg_settings(
            epg_match_mode="advanced",
            epg_match_ignore_prefixes=["HD:", "SD:"],
        )
        self.assertEqual(normalize_name("HD:SD:Channel 5"), "sdchannel 5")

    def test_call_sign_preserved_from_original_name(self):
        self._set_epg_settings(epg_match_mode="default")
        self.assertEqual(
            normalize_name("NBC 5 (KABC) - Metro"),
            "nbc 5 metro kabc",
        )

    def test_tvg_id_index_prefers_first_entry_when_catalog_sorted_by_priority(self):
        # Catalog from build_epg_matching_catalog() is highest-priority first.
        epg_data = [
            {"id": 2, "tvg_id": "abc.us", "epg_source_priority": 50, "name": "High"},
            {"id": 1, "tvg_id": "abc.us", "epg_source_priority": 10, "name": "Low"},
        ]
        index = build_epg_tvg_id_index(epg_data)
        self.assertEqual(index["abc.us"]["id"], 2)

    def test_settings_cache_refresh_picks_up_new_rules(self):
        self._set_epg_settings(epg_match_mode="default")
        self.assertEqual(normalize_name("HD:ABC"), "hdabc")

        self._set_epg_settings(
            epg_match_mode="advanced",
            epg_match_ignore_prefixes=["HD:"],
        )
        self.assertEqual(normalize_name("HD:ABC"), "abc")
