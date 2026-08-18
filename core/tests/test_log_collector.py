"""Tests for the merged-output log collector (dispatcharr.log_collector)."""

import io
import os
import shutil
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from core.models import CoreSettings, SYSTEM_SETTINGS_KEY
from dispatcharr import log_collector
from dispatcharr.log_collector import Collector


def _upper_filter(line):
    return line.upper()


def _drop_secret_filter(line):
    return None if "secret" in line else line


class ConfTests(SimpleTestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="dispatcharr-collector-")
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)

    def test_conf_round_trip(self):
        log_collector.write_conf(self.log_dir, False, 42, 7, "a.b:c")
        conf = log_collector.read_conf(self.log_dir)
        self.assertEqual(
            conf, {"persist": False, "max_mb": 42, "keep": 7, "filters": "a.b:c"}
        )

    def test_conf_clamps_garbage(self):
        with open(log_collector.conf_path(self.log_dir), "w") as f:
            f.write("persist=1\nmax_mb=99999\nkeep=abc\n")
        conf = log_collector.read_conf(self.log_dir)
        self.assertEqual(conf["max_mb"], 1000)
        self.assertEqual(conf["keep"], 5)
        self.assertTrue(conf["persist"])

    def test_missing_conf_gives_defaults(self):
        self.assertEqual(log_collector.read_conf(self.log_dir), log_collector._DEFAULT_CONF)

    def test_load_filters_skips_broken_specs(self):
        filters = log_collector.load_filters(
            "core.tests.test_log_collector:_upper_filter,nope.missing:fn"
        )
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]("x"), "X")


