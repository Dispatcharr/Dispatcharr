"""Startup output must land in the collector's canonical grammar."""

import contextlib
import io
import logging

from django.test import SimpleTestCase

from dispatcharr import log_collector
from django.conf import settings

from dispatcharr.startup_log import DisplayTimezoneFormatter, startup_log


class StartupLogTests(SimpleTestCase):
    def test_startup_log_matches_the_collector_python_shape(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            startup_log("Redis TLS: disabled")
        line = buf.getvalue().rstrip("\n")
        self.assertRegex(line.encode(), log_collector._PY)
        self.assertTrue(line.endswith(" INFO dispatcharr.startup Redis TLS: disabled"))

    def test_startup_log_carries_a_caller_level_and_source(self):
        # A warning printed before logging exists must not arrive as INFO stdout.
        buf = io.StringIO()
        startup_log(
            "gevent-early-monkey-patch did not run.",
            level="WARNING",
            source="dispatcharr.gevent_patch",
            stream=buf,
        )
        line = buf.getvalue().rstrip("\n")
        self.assertRegex(line.encode(), log_collector._PY)
        self.assertTrue(
            line.endswith(
                " WARNING dispatcharr.gevent_patch gevent-early-monkey-patch did not run."
            )
        )

    def test_canonical_formatter_matches_the_collector_python_shape(self):
        record = logging.LogRecord(
            "celery.utils.functional",
            logging.DEBUG,
            __file__,
            1,
            "def xstarmap(task, it): return 1",
            None,
            None,
        )
        line = DisplayTimezoneFormatter().format(record)
        self.assertRegex(line.encode(), log_collector._PY)

    def test_multiline_messages_keep_their_tail_as_continuations(self):
        # celery's FUNHEAD_TEMPLATE starts with a newline; an unindented tail arrives as stdout.
        record = logging.LogRecord(
            "celery.utils.functional",
            logging.DEBUG,
            __file__,
            1,
            "\ndef xstarmap(task, it):\n    return 1\n",
            None,
            None,
        )
        lines = DisplayTimezoneFormatter().format(record).split("\n")
        for tail in lines[1:]:
            self.assertTrue(tail == "" or tail.startswith(" "))
        self.assertIn("def xstarmap(task, it):", lines[1])

    def test_formatter_stamps_in_utc_regardless_of_process_zone(self):
        record = logging.LogRecord(
            "core.tests", logging.INFO, __file__, 1, "message", None, None
        )
        record.created = 1755500000.0
        record.msecs = 123.0
        self.assertEqual(
            DisplayTimezoneFormatter().format(record),
            "2025-08-18 06:53:20,123 INFO core.tests message",
        )

    def test_the_migration_seed_source_is_still_defined(self):
        # Migration 0020 seeds the system time zone from this setting.
        self.assertTrue(getattr(settings, "DISPATCHARR_DISPLAY_TZ", None))
