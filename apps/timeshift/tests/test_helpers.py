"""Tests for `apps.timeshift.helpers` — timestamp shape conversion and URL build."""

from django.test import TestCase

from apps.timeshift.helpers import (
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    format_timestamp_as_sql_datetime,
)


class _FakeAccount:
    def __init__(self):
        self.server_url = "http://example.test"
        self.username = "user"
        self.password = "pass"


class TimestampFormatTests(TestCase):
    """The SQL-datetime shape is needed for some XC server parsers. The
    reshape function changes format only — no timezone conversion."""

    def test_format_sql_reshapes_without_tz_conversion(self):
        # Must reshape only — no timezone shift. The value stays as-is.
        self.assertEqual(
            format_timestamp_as_sql_datetime("2026-05-12:17-00"),
            "2026-05-12 17:00:00",
        )

    def test_format_sql_invalid_falls_back(self):
        self.assertEqual(format_timestamp_as_sql_datetime("garbage"), "garbage")


class BuildTimeshiftUrlTests(TestCase):
    def setUp(self):
        self.account = _FakeAccount()

    def test_format_a_passes_dash_shape_unchanged(self):
        url = build_timeshift_url_format_a(
            self.account, "22372", "2026-05-12:19-00", 40
        )
        self.assertIn("start=2026-05-12:19-00", url)
        self.assertIn("stream=22372", url)
        self.assertIn("duration=40", url)

    def test_format_a_passes_sql_shape_unchanged(self):
        url = build_timeshift_url_format_a(
            self.account, "22372", "2026-05-12 19:00:00", 40
        )
        self.assertIn("start=2026-05-12 19:00:00", url)

    def test_format_b_path_with_dash_shape(self):
        url = build_timeshift_url_format_b(
            self.account, "22372", "2026-05-12:19-00", 40
        )
        self.assertIn("/40/2026-05-12:19-00/22372.ts", url)
