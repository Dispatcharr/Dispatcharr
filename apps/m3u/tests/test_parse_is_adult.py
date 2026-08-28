"""Unit tests for parse_is_adult helper shared by live and VOD ingest."""

from django.test import SimpleTestCase

from apps.m3u.utils import parse_is_adult


class ParseIsAdultTests(SimpleTestCase):
    def test_truthy_int_and_string(self):
        self.assertTrue(parse_is_adult(1))
        self.assertTrue(parse_is_adult("1"))

    def test_falsy_common_provider_values(self):
        self.assertFalse(parse_is_adult(0))
        self.assertFalse(parse_is_adult("0"))
        self.assertFalse(parse_is_adult(None))
        self.assertFalse(parse_is_adult("None"))
        self.assertFalse(parse_is_adult(""))
        self.assertFalse(parse_is_adult("true"))
        self.assertFalse(parse_is_adult(2))