class CollectorTests(SimpleTestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="dispatcharr-collector-")
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)
        self.forward_path = os.path.join(self.log_dir, "forward.out")
        self.forward_fd = os.open(
            self.forward_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND
        )
        self.addCleanup(self._close_forward)
        self.collector = Collector(self.log_dir, out_fd=self.forward_fd)
        self.collector._reload = False  # tests configure conf directly
        self.addCleanup(self.collector._close_fd)

    def _close_forward(self):
        try:
            os.close(self.forward_fd)
        except OSError:
            pass

    def read_forward(self):
        with open(self.forward_path, encoding="utf-8") as f:
            return f.read()

    def feed(self, *lines):
        self.collector.reader(io.BytesIO(b"".join(lines)))
        self.collector._stop = False  # tests simulate a still-open stream

    def read_log(self, name=log_collector.LIVE_NAME):
        try:
            with open(os.path.join(self.log_dir, name), encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def test_lines_reach_the_file_in_order(self):
        self.feed(b"one\n", b"two\n")
        self.collector._drain()
        self.assertEqual(self.read_log(), "one\ntwo\n")

    def test_drop_oldest_past_budget_writes_exact_marker(self):
        with mock.patch.object(log_collector, "_BUFFER_BYTES", 8):
            self.feed(b"aaaa\n", b"bbbb\n", b"cccc\n")
        self.collector._drain()
        content = self.read_log()
        self.assertNotIn("aaaa", content)
        self.assertNotIn("bbbb", content)
        self.assertIn("cccc", content)
        self.assertIn("2 log lines dropped", content)

    def test_write_failure_requeues_and_folds_marker(self):
        with mock.patch.object(log_collector, "_BUFFER_BYTES", 8):
            self.feed(b"aaaa\n", b"bbbb\n", b"cccc\n")
        with mock.patch.object(log_collector.os, "write", side_effect=OSError):
            with self.assertRaises(OSError):
                self.collector._drain()
        self.assertEqual(self.collector._dropped, 2)
        self.collector._drain()
        content = self.read_log()
        self.assertEqual(content.count("log lines dropped"), 1)
        self.assertIn("2 log lines dropped", content)

    def test_persist_off_drains_without_filing(self):
        self.collector.conf["persist"] = False
        self.feed(b"discarded\n")
        self.collector._drain()
        self.assertEqual(self.read_log(), "")
        self.assertEqual(self.collector._buf_bytes, 0)

    def test_filter_can_rewrite_and_drop_lines(self):
        self.collector.filters = [_drop_secret_filter, _upper_filter]
        self.feed(b"keep me\n", b"a secret line\n")
        self.collector._drain()
        self.assertEqual(self.read_log(), "KEEP ME\n")

    def test_broken_filter_passes_line_through(self):
        self.collector.filters = [lambda line: 1 / 0]
        self.feed(b"survives\n")
        self.collector._drain()
        self.assertEqual(self.read_log(), "survives\n")

    def test_rotation_at_cap_shifts_and_prunes(self):
        self.collector.conf.update({"max_mb": 1, "keep": 2})
        with open(self.collector.live_path, "w") as f:
            f.write("x" * (1024 * 1024 + 1))
        for n in (1, 2):
            with open(f"{self.collector.live_path}.{n}", "w") as f:
                f.write(f"old {n}")
        self.collector._maybe_rotate()
        self.assertEqual(self.read_log(), "")
        self.assertIn("x", self.read_log(log_collector.LIVE_NAME + ".1"))
        self.assertEqual(self.read_log(log_collector.LIVE_NAME + ".2"), "old 1")
        self.assertFalse(
            os.path.exists(os.path.join(self.log_dir, log_collector.LIVE_NAME + ".3"))
        )

    def test_force_rotate_rotates_below_cap(self):
        self.feed(b"some content\n")
        self.collector._drain()
        self.collector._force_rotate = True
        self.collector._drain()
        self.assertEqual(self.read_log(), "")
        self.assertIn("some content", self.read_log(log_collector.LIVE_NAME + ".1"))

    def test_reopens_when_live_file_deleted(self):
        self.feed(b"before\n")
        self.collector._drain()
        os.remove(self.collector.live_path)
        self.feed(b"after\n")
        self.collector._drain()
        self.assertEqual(self.read_log(), "after\n")

    def test_reader_eof_requests_stop(self):
        self.collector.reader(io.BytesIO(b"line\n"))
        self.assertTrue(self.collector._stop)

    def test_forwarded_stream_gets_filtered_lines(self):
        self.collector.filters = [_upper_filter]
        self.feed(b"masked?\n")
        self.assertEqual(self.read_forward(), "MASKED?\n")
        self.collector._drain()
        self.assertEqual(self.read_log(), "MASKED?\n")

    def test_filter_none_drops_from_both_sinks(self):
        self.collector.filters = [_drop_secret_filter]
        self.feed(b"public\n", b"a secret line\n")
        self.collector._drain()
        self.assertNotIn("secret", self.read_forward())
        self.assertNotIn("secret", self.read_log())

    def test_persist_off_still_forwards(self):
        self.collector.conf["persist"] = False
        self.feed(b"stdout only\n")
        self.collector._drain()
        self.assertEqual(self.read_forward(), "stdout only\n")
        self.assertEqual(self.read_log(), "")

    def test_slow_filter_latches_off(self):
        self.collector.filters = [_upper_filter]
        with mock.patch.object(log_collector, "_FILTER_BUDGET_SECONDS", -1.0):
            self.feed(b"one\n", b"two\n", b"three\n", b"four\n")
        self.assertTrue(self.collector._filters_broken)
        self.assertTrue(self.read_forward().endswith("four\n"))
        self.collector._drain()
        self.assertIn("filters disabled", self.read_log())

    def test_dropped_marker_is_file_only(self):
        with mock.patch.object(log_collector, "_BUFFER_BYTES", 8):
            self.feed(b"aaaa\n", b"bbbb\n", b"cccc\n")
        self.collector._drain()
        forward = self.read_forward()
        self.assertIn("aaaa", forward)
        self.assertIn("cccc", forward)
        self.assertNotIn("dropped", forward)
        self.assertIn("2 log lines dropped", self.read_log())

    def test_prune_runs_on_conf_apply(self):
        for n in (1, 2, 9):
            with open(f"{self.collector.live_path}.{n}", "w") as f:
                f.write("old")
        log_collector.write_conf(self.log_dir, True, 10, 2)
        self.collector._apply_conf()
        names = sorted(self.collector._archive_indices())
        self.assertEqual(names, [1, 2])

    def test_marker_defers_while_tail_open(self):
        # A dropped-lines marker must never splice into an unterminated line.
        self.collector._tail_open = True
        with mock.patch.object(log_collector, "_BUFFER_BYTES", 8):
            self.feed(b"aaaa\n", b"bbbb\n", b"cccc")
        self.collector._drain()
        self.assertEqual(self.read_log(), "cccc")
        self.assertEqual(self.collector._dropped, 2)
        self.feed(b" end\n")
        self.collector._drain()
        content = self.read_log()
        self.assertIn("cccc end\n", content)
        self.assertIn("2 log lines dropped", content)


class ApplySettingsTests(SimpleTestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="dispatcharr-collector-")
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)

    def test_settings_round_trip_to_conf(self):
        with mock.patch.object(log_collector, "signal_reload") as reload_sig:
            log_collector.apply_settings(
                self.log_dir,
                {"log_persist": False, "log_max_mb": 25, "log_keep": 3},
            )
        reload_sig.assert_called_once_with(self.log_dir)
        conf = log_collector.read_conf(self.log_dir)
        self.assertEqual(
            conf, {"persist": False, "max_mb": 25, "keep": 3, "filters": ""}
        )

    def test_modular_mode_is_a_no_op(self):
        with mock.patch.dict(log_collector.os.environ, {"DISPATCHARR_ENV": "modular"}):
            log_collector.apply_settings(self.log_dir, {"log_persist": False})
        self.assertFalse(os.path.exists(log_collector.conf_path(self.log_dir)))

    def test_signal_reload_refuses_recycled_pids(self):
        with open(log_collector.pid_path(self.log_dir), "w") as f:
            f.write(str(os.getpid()))
        opened = {"proc": False}
        real_open = open

        def fake_open(path, *args, **kwargs):
            if str(path).startswith("/proc/"):
                opened["proc"] = True
                return io.BytesIO(b"python\x00-m\x00something_else\x00")
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=fake_open):
            with mock.patch.object(log_collector.os, "kill") as kill:
                log_collector.signal_reload(self.log_dir)
        if hasattr(log_collector.signal, "SIGHUP"):
            self.assertTrue(opened["proc"])
            kill.assert_not_called()

# locmem cache: isolates this test's settings write from the shared Redis-backed group cache.
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "log-collector-receiver-tests",
        }
    }
)
class ReceiverTests(TestCase):
    def test_saving_system_settings_writes_conf(self):
        log_dir = tempfile.mkdtemp(prefix="dispatcharr-collector-")
        self.addCleanup(shutil.rmtree, log_dir, ignore_errors=True)
        inst, _ = CoreSettings.objects.get_or_create(
            key=SYSTEM_SETTINGS_KEY, defaults={"value": {}}
        )
        with override_settings(LOG_FILE_DIR=log_dir):
            inst.value = {"log_persist": False, "log_max_mb": 20, "log_keep": 4}
            inst.save()
        conf = log_collector.read_conf(log_dir)
        self.assertEqual(
            conf, {"persist": False, "max_mb": 20, "keep": 4, "filters": ""}
        )
