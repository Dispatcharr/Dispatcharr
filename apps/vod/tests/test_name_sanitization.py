from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.vod.tasks import apply_vod_name_regex, sanitize_vod_name


class ApplyVodNameRegexTests(SimpleTestCase):
    """Tests for the low-level regex application helper."""

    def test_basic_prefix_removal(self):
        result = apply_vod_name_regex("┃UK┃ The Matrix", r"┃UK┃\s*", "")
        self.assertEqual(result, "The Matrix")

    def test_replace_with_text(self):
        result = apply_vod_name_regex("Hello World", r"World", "Earth")
        self.assertEqual(result, "Hello Earth")

    def test_dollar_sign_in_replace_converted_to_backref(self):
        result = apply_vod_name_regex("abc123", r"(abc)(\d+)", "$1-$2")
        self.assertEqual(result, "abc-123")

    def test_empty_pattern_returns_original(self):
        result = apply_vod_name_regex("Some Name", "", "replacement")
        self.assertEqual(result, "Some Name")

    def test_none_pattern_returns_original(self):
        result = apply_vod_name_regex("Some Name", None, "replacement")
        self.assertEqual(result, "Some Name")

    def test_invalid_regex_returns_original(self):
        result = apply_vod_name_regex("[broken regex", "[broken", "")
        self.assertEqual(result, "[broken regex")

    def test_none_replace_treated_as_empty_string(self):
        result = apply_vod_name_regex("┃UK┃ Movie", r"┃UK┃\s*", None)
        self.assertEqual(result, "Movie")

    def test_unicode_pipe_characters(self):
        result = apply_vod_name_regex("┃NL┃ Film Title", r"┃\w+┃\s*", "")
        self.assertEqual(result, "Film Title")

    def test_no_match_returns_original(self):
        result = apply_vod_name_regex("Clean Title", r"┃UK┃\s*", "")
        self.assertEqual(result, "Clean Title")


class SanitizeVodNameTests(SimpleTestCase):
    """Tests for sanitize_vod_name including collision protection."""

    @staticmethod
    def _make_relation(regex_pattern=None, replace_pattern=None):
        rel = MagicMock()
        custom_props = {}
        if regex_pattern is not None:
            custom_props["name_regex_pattern"] = regex_pattern
        if replace_pattern is not None:
            custom_props["name_replace_pattern"] = replace_pattern
        rel.custom_properties = custom_props or None
        return rel

    def test_sanitizes_name_with_regex(self):
        relation = self._make_relation(regex_pattern=r"┃UK┃\s*", replace_pattern="")
        existing = set()
        result = sanitize_vod_name("┃UK┃ Movie", 2020, relation, existing, has_external_id=False)
        self.assertEqual(result, "Movie")

    def test_no_relation_returns_original(self):
        existing = set()
        result = sanitize_vod_name("Original Name", 2020, None, existing, has_external_id=False)
        self.assertEqual(result, "Original Name")

    def test_no_custom_properties_returns_original(self):
        relation = MagicMock()
        relation.custom_properties = None
        existing = set()
        result = sanitize_vod_name("Original Name", 2020, relation, existing, has_external_id=False)
        self.assertEqual(result, "Original Name")

    def test_collision_within_batch_keeps_original_for_second(self):
        relation = self._make_relation(regex_pattern=r"┃\w+┃\s*", replace_pattern="")
        existing = set()

        first = sanitize_vod_name("┃UK┃ Same Movie", 2023, relation, existing, has_external_id=False)
        self.assertEqual(first, "Same Movie")

        second = sanitize_vod_name("┃NL┃ Same Movie", 2023, relation, existing, has_external_id=False)
        self.assertEqual(second, "┃NL┃ Same Movie")

    def test_collision_with_existing_db_entry_keeps_original(self):
        relation = self._make_relation(regex_pattern=r"PREFIX\s*", replace_pattern="")
        existing = {("Already Exists", 2021)}

        result = sanitize_vod_name("PREFIX Already Exists", 2021, relation, existing, has_external_id=False)
        self.assertEqual(result, "PREFIX Already Exists")

    def test_entries_with_external_id_skip_collision_guard(self):
        relation = self._make_relation(regex_pattern=r"TAG\s*", replace_pattern="")
        existing = {("Same Name", 2020)}

        result = sanitize_vod_name("TAG Same Name", 2020, relation, existing, has_external_id=True)
        self.assertEqual(result, "Same Name")

    def test_no_id_entries_tracked_in_existing_set(self):
        relation = self._make_relation(regex_pattern=r"X\s*", replace_pattern="")
        existing = set()

        sanitize_vod_name("X Movie A", 2020, relation, existing, has_external_id=False)
        self.assertIn(("Movie A", 2020), existing)

    def test_external_id_entries_not_tracked_in_existing_set(self):
        relation = self._make_relation(regex_pattern=r"X\s*", replace_pattern="")
        existing = set()

        sanitize_vod_name("X Movie A", 2020, relation, existing, has_external_id=True)
        self.assertNotIn(("Movie A", 2020), existing)

    def test_different_years_do_not_collide(self):
        relation = self._make_relation(regex_pattern=r"┃UK┃\s*", replace_pattern="")
        existing = set()

        first = sanitize_vod_name("┃UK┃ Movie", 2020, relation, existing, has_external_id=False)
        second = sanitize_vod_name("┃UK┃ Movie", 2021, relation, existing, has_external_id=False)

        self.assertEqual(first, "Movie")
        self.assertEqual(second, "Movie")

    def test_invalid_regex_returns_original(self):
        relation = self._make_relation(regex_pattern=r"[invalid", replace_pattern="")
        existing = set()

        result = sanitize_vod_name("[invalid Movie", 2020, relation, existing, has_external_id=False)
        self.assertEqual(result, "[invalid Movie")
