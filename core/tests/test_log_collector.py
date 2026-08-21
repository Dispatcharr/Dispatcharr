"""Tests for the merged-output log collector (dispatcharr.log_collector)."""

import io
import os
import re
import shutil
import tempfile
from datetime import timezone
from unittest import mock
from zoneinfo import ZoneInfo

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
        log_collector.write_conf(
            self.log_dir, False, 42, 7, "a.b:c", "Pacific/Auckland", "DEBUG"
        )
        conf = log_collector.read_conf(self.log_dir)
        self.assertEqual(
            conf,
            {
                "persist": False,
                "max_mb": 42,
                "keep": 7,
                "filters": "a.b:c",
                "time_zone": "Pacific/Auckland",
                "level": "DEBUG",
            },
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

    @staticmethod
    def strip_stamps(text):
        # Case-insensitive so uppercasing filters still strip the arrival tokens.
        return re.sub(
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}(?: [+-]\d{4})? (?:INFO stdout )?",
            "",
            text,
            flags=re.M | re.I,
        )

    def test_lines_reach_the_file_in_order(self):
        self.feed(b"one\n", b"two\n")
        self.collector._drain()
        self.assertEqual(self.strip_stamps(self.read_log()), "one\ntwo\n")

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
        self.assertEqual(self.strip_stamps(self.read_log()), "KEEP ME\n")

    def test_broken_filter_passes_line_through(self):
        self.collector.filters = [lambda line: 1 / 0]
        self.feed(b"survives\n")
        self.collector._drain()
        self.assertEqual(self.strip_stamps(self.read_log()), "survives\n")

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
        self.assertEqual(self.strip_stamps(self.read_log()), "after\n")

    def test_reader_eof_requests_stop(self):
        self.collector.reader(io.BytesIO(b"line\n"))
        self.assertTrue(self.collector._stop)

    def test_forwarded_stream_gets_filtered_lines(self):
        self.collector.filters = [_upper_filter]
        self.feed(b"masked?\n")
        self.assertEqual(self.strip_stamps(self.read_forward()), "MASKED?\n")
        self.collector._drain()
        self.assertEqual(self.strip_stamps(self.read_log()), "MASKED?\n")

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
        self.assertEqual(self.strip_stamps(self.read_forward()), "stdout only\n")
        self.assertEqual(self.read_log(), "")

    def test_slow_filter_latches_off(self):
        self.collector.filters = [_upper_filter]
        with mock.patch.object(log_collector, "_FILTER_BUDGET_SECONDS", -1.0):
            self.feed(b"one\n", b"two\n", b"three\n", b"four\n")
        self.assertTrue(self.collector._filters_broken)
        self.assertTrue(self.read_forward().endswith("four\n"))
        self.collector._drain()
        self.assertIn("filters disabled", self.read_log())

    def test_oversize_line_chunks_are_not_stamped_mid_line(self):
        big = b"x" * (log_collector._MAX_LINE_BYTES + 100)
        self.feed(big + b"\n")
        forward = self.read_forward()
        # One stamp at the front, none spliced at the chunk boundary.
        self.assertEqual(len(re.findall(r"\d{4}-\d{2}-\d{2} ", forward)), 1)
        self.assertIn("x" * 200, forward)

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

    def test_level_gate_drops_below_floor_from_both_sinks(self):
        self.collector._min_rank = 20
        self.feed(
            b"2026-08-18 01:00:00,100 DEBUG core.utils noisy\n",
            b"2026-08-18 01:00:00,200 INFO core.utils kept\n",
        )
        self.collector._drain()
        for content in (self.read_log(), self.read_forward()):
            self.assertNotIn("noisy", content)
            self.assertIn("kept", content)

    def test_level_gate_suppresses_continuations_with_their_record(self):
        self.collector._min_rank = 20
        self.feed(
            b"2026-08-18 01:00:00,100 DEBUG core.utils noisy\n",
            b"  noisy detail\n",
            b"2026-08-18 01:00:00,200 ERROR core.utils boom\n",
            b"  boom detail\n",
        )
        self.collector._drain()
        content = self.read_log()
        self.assertNotIn("noisy", content)
        self.assertIn("boom\n", content)
        self.assertIn("  boom detail\n", content)

    def test_level_gate_keeps_whole_traceback_with_its_record(self):
        # The tail lines sit at column 0, so only an open traceback keeps them
        # attached to the ERROR they belong to.
        self.collector._min_rank = 40
        self.feed(
            b"2026-08-18 01:00:00,100 ERROR apps.channels refresh failed\n",
            b"Traceback (most recent call last):\n",
            b'  File "/app/x.py", line 1, in run\n',
            b"ValueError: bad m3u\n",
            b"\n",
            b"During handling of the above exception, another exception occurred:\n",
            b"Traceback (most recent call last):\n",
            b"RuntimeError: boom\n",
        )
        self.collector._drain()
        for content in (self.read_log(), self.read_forward()):
            self.assertIn("ValueError: bad m3u", content)
            self.assertIn("During handling of the above exception", content)
            self.assertIn("RuntimeError: boom", content)

    def test_level_gate_releases_after_a_traceback_ends(self):
        # The stdout line lands after a suppressed record: it is judged on its
        # own INFO token, not left inheriting the traceback's record.
        self.collector._min_rank = 20
        self.feed(
            b"2026-08-18 01:00:00,100 ERROR apps.channels refresh failed\n",
            b"Traceback (most recent call last):\n",
            b"ValueError: bad m3u\n",
            b"2026-08-18 01:00:00,200 DEBUG core.utils quiet\n",
            b"plain stdout line\n",
        )
        self.collector._drain()
        content = self.read_log()
        self.assertNotIn("quiet", content)
        self.assertIn("plain stdout line", content)

    def test_level_gate_passes_records_normalize_left_untouched(self):
        # A known shape with an unparseable date passes through unstamped; it
        # is still a record, not the previous record's continuation.
        self.collector._min_rank = 20
        self.feed(
            b"2026-08-18 01:00:00,100 DEBUG core.utils quiet\n",
            b"345:M 18 Xyz 2026 01:00:07.211 # Memory overcommit must be enabled\n",
        )
        self.collector._drain()
        self.assertIn("Memory overcommit", self.read_log())

    def test_level_gate_passes_unknown_levels(self):
        self.collector._min_rank = 50
        self.feed(b"2026-08-18 01:00:00,100 NOTE core.utils odd but kept\n")
        self.collector._drain()
        self.assertIn("odd but kept", self.read_log())

    def test_level_floor_comes_from_conf(self):
        log_collector.write_conf(self.log_dir, True, 10, 5, level="ERROR")
        self.collector._apply_conf()
        self.assertEqual(self.collector._min_rank, 40)

    def test_marker_defers_while_tail_open(self):
        # A dropped-lines marker must never splice into an unterminated line.
        self.collector._tail_open = True
        with mock.patch.object(log_collector, "_BUFFER_BYTES", 8):
            self.feed(b"aaaa\n", b"bbbb\n", b"cccc")
        self.collector._drain()
        self.assertEqual(self.strip_stamps(self.read_log()), "cccc")
        self.assertEqual(self.collector._dropped, 2)
        self.feed(b" end\n")
        self.collector._drain()
        content = self.read_log()
        self.assertIn("cccc end\n", content)
        self.assertIn("2 log lines dropped", content)


