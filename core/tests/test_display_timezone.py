"""Tests for the UTC source formatter (dispatcharr.display_timezone)."""

import logging

from django.conf import settings
from django.test import SimpleTestCase

from dispatcharr.display_timezone import DisplayTimezoneFormatter

FIXED_EPOCH = 1755500000.0  # 2025-08-18 06:53:20 UTC


def _record():
    record = logging.LogRecord(
        name="core.tests",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="message",
        args=(),
        exc_info=None,
    )
    record.created = FIXED_EPOCH
    record.msecs = 123.0
    return record


class DisplayTimezoneFormatterTests(SimpleTestCase):
    def setUp(self):
        self.formatter = DisplayTimezoneFormatter(
            format="{asctime} {levelname} {name} {message}", style="{"
        )

    def test_stamps_in_utc_regardless_of_process_zone(self):
        self.assertEqual(
            self.formatter.formatTime(_record()), "2025-08-18 06:53:20,123"
        )

    def test_full_record_renders_verbose_format(self):
        self.assertEqual(
            self.formatter.format(_record()),
            "2025-08-18 06:53:20,123 INFO core.tests message",
        )

    def test_custom_datefmt_is_respected(self):
        self.assertEqual(
            self.formatter.formatTime(_record(), datefmt="%H:%M"), "06:53"
        )


class DisplayZoneSeedTests(SimpleTestCase):
    def test_the_migration_seed_source_is_still_defined(self):
        # Migration 0020 seeds the system time zone from this setting; without
        # it every fresh install silently seeds UTC and renders the wrong clock.
        self.assertTrue(getattr(settings, "DISPATCHARR_DISPLAY_TZ", None))
