"""Startup output must land in the collector's canonical grammar."""

import contextlib
import io
import logging

from django.test import SimpleTestCase

from dispatcharr import log_collector
from dispatcharr.startup_log import canonical_formatter, startup_log


class StartupLogTests(SimpleTestCase):
    def test_startup_log_matches_the_collector_python_shape(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            startup_log("Redis TLS: disabled")
        line = buf.getvalue().rstrip("\n")
        self.assertRegex(line.encode(), log_collector._PY)
        self.assertTrue(line.endswith(" INFO dispatcharr.startup Redis TLS: disabled"))

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
        line = canonical_formatter().format(record)
        self.assertRegex(line.encode(), log_collector._PY)

    def test_multiline_messages_keep_their_tail_as_continuations(self):
        # celery's FUNHEAD_TEMPLATE starts with a newline; every tail line must
        # be indented or the collector stamps it as an unattributed stdout record.
        record = logging.LogRecord(
            "celery.utils.functional",
            logging.DEBUG,
            __file__,
            1,
            "\ndef xstarmap(task, it):\n    return 1\n",
            None,
            None,
        )
        lines = canonical_formatter().format(record).split("\n")
        for tail in lines[1:]:
            self.assertTrue(tail == "" or tail.startswith(" "))
        self.assertIn("def xstarmap(task, it):", lines[1])
