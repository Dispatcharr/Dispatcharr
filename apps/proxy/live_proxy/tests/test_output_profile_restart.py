"""Tests for output-profile process replacement on discontinuity / PMT change.

These run the real writer, reader and stderr threads against real child
processes (``cat`` stands in for FFmpeg: it echoes stdin to stdout, so the bytes
each process received are visible in the output buffer).
"""

import threading
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy import utils as live_utils
from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.output.profile import manager as manager_module
from apps.proxy.live_proxy.output.profile.manager import (
    OutputProfileManager,
    _Restart,
)
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.tests.test_buffer_discontinuity import _FakeRedis
from apps.proxy.live_proxy.tests.test_ts_pmt_watcher import (
    AAC,
    AC3,
    AUDIO_PID,
    H264,
    VIDEO_PID,
    make_filler,
    make_pat,
    make_pmt,
)


CHANNEL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PROFILE_ID = 3
WORKER_ID = "worker-test-1"

PAT = make_pat()
PMT_AAC = make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
PMT_AC3 = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)])
FILLER = make_filler()


def _profile_fmt(profile_id=PROFILE_ID):
    return f"mpegts:p{profile_id}"


def wait_until(predicate, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class ProfileOutputDiscontinuityKeyTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.output.profile.manager.RedisClient")
    def test_make_buffer_wires_output_discontinuities_key(self, _redis_client):
        redis = _FakeRedis()
        mgr = OutputProfileManager.__new__(OutputProfileManager)
        mgr.channel_id = CHANNEL_ID
        mgr.profile_id = PROFILE_ID
        mgr._redis = redis

        with patch(
            "apps.proxy.live_proxy.output.profile.manager.RedisClient.get_buffer",
            return_value=redis,
        ):
            buf = mgr._make_buffer()

        fmt = _profile_fmt()
        self.assertEqual(
            buf.discontinuities_key,
            RedisKeys.output_buffer_discontinuities(CHANNEL_ID, fmt),
        )
        self.assertEqual(
            buf.buffer_index_key,
            RedisKeys.output_buffer_index(CHANNEL_ID, fmt),
        )

    def test_mark_discontinuity_records_sidecar(self):
        redis = _FakeRedis()
        fmt = _profile_fmt()
        buf = StreamBuffer(
            channel_id=CHANNEL_ID,
            redis_client=redis,
            buffer_index_key=RedisKeys.output_buffer_index(CHANNEL_ID, fmt),
            buffer_chunk_prefix=RedisKeys.output_buffer_chunk_prefix(CHANNEL_ID, fmt),
            chunk_timestamps_key=RedisKeys.output_chunk_timestamps(CHANNEL_ID, fmt),
            discontinuities_key=RedisKeys.output_buffer_discontinuities(
                CHANNEL_ID, fmt
            ),
        )
        buf.target_chunk_size = TS_PACKET_SIZE * 4

        self.assertEqual(buf.mark_discontinuity(), 1)
        self.assertEqual(buf.discontinuities_in_range(0, 1), [1])
        self.assertIn(
            "1",
            redis.zsets[RedisKeys.output_buffer_discontinuities(CHANNEL_ID, fmt)],
        )

    def test_cleanup_includes_discontinuities_key(self):
        redis = MagicMock()
        buf_client = MagicMock()
        buf_client.scan.return_value = (0, [])
        mgr = OutputProfileManager.__new__(OutputProfileManager)
        mgr.channel_id = CHANNEL_ID
        mgr.profile_id = PROFILE_ID
        mgr._redis = redis

        with patch(
            "apps.proxy.live_proxy.output.profile.manager.RedisClient.get_buffer",
            return_value=buf_client,
        ):
            mgr._cleanup_redis()

        self.assertIn(
            RedisKeys.output_buffer_discontinuities(CHANNEL_ID, _profile_fmt()),
            redis.delete.call_args[0],
        )


class ScriptedInput:
    """Stands in for the channel's input StreamBuffer.

    ``responses`` are returned by successive get_optimized_client_data calls;
    afterwards it reports no data. ``disc`` are the discontinuity chunk indices.
    """

    def __init__(self, responses, disc=(), start_index=0, index=0):
        self.responses = list(responses)
        self.disc = set(disc)
        self.start_index = start_index
        self.index = index
        self.calls = []

    def find_chunk_index_by_time(self, seconds):
        return self.start_index

    def get_optimized_client_data(self, client_index):
        indexed, new_index = self.get_optimized_client_data_indexed(client_index)
        return [data for _idx, data in indexed], new_index

    def get_optimized_client_data_indexed(self, client_index):
        self.calls.append(client_index)
        if not self.responses:
            return [], client_index
        chunks, new_index = self.responses.pop(0)
        if chunks and isinstance(chunks[0], tuple):
            return list(chunks), new_index
        # Plain byte lists are a contiguous suffix ending at new_index.
        first = new_index - len(chunks) + 1
        return [(first + i, chunk) for i, chunk in enumerate(chunks)], new_index

    def discontinuities_in_range(self, start_exclusive, end_inclusive):
        return sorted(d for d in self.disc if start_exclusive < d <= end_inclusive)


class RecordingOutput:
    """Stands in for the profile's output StreamBuffer; records order of events."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.stopped = False
        self.on_mark = None

    def add_chunk(self, data):
        with self.lock:
            self.events.append(("data", bytes(data)))

    def mark_discontinuity(self):
        if self.on_mark:
            self.on_mark()
        with self.lock:
            self.events.append(("disc", None))

    def stop(self):
        self.stopped = True

    def eras(self):
        """Output bytes grouped by the discontinuity markers between them."""
        with self.lock:
            eras = [b""]
            for kind, payload in self.events:
                if kind == "disc":
                    eras.append(b"")
                else:
                    eras[-1] += payload
            return eras

    def total(self):
        return sum(len(era) for era in self.eras())


class ProcessHarness(SimpleTestCase):
    """Builds a manager wired to scripted input, recording output and real processes."""

    def setUp(self):
        self.spawned = []
        self.spawn_script = None  # optional callable(call_number, cmd) -> cmd or raises
        real_spawn = live_utils.posix_spawn_proc

        def spy(cmd):
            number = len(self.spawned)
            if self.spawn_script:
                cmd = self.spawn_script(number, cmd)
            process = real_spawn(cmd)
            self.spawned.append(process)
            return process

        self.enterContext(patch.object(live_utils, "posix_spawn_proc", spy))
        self.enterContext(
            patch.object(manager_module.RedisClient, "get_client", return_value=None)
        )
        self.enterContext(
            patch.object(
                manager_module.ConfigHelper, "new_client_behind_seconds", return_value=1
            )
        )
        self.output = RecordingOutput()
        self.enterContext(
            patch.object(
                OutputProfileManager, "_make_buffer", return_value=self.output
            )
        )
        self.manager = None
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if self.manager is not None:
            self.manager.stop()
            self.manager.running = False
        for process in self.spawned:
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
            except Exception:
                pass

    def start(self, ts_buffer, command=("cat",)):
        self.manager = OutputProfileManager(
            CHANNEL_ID, PROFILE_ID, list(command), ts_buffer, WORKER_ID
        )
        self.assertTrue(self.manager.start())
        return self.manager


class ProcessReplacementTests(ProcessHarness):
    def test_pmt_change_replaces_process_and_hands_it_the_pat_first(self):
        chunk1 = PAT + PMT_AAC + FILLER + FILLER
        chunk2 = FILLER + PAT + PMT_AC3 + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], index=2)

        self.start(ts)
        # Everything is echoed back, plus the PAT handed to the second process.
        expected_total = len(chunk1) + len(chunk2) + len(PAT)
        self.assertTrue(wait_until(lambda: self.output.total() >= expected_total))

        old_era, new_era = self.output.eras()
        # Old process: everything up to (not including) the changed PMT.
        self.assertEqual(old_era, chunk1 + FILLER + PAT)
        # New process: PAT first, then the changed PMT and the rest.
        self.assertEqual(new_era, PAT + PMT_AC3 + FILLER)
        self.assertEqual(len(self.spawned), 2)
        self.assertFalse(self.output.stopped)

    def test_input_discontinuity_replaces_process_at_the_chunk_boundary(self):
        chunk1 = PAT + PMT_AAC + FILLER
        chunk2 = PAT + PMT_AAC + FILLER + FILLER  # same layout, new source
        ts = ScriptedInput([([chunk1, chunk2], 2)], disc={2}, index=2)

        self.start(ts)
        self.assertTrue(
            wait_until(lambda: self.output.total() >= len(chunk1) + len(chunk2))
        )

        old_era, new_era = self.output.eras()
        self.assertEqual(old_era, chunk1)
        self.assertEqual(new_era, chunk2)
        self.assertEqual(len(self.spawned), 2)

    def test_matching_layout_does_not_restart(self):
        chunk = PAT + PMT_AAC + FILLER
        ts = ScriptedInput([([chunk, chunk, chunk], 3)], index=3)

        self.start(ts)
        self.assertTrue(wait_until(lambda: self.output.total() >= 3 * len(chunk)))
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(self.output.eras(), [chunk * 3])

    def test_process_is_alive_throughout_the_restart(self):
        """The server treats a dead _process as a crashed profile and tears it down."""
        seen = []
        ts = ScriptedInput(
            [([PAT + PMT_AAC, PMT_AC3 + FILLER], 2)], index=2
        )
        manager = self.start(ts)
        self.output.on_mark = lambda: seen.append(
            (manager._process.poll(), manager._process is self.spawned[-1])
        )

        self.assertTrue(wait_until(lambda: len(self.spawned) == 2 and seen))
        self.assertEqual(seen, [(None, True)])

    def test_restart_does_not_stop_the_output_buffer_but_stop_does(self):
        ts = ScriptedInput([([PAT + PMT_AAC, PMT_AC3 + FILLER], 2)], index=2)
        manager = self.start(ts)
        self.assertTrue(wait_until(lambda: len(self.spawned) == 2 and self.output.total()))
        self.assertTrue(wait_until(lambda: len(self.output.eras()) == 2))
        time.sleep(0.2)
        self.assertFalse(self.output.stopped)

        manager.stop()
        self.assertTrue(wait_until(lambda: self.output.stopped))

    def test_old_process_is_drained_not_cut_off(self):
        """Input written up to the boundary comes out of the old process."""
        big_prefix = FILLER * 400  # ~75 KB, more than one pipe buffer
        ts = ScriptedInput(
            [([PAT + PMT_AAC, big_prefix + PMT_AC3 + FILLER], 2)], index=2
        )

        self.start(ts)
        expected_total = len(PAT + PMT_AAC) + len(big_prefix) + len(PAT + PMT_AC3 + FILLER)
        self.assertTrue(wait_until(lambda: self.output.total() >= expected_total))

        old_era, _ = self.output.eras()
        self.assertEqual(old_era, PAT + PMT_AAC + big_prefix)


class FailurePathTests(ProcessHarness):
    def test_spawn_failure_keeps_the_current_process_running(self):
        def script(number, cmd):
            if number >= 1:
                raise OSError("simulated spawn failure")
            return cmd

        self.spawn_script = script
        chunk1 = PAT + PMT_AAC + FILLER
        held_back = FILLER + FILLER
        chunk2 = held_back + PMT_AC3 + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], index=2)

        manager = self.start(ts)
        # Head before the new PMT still reaches the process we kept; the
        # remainder follows without a PAT handoff (that is only for a real
        # replacement). Fingerprint is reverted so a later PMT can retry.
        expected = chunk1 + held_back + PMT_AC3 + FILLER
        self.assertTrue(wait_until(lambda: self.output.total() >= len(expected)))
        self.assertTrue(manager.running)
        self.assertEqual(len(self.spawned), 1)
        self.assertIsNone(self.spawned[0].poll())
        self.assertFalse(self.output.stopped)
        # No restart happened, so no discontinuity was marked.
        self.assertEqual(self.output.eras(), [expected])

    def test_spawn_failure_retries_on_the_next_matching_pmt(self):
        failed_once = {"done": False}

        def script(number, cmd):
            # Fail only the first replacement attempt; a later PMT retries.
            if number >= 1 and not failed_once["done"]:
                failed_once["done"] = True
                raise OSError("simulated spawn failure")
            return cmd

        self.spawn_script = script
        ts = ScriptedInput(
            [
                ([PAT + PMT_AAC + FILLER, FILLER + PMT_AC3 + FILLER], 2),
                ([FILLER + PMT_AC3 + FILLER], 3),
            ],
            index=3,
        )

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(self.spawned) == 2 and self.output.total()))
        self.assertTrue(wait_until(lambda: len(self.output.eras()) == 2))
        self.assertEqual(self.output.eras()[-1][: len(PAT)], PAT)

    def test_unexpected_process_exit_stops_the_output_buffer(self):
        self.start(ScriptedInput([]), command=("true",))
        self.assertTrue(wait_until(lambda: self.output.stopped))

    def test_dead_process_is_not_replaced(self):
        manager = self.start(ScriptedInput([]), command=("true",))
        self.assertTrue(wait_until(lambda: self.output.stopped))
        self.assertTrue(wait_until(lambda: self.spawned[0].poll() is not None))

        self.assertEqual(manager._restart_transcode(reason="test"), _Restart.STOP)
        self.assertEqual(len(self.spawned), 1)
        self.assertFalse(manager.running)

    def test_wedged_old_process_is_killed_within_the_drain_cap(self):
        """A process that never reads stdin must not stall the restart."""
        def script(number, cmd):
            return ["sleep", "30"] if number == 0 else cmd

        self.spawn_script = script
        # Prefix far larger than the pipe buffer: the flush write cannot complete.
        prefix = FILLER * 1200  # ~225 KB
        ts = ScriptedInput([([PAT + PMT_AAC, prefix + PMT_AC3 + FILLER], 2)], index=2)

        with patch.object(manager_module, "_DRAIN_TIMEOUT_SECONDS", 0.3):
            started = time.monotonic()
            self.start(ts)
            self.assertTrue(wait_until(lambda: len(self.spawned) == 2 and self.output.total()))
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 3.0)
        self.assertIsNotNone(self.spawned[0].poll())  # old process was killed
        self.assertEqual(self.output.eras()[-1][: len(PAT)], PAT)


class WriterIndexTests(ProcessHarness):
    def test_missing_chunks_do_not_shift_discontinuity_indices_or_refeed(self):
        """Chunks 3 and 4 expired: survivors 5 and 6 end at new_index 6."""
        c5 = PAT + PMT_AAC + FILLER
        c6 = PAT + PMT_AAC + FILLER + FILLER
        ts = ScriptedInput(
            [([c5, c6], 6)], disc={6}, start_index=2, index=6
        )

        self.start(ts)
        self.assertTrue(wait_until(lambda: self.output.total() >= len(c5) + len(c6)))
        self.assertTrue(wait_until(lambda: len(ts.calls) >= 2))

        old_era, new_era = self.output.eras()
        self.assertEqual(old_era, c5)
        self.assertEqual(new_era, c6)
        # Advanced straight to new_index, so nothing is fetched twice.
        self.assertEqual(ts.calls[:2], [2, 6])

    def test_hole_in_the_middle_does_not_move_the_discontinuity(self):
        """Chunk 6 is missing. The mark at 6 applies before chunk 7, not to chunk 5."""
        c5 = PAT + PMT_AAC + FILLER
        c7 = PAT + PMT_AAC + FILLER + FILLER
        ts = ScriptedInput(
            [([(5, c5), (7, c7)], 7)], disc={6}, start_index=4, index=7
        )

        self.start(ts)
        self.assertTrue(wait_until(lambda: self.output.total() >= len(c5) + len(c7)))
        self.assertTrue(wait_until(lambda: len(ts.calls) >= 2))

        old_era, new_era = self.output.eras()
        self.assertEqual(old_era, c5)
        self.assertEqual(new_era, c7)
        self.assertEqual(ts.calls[:2], [4, 7])

    def test_skipping_ahead_across_a_discontinuity_replaces_the_process(self):
        c = PAT + PMT_AAC + FILLER
        ts = ScriptedInput(
            [([], 2), ([c], 96)], disc={50}, start_index=2, index=100
        )

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(self.spawned) == 2 and self.output.total()))
        self.assertEqual(ts.calls[:2], [2, 95])
        self.assertEqual(self.output.eras()[-1], c)

    def test_skipping_ahead_without_a_discontinuity_keeps_the_process(self):
        c = PAT + PMT_AAC + FILLER
        ts = ScriptedInput([([], 2), ([c], 96)], start_index=2, index=100)

        self.start(ts)
        self.assertTrue(wait_until(lambda: self.output.total() >= len(c)))
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(self.output.eras(), [c])
