"""Tests for the merged-output log collector (dispatcharr.log_collector)."""

import importlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import timezone
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase, override_settings

from core.models import CoreSettings, SYSTEM_SETTINGS_KEY
from dispatcharr import log_collector, log_redaction
from dispatcharr.log_collector import Collector


class ConfTests(SimpleTestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="dispatcharr-collector-")
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)

    def test_conf_round_trip(self):
        log_collector.write_conf(self.log_dir, False, 42, 7, "Pacific/Auckland")
        conf = log_collector.read_conf(self.log_dir)
        self.assertEqual(
            conf,
            {
                "persist": False,
                "max_mb": 42,
                "keep": 7,
                "time_zone": "Pacific/Auckland",
            },
        )

    def test_write_conf_creates_the_config_subdirectory(self):
        log_collector.write_conf(self.log_dir, True, 10, 5)
        self.assertTrue(
            os.path.isfile(os.path.join(self.log_dir, "config", "collector.conf"))
        )

    def test_conf_clamps_garbage(self):
        path = log_collector.conf_path(self.log_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("persist=1\nmax_mb=99999\nkeep=abc\n")
        conf = log_collector.read_conf(self.log_dir)
        self.assertEqual(conf["max_mb"], 1000)
        self.assertEqual(conf["keep"], 5)
        self.assertTrue(conf["persist"])

    def test_boot_zone_comes_from_the_entrypoint_environment(self):
        # `su -` strips TZ and /etc/localtime is UTC: the env is all a pre-conf line has.
        with mock.patch.dict(
            os.environ, {"DISPATCHARR_TIME_ZONE": "Pacific/Auckland"}
        ):
            collector = Collector(self.log_dir)
        out = collector._normalize(b"2026-08-18 01:00:00,500 INFO core.utils msg\n")
        self.assertEqual(
            out.decode(), "2026-08-18 13:00:00,500 +1200 INFO core.utils msg\n"
        )

    def test_boot_zone_falls_back_to_utc_when_the_environment_lies(self):
        with mock.patch.dict(os.environ, {"DISPATCHARR_TIME_ZONE": "Mars/Olympus"}):
            collector = Collector(self.log_dir)
        out = collector._normalize(b"2026-08-18 01:00:00,500 INFO core.utils msg\n")
        self.assertEqual(
            out.decode(), "2026-08-18 01:00:00,500 INFO core.utils msg\n"
        )

    def test_conf_zone_outranks_the_boot_zone(self):
        log_collector.write_conf(self.log_dir, True, 10, 5, "America/Denver")
        with mock.patch.dict(
            os.environ, {"DISPATCHARR_TIME_ZONE": "Pacific/Auckland"}
        ):
            collector = Collector(self.log_dir)
            collector._apply_conf()
        out = collector._normalize(b"2026-08-18 01:00:00,500 INFO core.utils msg\n")
        self.assertEqual(
            out.decode(), "2026-08-17 19:00:00,500 -0600 INFO core.utils msg\n"
        )

    def test_missing_conf_gives_defaults(self):
        self.assertEqual(log_collector.read_conf(self.log_dir), log_collector._DEFAULT_CONF)

class RedactionImportTests(SimpleTestCase):
    def test_redaction_module_needs_no_django(self):
        """The collector runs with no settings, so its masking must load bare."""
        script = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('lr', sys.argv[1])\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "assert not [n for n in sys.modules if n.split('.')[0] == 'django'], "
            "sorted(sys.modules)\n"
            "print(module.redact_text('GET /live/portaluser/portalpass/1.ts'))\n"
        )
        # -I keeps PYTHONPATH and the cwd off sys.path: nothing but the file.
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, log_redaction.__file__],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/live/[username]/[password]/1.ts", result.stdout)


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
        # Case-insensitive so a re-stamped line still strips the arrival tokens.
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

    def test_run_joins_reader_on_stdin_eof(self):
        done = threading.Thread(
            target=self.collector.run,
            args=(io.BytesIO(b"2026-08-18 01:00:00,000 INFO core.tasks tick\n"),),
            daemon=True,
        )
        done.start()
        done.join(timeout=5.0)
        self.assertFalse(done.is_alive())

    def test_both_sinks_get_the_same_bytes(self):
        self.feed(b"one line\n")
        self.collector._drain()
        self.assertEqual(self.read_forward(), self.read_log())

    def test_persist_off_writes_no_file_at_all(self):
        # The boot archive shift promotes even an empty log, replacing archives with stubs.
        log_collector.write_conf(self.log_dir, False, 10, 5)
        self.collector._apply_conf()
        self.feed(b"2026-08-18 01:00:00,000 INFO core.tasks tick\n")
        self.collector._drain()
        self.assertFalse(os.path.exists(self.collector.live_path))

    def test_shutdown_drains_the_whole_buffer(self):
        # Anything left behind at stop vanishes without even a dropped-lines marker.
        for i in range(20000):
            self.collector._enqueue(
                f"2026-08-18 01:00:00,000 INFO core.tasks line {i}".encode() + b"\n"
            )
        self.collector._stop = True
        self.collector.writer()
        content = self.read_log()
        self.assertIn("line 0", content)
        self.assertIn("line 19999", content)

    def test_persist_off_still_forwards(self):
        self.collector.conf["persist"] = False
        self.feed(b"stdout only\n")
        self.collector._drain()
        self.assertEqual(self.strip_stamps(self.read_forward()), "stdout only\n")
        self.assertEqual(self.read_log(), "")

    def test_oversize_line_chunks_are_not_stamped_mid_line(self):
        big = b"x" * (log_collector._MAX_LINE_BYTES + 100)
        self.feed(big + b"\n")
        forward = self.read_forward()
        self.assertEqual(len(re.findall(r"\d{4}-\d{2}-\d{2} ", forward)), 1)
        self.assertIn("x" * 200, forward)

    def test_oversize_record_is_capped_in_the_file_and_whole_on_stdout(self):
        # The file rotates so it takes the cap; docker logs has to stay complete.
        big = b"2026-08-18 01:00:00,100 ERROR postgres [1] STATEMENT:  " + b"y" * 60000
        self.feed(big + b"\n")
        self.collector._drain()
        filed = self.read_log()
        self.assertLess(len(filed), 20000)
        self.assertIn("truncated this record at", filed)
        forwarded = self.read_forward()
        self.assertGreater(len(forwarded), 60000)
        self.assertNotIn("truncated this record at", forwarded)

    def test_the_cap_never_cuts_through_a_codepoint(self):
        # The tail is served as charset=utf-8, so a cut mid-sequence malforms the file.
        body = "e" * 20000
        big = "2026-08-18 01:00:00,100 ERROR postgres [1] STATEMENT:  " + body
        self.feed(big.encode() + b"\n")
        self.collector._drain()
        with open(self.collector.live_path, "rb") as f:
            raw = f.read()
        raw.decode("utf-8")  # raises if the cap split a sequence

    def test_record_after_an_oversize_one_survives(self):
        self.feed(
            b"2026-08-18 01:00:00,100 ERROR postgres [1] STATEMENT:  " + b"y" * 60000 + b"\n",
            b"2026-08-18 01:00:01,100 INFO core.utils still here\n",
        )
        self.collector._drain()
        self.assertIn("still here", self.read_log())

    def test_record_under_the_cap_is_untouched(self):
        self.feed(b"2026-08-18 01:00:00,100 INFO core.utils " + b"z" * 100 + b"\n")
        self.collector._drain()
        content = self.read_log()
        self.assertIn("z" * 100, content)
        self.assertNotIn("truncated", content)

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

    def test_a_conf_written_elsewhere_is_noticed(self):
        """A save in another container writes the conf; the poll picks it up."""
        log_collector.write_conf(self.log_dir, True, 10, 5)
        self.collector._apply_conf()
        self.collector._drain()
        self.assertIn("dispatcharr.log_collector started", self.read_log())
        self.assertEqual(self.collector._conf_stat(), self.collector._conf_stamp)
        # A different length, so the stamp differs whatever the clock resolution.
        log_collector.write_conf(self.log_dir, True, 10, 50)
        self.assertNotEqual(self.collector._conf_stat(), self.collector._conf_stamp)
        self.collector._apply_conf()
        self.assertEqual(self.collector.conf["keep"], 50)

    def test_an_unchanged_conf_is_not_reapplied(self):
        """The writer polls every tick; only a changed conf may re-read it."""
        log_collector.write_conf(self.log_dir, True, 10, 5)
        self.collector._apply_conf()
        self.assertFalse(self.collector._conf_is_stale())
        log_collector.write_conf(self.log_dir, True, 10, 50)
        self.assertTrue(self.collector._conf_is_stale())

    def test_marker_defers_while_tail_open(self):
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
        # Postgres repeats its prefix on DETAIL/STATEMENT, so they arrive stamped.
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

    def test_python_log_after_traceback_is_renormalized(self):
        self.collector._normalize(b"2026-08-18 01:00:00,100 ERROR apps.x boom\n")
        self.collector._normalize(b"Traceback (most recent call last):\n")
        self.collector._normalize(b'  File "/app/x.py", line 1\n')
        self.collector._normalize(b"ValueError: bad m3u\n")
        self.collector._normalize(b"\n")
        out = self.norm(b"2026-08-18 01:00:00,200 INFO apps.x recovered\n")
        self.assertEqual(
            out, "2026-08-18 13:00:00,200 +1200 INFO apps.x recovered\n"
        )

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
        # Postgres carries its own log_timezone; reading an NZST row as UTC dates it +12h.
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
        # Postgres names its own zone, so the instant survives a UTC display.
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
        log_collector.apply_settings(
            self.log_dir,
            {"log_persist": False, "log_max_mb": 25, "log_keep": 3},
        )
        conf = log_collector.read_conf(self.log_dir)
        self.assertEqual(
            conf,
            {
                "persist": False,
                "max_mb": 25,
                "keep": 3,
                "time_zone": "UTC",
            },
        )

    def test_modular_mode_still_writes_the_conf(self):
        """Modular collects too, so a settings save must reach its conf."""
        with mock.patch.dict(log_collector.os.environ, {"DISPATCHARR_ENV": "modular"}):
            log_collector.apply_settings(self.log_dir, {"log_persist": False})
        self.assertFalse(log_collector.read_conf(self.log_dir)["persist"])

    def test_collector_running_needs_a_live_collector_process(self):
        self.assertFalse(log_collector.collector_running(self.log_dir))
        # A pidfile naming this process, which is not a collector.
        path = log_collector.pid_path(self.log_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(str(os.getpid()))
        self.assertFalse(log_collector.collector_running(self.log_dir))

    def test_a_save_that_reaches_nobody_says_so(self):
        # The conf still lands: it is read whenever a collector next starts.
        with self.assertLogs("dispatcharr.log_collector", level="WARNING") as caught:
            log_collector.apply_settings(
                self.log_dir, {"log_max_mb": 12}, warn_if_absent=True
            )
        self.assertIn("no log collector is running", caught.output[0])
        self.assertEqual(log_collector.read_conf(self.log_dir)["max_mb"], 12)

    def test_boot_does_not_warn_about_a_collector_that_may_be_starting(self):
        with self.assertNoLogs("dispatcharr.log_collector", level="WARNING"):
            log_collector.apply_settings(self.log_dir, {"log_max_mb": 12})

class EnvironmentFlagTests(TestCase):
    def test_the_environment_reports_the_collector_state(self):
        """The frontend hides collector-dependent surfaces on this flag."""
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        user = get_user_model().objects.create_user("envflag", password="pw")
        client = APIClient()
        client.force_authenticate(user=user)
        with override_settings(ENABLE_IP_LOOKUP=False):
            response = client.get("/api/core/settings/env/")
        self.assertIs(response.data["log_collector_running"], False)


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
                "time_zone": "UTC",
            },
        )


