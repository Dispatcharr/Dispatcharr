import unittest

from apps.vod.utils import parse_category_filter_value


class ParseCategoryFilterValueTests(unittest.TestCase):
    VALID_TYPES = {"movie", "series"}

    def test_plain_name_without_pipe(self):
        self.assertEqual(
            parse_category_filter_value("Documentaries", self.VALID_TYPES),
            ("Documentaries", None),
        )

    def test_name_and_type(self):
        self.assertEqual(
            parse_category_filter_value("Action|movie", self.VALID_TYPES),
            ("Action", "movie"),
        )

    def test_name_containing_pipe_is_not_mis_split(self):
        # A category whose name contains '|' and has no type suffix must not be split (#1603).
        self.assertEqual(
            parse_category_filter_value("|EN| 4K CLASSIC MOVIES", self.VALID_TYPES),
            ("|EN| 4K CLASSIC MOVIES", None),
        )

    def test_name_containing_pipe_with_type_suffix(self):
        # The trailing token is a real type, so only the last '|' separates name from type.
        self.assertEqual(
            parse_category_filter_value("|EN| 4K CLASSIC MOVIES|movie", self.VALID_TYPES),
            ("|EN| 4K CLASSIC MOVIES", "movie"),
        )