class NormalizationTests(SimpleTestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="dispatcharr-collector-")
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)
        self.collector = Collector(self.log_dir)
        self.collector._display_zone = ZoneInfo("Pacific/Auckland")
        self.collector._container_zone = timezone.utc
        self.collector._pid1_zone = timezone.utc

    def norm(self, raw):
        return self.collector._normalize(raw).decode()

    def test_canonical_line_passes_through(self):
        line = b"2026-08-18 13:00:00,500 +1200 INFO core.utils msg\n"
        self.assertEqual(self.collector._normalize(line), line)

    def test_python_utc_stamp_rendered_in_display_zone(self):
        out = self.norm(b"2026-08-18 01:00:00,500 INFO core.utils msg\n")
        self.assertEqual(out, "2026-08-18 13:00:00,500 +1200 INFO core.utils msg\n")

    def test_uwsgi_dash_stamp_gets_info_uwsgi_tokens(self):
        out = self.norm(b"2026-08-18 01:00:06,000 - *** Starting uWSGI ***\n")
        self.assertEqual(
            out, "2026-08-18 13:00:06,000 +1200 INFO uwsgi *** Starting uWSGI ***\n"
        )

    def test_shell_stamp_gets_entrypoint_tokens(self):
        out = self.norm(b"2026-08-18 01:00:06 - Starting init process...\n")
        self.assertEqual(
            out, "2026-08-18 13:00:06,000 +1200 INFO entrypoint Starting init process...\n"
        )

    def test_redis_stamp_rewritten_and_pid_role_kept(self):
        out = self.norm(b"345:M 18 Aug 2026 01:00:07.211 * Ready to accept\n")
        self.assertEqual(
            out, "2026-08-18 13:00:07,211 +1200 INFO redis 345:M * Ready to accept\n"
        )

    def test_redis_warning_sigil_maps_to_warning(self):
        out = self.norm(b"345:M 18 Aug 2026 01:00:07.211 # Memory overcommit off\n")
        self.assertEqual(
            out,
            "2026-08-18 13:00:07,211 +1200 WARNING redis 345:M # Memory overcommit off\n",
        )

    def test_postgres_stamp_rewritten(self):
        out = self.norm(b"2026-08-18 01:00:00.359 UTC [214] LOG:  starting\n")
        self.assertEqual(
            out, "2026-08-18 13:00:00,359 +1200 INFO postgres [214] LOG:  starting\n"
        )

    def test_postgres_severities_map_to_python_levels(self):
        for native, level in ((b"FATAL", "CRITICAL"), (b"ERROR", "ERROR"), (b"DEBUG2", "DEBUG")):
            out = self.norm(
                b"2026-08-18 01:00:00.359 UTC [214] " + native + b":  boom\n"
            )
            self.assertEqual(
                out,
                f"2026-08-18 13:00:00,359 +1200 {level} postgres [214] "
                + native.decode()
                + ":  boom\n",
            )

    def test_postgres_trailers_inherit_their_record_severity(self):
        # Postgres repeats its prefix on DETAIL/STATEMENT, so they arrive as
        # stamped lines that must keep the severity above them.
        self.norm(b"2026-08-18 01:00:00.359 UTC [214] ERROR:  duplicate key\n")
        for trailer in (b"DETAIL:  Key (id)=(1) exists.", b"STATEMENT:  INSERT INTO t"):
            out = self.norm(b"2026-08-18 01:00:00.359 UTC [214] " + trailer + b"\n")
            self.assertEqual(
                out,
                "2026-08-18 13:00:00,359 +1200 ERROR postgres [214] "
                + trailer.decode()
                + "\n",
            )

    def test_python_traceback_tail_is_not_stamped(self):
        self.collector._normalize(b"2026-08-18 01:00:00,100 ERROR apps.x boom\n")
        self.collector._normalize(b"Traceback (most recent call last):\n")
        for line in (b"ValueError: bad m3u\n", b"\n", b"During handling\n"):
            self.assertEqual(self.collector._normalize(line), line)

    def test_nginx_error_stamp_rewritten(self):
        out = self.norm(b"2026/08/18 01:00:00 [notice] 1#1: start worker\n")
        self.assertEqual(
            out, "2026-08-18 13:00:00,000 +1200 INFO nginx.error [notice] 1#1: start worker\n"
        )

    def test_nginx_error_levels_map_to_python_levels(self):
        for native, level in ((b"error", "ERROR"), (b"emerg", "CRITICAL")):
            out = self.norm(
                b"2026/08/18 01:00:00 [" + native + b"] 1#1: broken\n"
            )
            self.assertEqual(
                out,
                f"2026-08-18 13:00:00,000 +1200 {level} nginx.error ["
                + native.decode()
                + "] 1#1: broken\n",
            )

    def test_nginx_access_uses_its_own_offset(self):
        out = self.norm(
            b'192.0.2.7 - admin [18/Aug/2026:03:00:00 +0200] "GET / HTTP/1.1" 200\n'
        )
        self.assertEqual(
            out,
            '2026-08-18 13:00:00,000 +1200 INFO nginx.access 192.0.2.7 - admin "GET / HTTP/1.1" 200\n',
        )

    def test_uwsgi_request_shape_uses_container_zone(self):
        # uwsgi's log-format mimics the Python shape but stamps localtime.
        self.collector._container_zone = ZoneInfo("Pacific/Auckland")
        out = self.norm(
            b"2026-08-18 13:00:00,000 DEBUG uwsgi.requests Worker ID: 3 GET 200 / 4ms\n"
        )
        self.assertEqual(
            out,
            "2026-08-18 13:00:00,000 +1200 DEBUG uwsgi.requests Worker ID: 3 GET 200 / 4ms\n",
        )

    def test_postgres_zone_token_is_honoured_over_the_container_zone(self):
        # Postgres carries its own log_timezone: a container running UTC still
        # gets NZST-stamped rows, and reading them as UTC dates them +12h.
        self.collector._container_zone = timezone.utc
        out = self.norm(b"2026-08-21 21:35:01.033 NZST [176] LOG:  listening\n")
        self.assertEqual(
            out,
            "2026-08-21 21:35:01,033 +1200 INFO postgres [176] LOG:  listening\n",
        )

    def test_postgres_zone_token_follows_daylight_saving(self):
        self.collector._container_zone = timezone.utc
        out = self.norm(b"2026-01-15 21:35:01.033 NZDT [176] LOG:  midsummer\n")
        self.assertEqual(
            out,
            "2026-01-15 21:35:01,033 +1300 INFO postgres [176] LOG:  midsummer\n",
        )

    def test_postgres_zone_token_matches_the_env_declared_zone(self):
        # Display set to UTC while the container declares TZ=Pacific/Auckland:
        # postgres still names its zone, so the instant stays right.
        self.collector._display_zone = timezone.utc
        self.collector._container_zone = timezone.utc
        self.collector._pid1_zone = ZoneInfo("Pacific/Auckland")
        out = self.norm(b"2026-08-21 21:35:01.033 NZST [176] LOG:  listening\n")
        self.assertEqual(
            out,
            "2026-08-21 09:35:01,033 INFO postgres [176] LOG:  listening\n",
        )

    def test_postgres_unknown_zone_token_falls_back_to_the_container_zone(self):
        self.collector._container_zone = timezone.utc
        out = self.norm(b"2026-08-21 09:35:01.033 XYZ [176] LOG:  listening\n")
        self.assertEqual(
            out,
            "2026-08-21 21:35:01,033 +1200 INFO postgres [176] LOG:  listening\n",
        )

    def test_postgres_utc_token_is_honoured_over_container_zone(self):
        self.collector._container_zone = ZoneInfo("Pacific/Auckland")
        out = self.norm(b"2026-08-18 01:00:00.359 UTC [214] LOG:  starting\n")
        self.assertEqual(
            out, "2026-08-18 13:00:00,359 +1200 INFO postgres [214] LOG:  starting\n"
        )

    def test_continuation_lines_pass_through(self):
        for line in (b"  File \"x.py\", line 1\n", b"\tDETAIL: boom\n", b"Traceback (most recent call last):\n"):
            self.assertEqual(self.collector._normalize(line), line)

    def test_unstamped_line_gets_arrival_stamp_and_stdout_tokens(self):
        out = self.norm(b"spawned uWSGI worker 1 (pid: 74)\n")
        self.assertRegex(
            out,
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \+1[23]00 INFO stdout spawned uWSGI worker 1 \(pid: 74\)\n$",
        )

    def test_unparseable_date_in_known_shape_passes_through(self):
        line = b"345:M 99 Xxx 2026 01:00:07.211 * garbled\n"
        self.assertEqual(self.collector._normalize(line), line)

    def test_display_zone_utc_renders_without_offset(self):
        self.collector._display_zone = timezone.utc
        out = self.norm(b"2026-08-18 01:00:00,500 INFO core.utils msg\n")
        self.assertEqual(out, "2026-08-18 01:00:00,500 INFO core.utils msg\n")


class ApplySettingsTests(SimpleTestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="dispatcharr-collector-")
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)

    def test_settings_round_trip_to_conf(self):
        with mock.patch.object(log_collector, "signal_reload") as reload_sig:
            log_collector.apply_settings(
                self.log_dir,
                {
                    "log_persist": False,
                    "log_max_mb": 25,
                    "log_keep": 3,
                    "log_level": "WARNING",
                },
            )
        reload_sig.assert_called_once_with(self.log_dir)
        conf = log_collector.read_conf(self.log_dir)
        self.assertEqual(
            conf,
            {
                "persist": False,
                "max_mb": 25,
                "keep": 3,
                "filters": "",
                "time_zone": "UTC",
                "level": "WARNING",
            },
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
            conf,
            {
                "persist": False,
                "max_mb": 20,
                "keep": 4,
                "filters": "",
                "time_zone": "UTC",
                "level": "",
            },
        )