class Pid1ZoneTests(SimpleTestCase):
    """nginx and the entrypoint stamp in TZ, which the collector cannot read directly."""

    def test_an_unreadable_pid1_falls_back_to_the_entrypoint_mirror(self):
        env = {"DISPATCHARR_TIME_ZONE": "Pacific/Auckland"}
        with mock.patch.dict(log_collector.os.environ, env), mock.patch(
            "builtins.open", side_effect=PermissionError
        ):
            zone = log_collector._resolve_pid1_zone(timezone.utc)
        self.assertEqual(str(zone), "Pacific/Auckland")

    def test_without_the_mirror_it_keeps_the_container_zone(self):
        with mock.patch.dict(log_collector.os.environ, {}, clear=True), mock.patch(
            "builtins.open", side_effect=PermissionError
        ):
            zone = log_collector._resolve_pid1_zone(timezone.utc)
        self.assertIs(zone, timezone.utc)


class RoleTests(SimpleTestCase):
    """Each container collects under its own name when /data is shared."""

    def test_no_role_leaves_the_names_plain(self):
        with mock.patch.dict(log_collector.os.environ, {}, clear=False):
            log_collector.os.environ.pop("DISPATCHARR_LOG_ROLE", None)
            self.assertEqual(log_collector._role_suffix(), "")

    def test_a_role_becomes_a_suffix(self):
        with mock.patch.dict(log_collector.os.environ, {"DISPATCHARR_LOG_ROLE": "celery"}):
            self.assertEqual(log_collector._role_suffix(), "-celery")

    def test_a_role_reaching_a_path_is_sanitized(self):
        with mock.patch.dict(log_collector.os.environ, {"DISPATCHARR_LOG_ROLE": "../ev/il"}):
            self.assertEqual(log_collector._role_suffix(), "-evil")

    def test_an_overlong_role_is_truncated(self):
        with mock.patch.dict(log_collector.os.environ, {"DISPATCHARR_LOG_ROLE": "a" * 40}):
            self.assertEqual(log_collector._role_suffix(), "-" + "a" * 16)

    def test_the_suffix_reaches_the_log_and_pid_names_but_not_the_conf(self):
        with mock.patch.dict(log_collector.os.environ, {"DISPATCHARR_LOG_ROLE": "celery"}):
            importlib.reload(log_collector)
            self.assertEqual(log_collector.LIVE_NAME, "dispatcharr.log-celery")
            self.assertEqual(log_collector.PID_NAME, "collector-celery.pid")
            # Shared on purpose: one save configures every collector on this volume.
            self.assertEqual(log_collector.CONF_NAME, "collector.conf")
        importlib.reload(log_collector)
        self.assertEqual(log_collector.LIVE_NAME, "dispatcharr.log")
