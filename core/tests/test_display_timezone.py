"""Log timestamps must render in the configured display timezone."""

import logging
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo
from django.db import ProgrammingError
from django.test import TestCase, override_settings
from core.models import CoreSettings
from dispatcharr import display_timezone
from dispatcharr.display_timezone import DisplayTimezoneFormatter, refresh_display_zone

FIXED_EPOCH = 1784073600.0


def _record():
    record = logging.LogRecord(
        name="test",
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


def _expected(zone_name):
    dt = datetime.fromtimestamp(FIXED_EPOCH, ZoneInfo(zone_name))
    stamp = f"{dt.strftime('%Y-%m-%d %H:%M:%S')},123"
    offset = dt.strftime("%z")
    if offset != "+0000":
        return f"{stamp} {offset}"
    return stamp


class DisplayTimezoneFormatterTests(TestCase):
    def setUp(self):
        self._reset_cache()
        self.addCleanup(self._reset_cache)
        self.formatter = DisplayTimezoneFormatter(
            format="{asctime} {levelname} {name} {message}", style="{"
        )

    @staticmethod
    def _reset_cache():
        display_timezone._cache.update({"zone": None, "checked": 0.0})

    @override_settings(DISPATCHARR_DISPLAY_TZ="Europe/Zurich")
    def test_env_capture_used_before_first_refresh(self):
        self.assertEqual(
            self.formatter.formatTime(_record()), _expected("Europe/Zurich")
        )

    def test_settings_change_refreshes_through_signal(self):
        CoreSettings.set_system_time_zone("Pacific/Auckland")
        self.assertEqual(
            self.formatter.formatTime(_record()), _expected("Pacific/Auckland")
        )

    def test_settings_change_wins_over_stale_cached_read(self):
        CoreSettings.set_system_time_zone("Europe/Zurich")
        with mock.patch.object(
            CoreSettings, "get_system_time_zone", return_value="Europe/Zurich"
        ):
            CoreSettings.set_system_time_zone("Pacific/Auckland")
            self.assertEqual(
                self.formatter.formatTime(_record()), _expected("Pacific/Auckland")
            )

    @override_settings(DISPATCHARR_DISPLAY_TZ="Europe/Zurich")
    def test_database_errors_keep_previous_value(self):
        with mock.patch.object(
            CoreSettings,
            "get_system_time_zone",
            side_effect=ProgrammingError("relation does not exist"),
        ):
            refresh_display_zone(force=True)
        self.assertEqual(
            self.formatter.formatTime(_record()), _expected("Europe/Zurich")
        )

    def test_invalid_stored_zone_keeps_previous_value(self):
        CoreSettings.set_system_time_zone("Pacific/Auckland")
        with mock.patch.object(
            CoreSettings, "get_system_time_zone", return_value="Not/AZone"
        ):
            refresh_display_zone(force=True)
        self.assertEqual(
            self.formatter.formatTime(_record()), _expected("Pacific/Auckland")
        )

    def test_refresh_respects_interval_unless_forced(self):
        CoreSettings.set_system_time_zone("UTC")
        with mock.patch.object(
            CoreSettings, "get_system_time_zone", return_value="Pacific/Auckland"
        ):
            refresh_display_zone()
            self.assertEqual(self.formatter.formatTime(_record()), _expected("UTC"))
            refresh_display_zone(force=True)
            self.assertEqual(
                self.formatter.formatTime(_record()), _expected("Pacific/Auckland")
            )

    def test_custom_datefmt_is_respected(self):
        CoreSettings.set_system_time_zone("Pacific/Auckland")
        expected = datetime.fromtimestamp(
            FIXED_EPOCH, ZoneInfo("Pacific/Auckland")
        ).strftime("%H:%M")
        self.assertEqual(
            self.formatter.formatTime(_record(), datefmt="%H:%M"), expected
        )

    def test_non_utc_stamp_carries_offset(self):
        CoreSettings.set_system_time_zone("Pacific/Auckland")
        stamp = self.formatter.formatTime(_record())
        self.assertRegex(stamp, r" [+-]\d{4}$")

    def test_utc_stamp_has_no_offset(self):
        CoreSettings.set_system_time_zone("UTC")
        stamp = self.formatter.formatTime(_record())
        self.assertNotRegex(stamp, r"[+-]\d{4}$")
