from datetime import datetime, timezone

from django.test import SimpleTestCase

from core.tasks import parse_build_timestamp


class BuildTimestampTests(SimpleTestCase):
    def test_parses_compact_ci_timestamp(self):
        self.assertEqual(
            parse_build_timestamp("20261021212756"),
            datetime(2026, 10, 21, 21, 27, 56, tzinfo=timezone.utc),
        )

    def test_parses_iso_timestamp(self):
        self.assertEqual(
            parse_build_timestamp("2026-10-21T21:27:56Z"),
            datetime(2026, 10, 21, 21, 27, 56, tzinfo=timezone.utc),
        )
