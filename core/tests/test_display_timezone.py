"""Tests for the source formatter (dispatcharr.display_timezone)."""

import logging
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from dispatcharr import display_timezone
from dispatcharr.display_timezone import DisplayTimezoneFormatter, set_display_zone

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


# Pin the pre-database fallback: without this the container's own TZ can equal the
# zone under test, and a cleared cache would go unnoticed.
@override_settings(DISPATCHARR_DISPLAY_TZ="UTC")
class ModularFormatterTests(SimpleTestCase):
    """Without a collector in front, the formatter renders the display zone itself."""

    def setUp(self):
        self.formatter = DisplayTimezoneFormatter(
            format="{asctime} {levelname} {name} {message}", style="{"
        )
        self._saved = dict(display_timezone._cache)
        self.addCleanup(display_timezone._cache.update, self._saved)

    def _modular(self):
        return mock.patch.dict("os.environ", {"DISPATCHARR_ENV": "modular"})

    def _aio(self):
        return mock.patch.dict("os.environ", {"DISPATCHARR_ENV": "aio"})

    def test_modular_stamps_the_display_zone_not_utc(self):
        set_display_zone("Pacific/Auckland")
        with self._modular():
            self.assertEqual(
                self.formatter.formatTime(_record()), "2025-08-18 18:53:20,123"
            )

    def test_a_collector_in_front_keeps_the_stamp_utc(self):
        set_display_zone("Pacific/Auckland")
        with self._aio():
            self.assertEqual(
                self.formatter.formatTime(_record()), "2025-08-18 06:53:20,123"
            )

    def test_the_zone_follows_the_saved_setting(self):
        with self._modular():
            set_display_zone("America/New_York")
            first = self.formatter.formatTime(_record())
            set_display_zone("Pacific/Auckland")
            self.assertNotEqual(first, self.formatter.formatTime(_record()))

    def test_an_invalid_zone_keeps_the_previous_one(self):
        set_display_zone("Pacific/Auckland")
        set_display_zone("Not/AZone")
        with self._modular():
            self.assertEqual(
                self.formatter.formatTime(_record()), "2025-08-18 18:53:20,123"
            )

    def test_modular_leaves_multi_line_records_unindented(self):
        record = _record()
        record.msg = "first\nsecond"
        with self._modular():
            self.assertIn("\nsecond", self.formatter.format(record))

    def test_a_collector_in_front_indents_continuations(self):
        record = _record()
        record.msg = "first\nsecond"
        with self._aio():
            self.assertIn("\n second", self.formatter.format(record))


class DisplayZoneSeedTests(SimpleTestCase):
    def test_the_migration_seed_source_is_still_defined(self):
        # Migration 0020 seeds the system time zone from this setting.
        self.assertTrue(getattr(settings, "DISPATCHARR_DISPLAY_TZ", None))
