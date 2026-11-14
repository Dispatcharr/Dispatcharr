"""Tests for fMP4 remux process replacement on discontinuity / PMT change."""

import struct
import threading
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy import utils as live_utils
from apps.proxy.live_proxy.output.buffer import OutputStreamBuffer
from apps.proxy.live_proxy.output.fmp4 import manager as fmp4_manager_module
from apps.proxy.live_proxy.output.fmp4.manager import (
    FFMPEG_REMUX_CMD,
    FFMPEG_REMUX_CMD_NO_BSF,
    FMP4RemuxManager,
    remux_command_for_layout,
)
from apps.proxy.live_proxy.output.fmp4.timing import (
    PublishedClock,
    _iter_boxes,
    fragment_media_end,
    init_track_timing,
)
from apps.proxy.live_proxy.psi_scan import PsiScanCache
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.tests.test_buffer_discontinuity import _FakeRedis
from apps.proxy.live_proxy.tests.test_output_profile_restart import (
    ScriptedInput,
    wait_until,
)
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
WORKER_ID = "worker-test-1"
FMT = "fmp4"

PAT = make_pat()
PMT_AAC = make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
PMT_AC3 = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)])
PMT_MIXED = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID), (AAC, AUDIO_PID + 1)])
FILLER = make_filler()


def _box(box_type: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


# Minimal fragmented MP4: init (ftyp+moov) then two fragments. The remux
# reader only publishes a fragment when the next moof arrives (or on clean
# EOF), so a single trailing fragment would stay buffered across a restart.
FAKE_INIT = _box(b"ftyp", b"isom") + _box(b"moov", b"")
FAKE_FRAGMENT = _box(b"moof", b"") + _box(b"mdat", b"\x00\x01\x02\x03")
FAKE_FMP4 = FAKE_INIT + FAKE_FRAGMENT + FAKE_FRAGMENT


class RemuxCommandLayoutTests(SimpleTestCase):
    def test_default_without_fingerprint_uses_aac_bsf(self):
        self.assertEqual(remux_command_for_layout(None), FFMPEG_REMUX_CMD)

    def test_aac_layout_uses_bsf(self):
        fingerprint = (256, ((H264, VIDEO_PID, ()), (AAC, AUDIO_PID, ())))
        self.assertEqual(remux_command_for_layout(fingerprint), FFMPEG_REMUX_CMD)

    def test_ac3_layout_skips_bsf(self):
        fingerprint = (256, ((H264, VIDEO_PID, ()), (AC3, AUDIO_PID, ())))
        self.assertEqual(remux_command_for_layout(fingerprint), FFMPEG_REMUX_CMD_NO_BSF)

    def test_mixed_aac_and_ac3_filters_only_the_aac_streams(self):
        """PMT order is audio index order: AC-3, AAC, AC-3, AAC."""
        fingerprint = (
            256,
            (
                (H264, VIDEO_PID, ()),
                (AC3, AUDIO_PID, ()),
                (AAC, AUDIO_PID + 1, ()),
                (AC3, AUDIO_PID + 2, ()),
                (AAC, AUDIO_PID + 3, ()),
            ),
        )
        command = remux_command_for_layout(fingerprint)
        self.assertNotIn("-bsf:a", command)
        self.assertEqual(
            command[command.index("-max_interleave_delta") + 2:command.index("-use_editlist")],
            ["-bsf:a:1", "aac_adtstoasc", "-bsf:a:3", "aac_adtstoasc"],
        )

    def test_private_pes_ac3_beside_aac_is_its_own_audio_index(self):
        fingerprint = (
            256,
            (
                (H264, VIDEO_PID, ()),
                (0x06, AUDIO_PID, ((0x6A, b""),)),
                (AAC, AUDIO_PID + 1, ()),
            ),
        )
        command = remux_command_for_layout(fingerprint)
        self.assertIn("-bsf:a:1", command)
        self.assertNotIn("-bsf:a", command)
        self.assertNotIn("-bsf:a:0", command)

    def test_commands_differ_only_by_the_aac_filter(self):
        bsf_at = FFMPEG_REMUX_CMD.index("-bsf:a")
        without_filter = (
            FFMPEG_REMUX_CMD[:bsf_at] + FFMPEG_REMUX_CMD[bsf_at + 2:]
        )
        self.assertEqual(without_filter, FFMPEG_REMUX_CMD_NO_BSF)

    def test_latm_is_audio_but_is_never_given_the_filter(self):
        """FFmpeg reads LATM as aac_latm, which aac_adtstoasc refuses."""
        latm_only = (256, ((H264, VIDEO_PID, ()), (0x11, AUDIO_PID, ())))
        self.assertEqual(remux_command_for_layout(latm_only), FFMPEG_REMUX_CMD_NO_BSF)

        latm_then_adts = (
            256,
            ((H264, VIDEO_PID, ()), (0x11, AUDIO_PID, ()), (AAC, AUDIO_PID + 1, ())),
        )
        command = remux_command_for_layout(latm_then_adts)
        self.assertIn("-bsf:a:1", command)
        self.assertNotIn("-bsf:a:0", command)

    def test_less_common_audio_types_keep_the_audio_index_in_step(self):
        """A type FFmpeg maps to audio takes an index even though it is not AAC ADTS."""
        for stream_type in (0x1C, 0x8A, 0xC1, 0xC2, 0xCF):
            fingerprint = (
                256,
                (
                    (H264, VIDEO_PID, ()),
                    (stream_type, AUDIO_PID, ()),
                    (AAC, AUDIO_PID + 1, ()),
                ),
            )
            command = remux_command_for_layout(fingerprint)
            self.assertIn("-bsf:a:1", command, msg=hex(stream_type))
            self.assertNotIn("-bsf:a:0", command, msg=hex(stream_type))

    def test_non_audio_streams_do_not_take_an_audio_index(self):
        data_and_subtitles = (
            256,
            (
                (H264, VIDEO_PID, ()),
                (0x15, 0x200, ()),  # timed metadata
                (0x06, 0x201, ((0x59, b""),)),  # DVB subtitles, not audio
                (AC3, AUDIO_PID, ()),
                (AAC, AUDIO_PID + 1, ()),
            ),
        )
        command = remux_command_for_layout(data_and_subtitles)
        self.assertIn("-bsf:a:1", command)
        self.assertNotIn("-bsf:a:3", command)

    def test_audio_index_follows_pmt_order_not_pid_order(self):
        """AC-3 on the higher PID is still audio index 0 when the PMT lists it first."""
        fingerprint = (
            256,
            (
                (H264, VIDEO_PID, ()),
                (AC3, 0x300, ()),
                (AAC, 0x200, ()),
            ),
        )
        command = remux_command_for_layout(fingerprint)
        self.assertIn("-bsf:a:1", command)
        self.assertNotIn("-bsf:a:0", command)

    def test_every_command_maps_only_video_and_audio(self):
        """DVB subtitles, teletext, and data streams are not mapped."""
        mixed = (
            256,
            ((H264, VIDEO_PID, ()), (AC3, AUDIO_PID, ()), (AAC, AUDIO_PID + 1, ())),
        )
        for command in (
            FFMPEG_REMUX_CMD,
            FFMPEG_REMUX_CMD_NO_BSF,
            remux_command_for_layout(mixed),
        ):
            map_at = command.index("-map")
            self.assertEqual(
                command[map_at:map_at + 4], ["-map", "0:v?", "-map", "0:a?"]
            )
            self.assertEqual(command.count("-map"), 2)

    def test_no_bsf_command_caps_interleave_like_bsf_command(self):
        for command in (FFMPEG_REMUX_CMD, FFMPEG_REMUX_CMD_NO_BSF):
            cap_at = command.index("-max_interleave_delta")
            self.assertEqual(command[cap_at + 1], "100K")


def _timed_era(tracks=((1, 48000, 48000),), sequence=1, start=0.0, composition=0):
    """An init and one fragment shaped like FFmpeg's.

    ``tracks`` are ``(track_id, timescale, duration_ticks)``. The fragment has
    one traf per track starting ``start`` seconds in, and a sequence number.
    """

    def box(box_type, payload):
        return struct.pack(">I", 8 + len(payload)) + box_type + payload

    traks = b""
    trafs = b""
    for track_id, timescale, duration in tracks:
        tkhd = struct.pack(">I", 3) + b"\x00" * 8 + struct.pack(">I", track_id) + b"\x00" * 60
        mdhd = struct.pack(">I", 0) + b"\x00" * 8 + struct.pack(">I", timescale) + b"\x00" * 8
        traks += box(b"trak", box(b"tkhd", tkhd) + box(b"mdia", box(b"mdhd", mdhd)))
        tfhd = struct.pack(">I", 0x000008) + struct.pack(">II", track_id, duration)
        tfdt = b"\x01\x00\x00\x00" + struct.pack(">Q", round(start * timescale))
        trun = struct.pack(">I", 0x000800) + struct.pack(">II", 1, composition)
        trafs += box(b"traf", box(b"tfhd", tfhd) + box(b"tfdt", tfdt) + box(b"trun", trun))
    init = box(b"ftyp", b"isom") + box(b"moov", traks)
    moof = box(b"moof", box(b"mfhd", struct.pack(">II", 0, sequence)) + trafs)
    return init, moof + box(b"mdat", b"\x01\x02\x03\x04")


def _fragment_clock(fragment):
    """Return ``(sequence, {track_id: tfdt})`` read from a fragment's headers."""
    sequence = None
    decode_times = {}
    for box_type, start, end in _iter_boxes(fragment):
        if box_type != b"moof":
            continue
        for child, child_start, child_end in _iter_boxes(fragment, start, end):
            if child == b"mfhd":
                sequence = struct.unpack_from(">I", fragment, child_start + 4)[0]
            elif child == b"traf":
                track_id = None
                for leaf, leaf_start, leaf_end in _iter_boxes(fragment, child_start, child_end):
                    if leaf == b"tfhd":
                        track_id = struct.unpack_from(">I", fragment, leaf_start + 4)[0]
                    elif leaf == b"tfdt":
                        decode_times[track_id] = struct.unpack_from(
                            ">Q", fragment, leaf_start + 4
                        )[0]
    return sequence, decode_times


class FragmentTimingTests(SimpleTestCase):
    def test_fragment_end_is_duration_plus_composition_offset(self):
        init, fragment = _timed_era(((1, 90000, 3600),), composition=7200)
        timescales, defaults = init_track_timing(init)
        self.assertEqual(timescales, {1: 90000})
        self.assertEqual(defaults, {})
        # 3600 ticks of duration and a 7200 tick composition offset.
        self.assertAlmostEqual(
            fragment_media_end(fragment, timescales, defaults),
            (3600 + 7200) / 90000,
        )

    def test_the_latest_track_sets_the_end(self):
        init, fragment = _timed_era(((1, 90000, 90000), (2, 48000, 96000)))
        timescales, defaults = init_track_timing(init)
        self.assertEqual(fragment_media_end(fragment, timescales, defaults), 2.0)


class PublishedClockTests(SimpleTestCase):
    TRACKS = ((1, 90000, 90000), (2, 48000, 48000))

    def _first_era(self, clock, fragments=2):
        init, _ = _timed_era(self.TRACKS)
        clock.begin_era(init)
        published = []
        for number in range(1, fragments + 1):
            _, fragment = _timed_era(self.TRACKS, sequence=number, start=number - 1)
            published.append(clock.patch(fragment))
        return published

    def test_the_first_process_is_not_shifted(self):
        clock = PublishedClock()
        init, fragment = _timed_era(self.TRACKS)
        self.assertEqual(clock.begin_era(init), 0.0)
        self.assertEqual(clock.patch(fragment), fragment)
        self.assertEqual(clock.end, 1.0)

    def test_next_process_continues_the_decode_times_and_sequence(self):
        clock = PublishedClock()
        self._first_era(clock, fragments=2)
        self.assertEqual(clock.end, 2.0)

        init, fragment = _timed_era(self.TRACKS, sequence=1)
        self.assertEqual(clock.begin_era(init), 2.0)
        sequence, decode_times = _fragment_clock(clock.patch(fragment))
        self.assertEqual(sequence, 3)
        # Each track is shifted by 2 s in its own timescale.
        self.assertEqual(decode_times, {1: 2 * 90000, 2: 2 * 48000})
        self.assertEqual(clock.end, 3.0)

    def test_later_fragments_of_the_new_process_keep_their_spacing(self):
        clock = PublishedClock()
        self._first_era(clock, fragments=1)
        init, first = _timed_era(self.TRACKS, sequence=1)
        clock.begin_era(init)
        _, second = _timed_era(self.TRACKS, sequence=2, start=1)
        self.assertEqual(_fragment_clock(clock.patch(first)), (2, {1: 90000, 2: 48000}))
        self.assertEqual(_fragment_clock(clock.patch(second)), (3, {1: 180000, 2: 96000}))

    def test_three_processes_chain(self):
        clock = PublishedClock()
        self._first_era(clock, fragments=1)
        for expected_sequence, expected_start in ((2, 1), (3, 2)):
            init, fragment = _timed_era(self.TRACKS, sequence=1)
            clock.begin_era(init)
            sequence, decode_times = _fragment_clock(clock.patch(fragment))
            self.assertEqual(sequence, expected_sequence)
            self.assertEqual(decode_times[1], expected_start * 90000)

    def test_only_header_fields_change(self):
        clock = PublishedClock()
        self._first_era(clock, fragments=1)
        init, fragment = _timed_era(self.TRACKS, sequence=1)
        clock.begin_era(init)
        patched = clock.patch(fragment)
        self.assertEqual(len(patched), len(fragment))
        # The media data after the moof box is byte for byte the same.
        moof_end = struct.unpack_from(">I", fragment, 0)[0]
        self.assertEqual(patched[moof_end:], fragment[moof_end:])

    def test_a_track_without_a_known_timescale_is_left_alone(self):
        clock = PublishedClock()
        self._first_era(clock, fragments=1)
        init, fragment = _timed_era(((1, 90000, 90000),), sequence=1)
        clock.begin_era(init)
        # Track 2 is not in this init, so only the sequence number moves.
        _, other_track = _timed_era(((2, 48000, 48000),), sequence=1)
        sequence, decode_times = _fragment_clock(clock.patch(other_track))
        self.assertEqual(sequence, 2)
        self.assertEqual(decode_times, {2: 0})

    def test_a_truncated_tail_is_published_unchanged_and_does_not_raise(self):
        clock = PublishedClock()
        init, fragment = _timed_era(self.TRACKS)
        clock.begin_era(init)
        cut = fragment[: len(fragment) // 3]
        self.assertEqual(clock.patch(cut), cut)


class _BufferRedis(_FakeRedis):
    """FakeRedis plus helpers used by fMP4 remux ownership and cleanup."""

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return False
        super().set(key, value)
        if ex is not None:
            self.ttls[key] = ex
        return True

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.kv:
                del self.kv[key]
                removed += 1
            if key in self.zsets:
                del self.zsets[key]
                removed += 1
        return removed

    def scan(self, cursor, match=None, count=200):
        prefix = (match or "*").rstrip("*")
        keys = [k for k in list(self.kv) if k.startswith(prefix)]
        return 0, keys


class OutputBufferDiscontinuityTests(SimpleTestCase):
    def test_mark_discontinuity_records_sidecar(self):
        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        self.assertEqual(buf.mark_discontinuity(), 1)
        self.assertEqual(buf.discontinuities_in_range(0, 1), [1])
        self.assertIn(
            "1",
            redis.zsets[RedisKeys.output_buffer_discontinuities(CHANNEL_ID, FMT)],
        )

    def test_get_chunks_indexed_preserves_indices(self):
        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        buf.put_chunk(b"one")
        buf.put_chunk(b"two")
        indexed, head = buf.get_chunks_indexed(0)
        self.assertEqual(head, 2)
        self.assertEqual(indexed, [(1, b"one"), (2, b"two")])

    def test_cleanup_deletes_discontinuities_key(self):
        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        buf.mark_discontinuity()
        disc_key = RedisKeys.output_buffer_discontinuities(CHANNEL_ID, FMT)
        self.assertIn(disc_key, redis.zsets)
        buf.cleanup_redis()
        self.assertNotIn(disc_key, redis.zsets)


class RecordingFmp4Output:
    """Records put_chunk / mark_discontinuity order for harness assertions."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.index = 0

    def put_chunk(self, data):
        with self.lock:
            self.index += 1
            self.events.append(("data", bytes(data)))
        return True

    def mark_discontinuity(self):
        with self.lock:
            self.events.append(("disc", None))
            return self.index + 1

    def cleanup_redis(self):
        pass

    def eras(self):
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


def _fake_remux_command():
    """Emit one fake fMP4 init+fragment, then copy stdin to /dev/null.

    Real FFmpeg is not required: the reader only needs a moof boundary so it
    can store init and forward fragments while the writer exercises restarts.
    """
    return [
        "python3",
        "-c",
        (
            "import sys, threading\n"
            f"sys.stdout.buffer.write({FAKE_FMP4!r})\n"
            "sys.stdout.buffer.flush()\n"
            "def _drain():\n"
            "    while sys.stdin.buffer.read(65536):\n"
            "        pass\n"
            "threading.Thread(target=_drain, daemon=True).start()\n"
            "threading.Event().wait()\n"
        ),
    ]


class Fmp4ProcessHarness(SimpleTestCase):
    def setUp(self):
        self.spawned = []
        self.spawn_script = None
        real_spawn = live_utils.posix_spawn_proc
        self.redis = _BufferRedis()
        self.output = RecordingFmp4Output()

        def spy(cmd):
            number = len(self.spawned)
            if self.spawn_script:
                cmd = self.spawn_script(number, cmd)
            else:
                cmd = _fake_remux_command()
            process = real_spawn(cmd)
            self.spawned.append(process)
            return process

        self.enterContext(patch.object(live_utils, "posix_spawn_proc", spy))
        self.enterContext(
            patch.object(
                fmp4_manager_module.RedisClient, "get_client", return_value=self.redis
            )
        )
        self.enterContext(
            patch.object(
                fmp4_manager_module.RedisClient, "get_buffer", return_value=self.redis
            )
        )
        self.enterContext(
            patch.object(
                fmp4_manager_module.ConfigHelper,
                "new_client_behind_seconds",
                return_value=1,
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

    def start(self, ts_buffer):
        self.manager = FMP4RemuxManager(CHANNEL_ID, ts_buffer, WORKER_ID, fmt=FMT)
        self.manager.fmp4_buffer = self.output
        self.assertTrue(self.manager.start())
        return self.manager


class Fmp4ProcessReplacementTests(Fmp4ProcessHarness):
    def test_pmt_change_replaces_process_and_marks_output_discontinuity(self):
        chunk1 = PAT + PMT_AAC + FILLER + FILLER
        chunk2 = FILLER + PAT + PMT_AC3 + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], index=2)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(self.spawned) >= 2))
        self.assertTrue(wait_until(lambda: len(self.output.eras()) >= 2))
        self.assertGreaterEqual(len(self.spawned), 2)
        # Init is stored in Redis; the output buffer only sees moof+mdat fragments.
        self.assertTrue(any(FAKE_FRAGMENT in era for era in self.output.eras()))
        self.assertIn("disc", {kind for kind, _ in self.output.events})

    def test_input_discontinuity_replaces_process(self):
        chunk1 = PAT + PMT_AAC + FILLER
        chunk2 = PAT + PMT_AAC + FILLER + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], disc={2}, index=2)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(self.spawned) >= 2))
        self.assertTrue(wait_until(lambda: "disc" in {e[0] for e in self.output.events}))

    def test_crashing_remux_is_not_respawned_on_every_chunk(self):
        """A dead process with no restart boundary must not become a respawn loop."""
        # Dies shortly after start. Input then arrives slowly, one chunk per
        # response with idle polls between, so many chunks follow the death.
        self.spawn_script = lambda number, cmd: [
            "python3", "-c", "import time; time.sleep(0.2)"
        ]
        chunk = PAT + PMT_AAC + FILLER
        responses = []
        for i in range(1, 25):
            responses.append(([chunk], i))
            responses.extend([([], i)] * 3)
        ts = ScriptedInput(responses, index=1)

        self.start(ts)
        time.sleep(3.0)
        self.assertEqual(len(self.spawned), 1)
        self.assertFalse(self.manager.running)

    def test_registered_process_stays_alive_across_a_discontinuity(self):
        """ensure_output_format recycles a manager whose process looks dead."""
        states = []

        def watch(number, cmd):
            if number >= 1 and self.manager is not None:
                states.append(self.manager._process.poll())
            return _fake_remux_command()

        self.spawn_script = watch
        chunk1 = PAT + PMT_AAC + FILLER
        chunk2 = PAT + PMT_AC3 + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], disc={2}, index=2)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(self.spawned) >= 2))
        # While the replacement is being spawned the registered process is
        # still the old one, and it has not been killed yet.
        self.assertEqual(states, [None])

    def test_two_layouts_right_after_a_switch_do_not_feed_the_old_process(self):
        """New-source bytes before a PMT change go to a process built for them."""

        def script(number, cmd):
            return _fake_remux_command()

        self.spawn_script = script
        chunk1 = PAT + PMT_AAC + FILLER
        chunk2 = PAT + PMT_AAC + FILLER + PMT_AC3 + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], disc={2}, index=2)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(self.spawned) >= 3))
        # Original, one for the switched source, one for its codec change.
        self.assertEqual(len(self.spawned), 3)

    def test_prefix_of_a_switched_chunk_uses_that_prefix_command(self):
        """Bytes before the second PMT are not handed to the default AAC command."""
        seen = []

        def script(number, cmd):
            seen.append(list(cmd))
            return _fake_remux_command()

        self.spawn_script = script
        chunk1 = PAT + PMT_AAC + FILLER
        chunk2 = PAT + PMT_AC3 + FILLER + PMT_AAC + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], disc={2}, index=2)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(seen) >= 3))
        time.sleep(0.3)
        self.assertEqual(len(seen), 3)
        self.assertIn("aac_adtstoasc", seen[0])
        self.assertNotIn("aac_adtstoasc", seen[1])
        self.assertIn("aac_adtstoasc", seen[2])

    def test_restart_continues_the_published_media_clock(self):
        """The next process's fragments continue the sequence and the decode times."""
        tracks = ((1, 90000, 90000), (2, 48000, 48000))
        init, first = _timed_era(tracks, sequence=1)
        _, second = _timed_era(tracks, sequence=2, start=1)
        # The reader publishes a fragment when the next moof arrives, so the
        # last one of each process stays buffered and is not published.
        blob = init + first + second
        script_source = (
            "import sys, threading\n"
            f"sys.stdout.buffer.write({blob!r})\n"
            "sys.stdout.buffer.flush()\n"
            "def _drain():\n"
            "    while sys.stdin.buffer.read(65536):\n"
            "        pass\n"
            "threading.Thread(target=_drain, daemon=True).start()\n"
            "threading.Event().wait()\n"
        )
        seen = []

        def script(number, cmd):
            seen.append(list(cmd))
            return ["python3", "-c", script_source]

        self.spawn_script = script
        chunk = PAT + PMT_AC3 + FILLER
        ts = ScriptedInput(self._spaced_chunks(chunk, 2), disc={2}, index=2)

        self.start(ts)

        def published():
            return [
                payload for kind, payload in self.output.events if kind == "data"
            ]

        self.assertTrue(wait_until(lambda: len(published()) >= 2))
        clocks = [_fragment_clock(fragment) for fragment in published()[:2]]
        # First process: its own numbers. Second: one second later, next sequence.
        self.assertEqual(clocks[0], (1, {1: 0, 2: 0}))
        self.assertEqual(clocks[1], (2, {1: 90000, 2: 48000}))
        # The command is the same for both processes. The clock is shifted in
        # the published bytes, so the muxer keeps its usual flags.
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])
        self.assertIn("-use_editlist", seen[1])
        self.assertNotIn("-output_ts_offset", seen[1])

    def test_codec_change_at_discontinuity_spawns_the_new_command_once(self):
        """The replacement is launched after the new PMT is read, not before."""
        seen = []

        def script(number, cmd):
            seen.append(list(cmd))
            return _fake_remux_command()

        self.spawn_script = script
        chunk1 = PAT + PMT_AAC + FILLER
        chunk2 = PAT + PMT_AC3 + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], disc={2}, index=2)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(seen) >= 2))
        time.sleep(0.3)
        self.assertEqual(len(seen), 2)
        self.assertIn("aac_adtstoasc", seen[0])
        self.assertNotIn("aac_adtstoasc", seen[1])

    def test_writer_scans_through_the_buffers_shared_cache(self):
        chunk = PAT + PMT_AAC + FILLER
        ts = ScriptedInput([([chunk, chunk], 2)], index=2)
        ts.psi_scan_cache = PsiScanCache()

        self.start(ts)
        # Chunk 1 is cached twice (before and after its PAT names the PMT PID),
        # so wait for chunk 2 rather than for a count of two.
        self.assertTrue(wait_until(
            lambda: any(key[0] == 2 for key in ts.psi_scan_cache._items)
        ))
        self.assertEqual({key[0] for key in ts.psi_scan_cache._items}, {1, 2})

    def test_matching_layout_does_not_restart(self):
        chunk = PAT + PMT_AAC + FILLER
        ts = ScriptedInput([([chunk, chunk, chunk], 3)], index=3)

        self.start(ts)
        self.assertTrue(wait_until(lambda: self.output.total() >= len(FAKE_FRAGMENT)))
        time.sleep(0.2)
        self.assertEqual(len(self.spawned), 1)

    @staticmethod
    def _rejecting_script(seen_cmds):
        """A remux that exits the way FFmpeg does when it refuses the global filter."""

        def script(number, cmd):
            seen_cmds.append(list(cmd))
            if "-bsf:a" in cmd:
                return [
                    "python3",
                    "-c",
                    "import sys\n"
                    "sys.stderr.write("
                    "\"Codec 'ac3' is not supported by the bitstream filter "
                    "'aac_adtstoasc'\\n\")\n"
                    "sys.stderr.flush()\n",
                ]
            return _fake_remux_command()

        return script

    @staticmethod
    def _spaced_chunks(chunk, count):
        """Chunks with idle polls between them, so each one reaches a live process.

        The idle polls give the stderr reader time to report a refused filter
        before the next chunk arrives, as a real stream's timing does.
        """
        responses = []
        for number in range(1, count + 1):
            responses.append(([chunk], number))
            responses.extend([([], number)] * 5)
        return responses

    def test_bsf_rejection_respawns_without_the_filter_and_stays_off(self):
        """The PMT still lists AAC. It must not switch the refused filter back on."""
        seen_cmds = []
        self.spawn_script = self._rejecting_script(seen_cmds)
        chunk = PAT + PMT_AAC + FILLER
        ts = ScriptedInput(self._spaced_chunks(chunk, 4), index=4)

        self.start(ts)
        self.assertTrue(
            wait_until(lambda: any(cmd == FFMPEG_REMUX_CMD_NO_BSF for cmd in seen_cmds))
        )
        time.sleep(1.5)
        self.assertEqual(seen_cmds, [FFMPEG_REMUX_CMD, FFMPEG_REMUX_CMD_NO_BSF])
        self.assertTrue(self.manager.running)

    def test_refused_filter_is_tried_again_for_a_new_source(self):
        """A discontinuity brings a new PMT, so the filter is chosen from it afresh."""
        seen_cmds = []
        self.spawn_script = self._rejecting_script(seen_cmds)
        chunk = PAT + PMT_AAC + FILLER
        ts = ScriptedInput(self._spaced_chunks(chunk, 3), disc={3}, index=3)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(seen_cmds) >= 3))
        self.assertEqual(
            seen_cmds[:3],
            [FFMPEG_REMUX_CMD, FFMPEG_REMUX_CMD_NO_BSF, FFMPEG_REMUX_CMD],
        )

    def test_rejected_per_stream_filter_is_not_retried(self):
        """A wrong audio index has no fallback command, so it must not loop."""
        seen_cmds = []

        def script(number, cmd):
            seen_cmds.append(list(cmd))
            return [
                "python3",
                "-c",
                "import sys\n"
                "sys.stderr.write("
                "\"Codec 'ac3' is not supported by the bitstream filter "
                "'aac_adtstoasc'\\n\")\n"
                "sys.stderr.flush()\n",
            ]

        self.spawn_script = script
        chunk = PAT + PMT_MIXED + FILLER
        ts = ScriptedInput(self._spaced_chunks(chunk, 4), index=4)

        self.start(ts)
        self.assertTrue(wait_until(lambda: not self.manager.running))
        time.sleep(0.4)
        self.assertEqual(len(seen_cmds), 1)
        self.assertIn("-bsf:a:1", seen_cmds[0])

    def test_ac3_startup_spawns_the_no_bsf_command_once(self):
        """The first process is chosen from the chunk's PMT, not launched ahead of it."""
        seen_cmds = []

        def script(number, cmd):
            seen_cmds.append(list(cmd))
            return _fake_remux_command()

        self.spawn_script = script
        chunk = PAT + PMT_AC3 + FILLER
        ts = ScriptedInput([([chunk], 1)], index=1)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(seen_cmds) == 1 and self.output.total()))
        time.sleep(0.2)
        self.assertEqual(seen_cmds, [FFMPEG_REMUX_CMD_NO_BSF])
        self.assertIsNone(self.manager._process.poll())

    def test_chunk_without_a_pmt_waits_for_the_map(self):
        """Chunks before the first program map go to the process that map selects."""
        seen_cmds = []
        written = []
        real_write = FMP4RemuxManager._write_stdin

        def script(number, cmd):
            seen_cmds.append(list(cmd))
            return _fake_remux_command()

        def record_write(manager, data):
            written.append(bytes(data))
            return real_write(manager, data)

        self.spawn_script = script
        self.enterContext(patch.object(FMP4RemuxManager, "_write_stdin", record_write))
        no_pmt = FILLER + FILLER
        ac3 = PAT + PMT_AC3 + FILLER
        ts = ScriptedInput([([no_pmt, ac3], 2)], index=2)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(seen_cmds) == 1 and len(written) >= 2))
        time.sleep(0.2)
        self.assertEqual(seen_cmds, [FFMPEG_REMUX_CMD_NO_BSF])
        self.assertEqual(written[0], no_pmt)
        self.assertEqual(written[1], ac3)

    def test_switch_without_a_pmt_waits_for_the_new_map(self):
        """After a switch, chunks before the new map stay off the old process and the AAC command."""
        seen_cmds = []
        written = []
        real_write = FMP4RemuxManager._write_stdin

        def script(number, cmd):
            seen_cmds.append(list(cmd))
            return _fake_remux_command()

        def record_write(manager, data):
            written.append((manager._process.pid, bytes(data)))
            return real_write(manager, data)

        self.spawn_script = script
        self.enterContext(patch.object(FMP4RemuxManager, "_write_stdin", record_write))
        first = PAT + PMT_AAC + FILLER
        no_pmt = FILLER + FILLER
        ac3 = PAT + PMT_AC3 + FILLER
        ts = ScriptedInput([([first, no_pmt, ac3], 3)], disc={2}, index=3)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(seen_cmds) == 2 and len(written) >= 3))
        time.sleep(0.2)
        self.assertEqual(seen_cmds, [FFMPEG_REMUX_CMD, FFMPEG_REMUX_CMD_NO_BSF])
        first_pid = written[0][0]
        self.assertEqual(written[0][1], first)
        self.assertNotEqual(written[1][0], first_pid)
        self.assertEqual(written[1][1], no_pmt)
        self.assertEqual(written[2][0], written[1][0])
        self.assertEqual(written[2][1], ac3)

    def test_start_fails_when_the_remux_binary_is_missing(self):
        ts = ScriptedInput([([PAT + PMT_AC3 + FILLER], 1)], index=1)
        self.manager = FMP4RemuxManager(CHANNEL_ID, ts, WORKER_ID, fmt=FMT)
        self.manager.fmp4_buffer = self.output
        with patch("shutil.which", return_value=None):
            self.assertFalse(self.manager.start())
        self.assertEqual(self.spawned, [])
        self.assertFalse(self.manager.running)

    def test_spawn_failure_on_the_first_chunk_stops_the_remux(self):
        def script(number, cmd):
            raise OSError("cannot spawn")

        self.spawn_script = script
        ts = ScriptedInput([([PAT + PMT_AC3 + FILLER], 1)], index=1)

        self.start(ts)
        self.assertTrue(wait_until(lambda: self.manager.running is False))
        self.assertEqual(self.spawned, [])

    def test_waiting_for_the_first_chunk_stays_registered(self):
        ts = ScriptedInput([([], 0)], index=0)
        self.manager = FMP4RemuxManager(CHANNEL_ID, ts, WORKER_ID, fmt=FMT)
        self.manager.running = True
        self.manager._process = None
        self.assertTrue(self.manager.output_process_healthy())

        self.manager.running = False
        self.assertFalse(self.manager.output_process_healthy())

        process = MagicMock()
        process.poll.return_value = None
        self.manager._process = process
        self.manager.running = True
        self.assertTrue(self.manager.output_process_healthy())
        process.poll.return_value = 1
        self.assertFalse(self.manager.output_process_healthy())

    def test_live_process_without_a_writer_is_not_healthy(self):
        """A remux that stopped feeding is replaced even while FFmpeg still runs."""
        ts = ScriptedInput([([], 0)], index=0)
        self.manager = FMP4RemuxManager(CHANNEL_ID, ts, WORKER_ID, fmt=FMT)
        process = MagicMock()
        process.poll.return_value = None
        self.manager._process = process
        self.manager.running = False
        self.assertFalse(self.manager.output_process_healthy())

    def test_restart_clears_init_segment_key(self):
        init_key = RedisKeys.output_init(CHANNEL_ID, FMT)
        self.redis.kv[init_key] = b"stale-init"
        chunk1 = PAT + PMT_AAC + FILLER
        chunk2 = FILLER + PAT + PMT_AC3 + FILLER
        ts = ScriptedInput([([chunk1, chunk2], 2)], index=2)

        self.start(ts)
        self.assertTrue(wait_until(lambda: len(self.spawned) >= 2))
        # After restart the stale key is cleared until the new reader stores init.
        # Allow either cleared or replaced with a fresh fake init.
        self.assertTrue(
            wait_until(
                lambda: init_key not in self.redis.kv
                or self.redis.kv.get(init_key) == FAKE_INIT
            )
        )


class Fmp4GeneratorDiscontinuityTests(SimpleTestCase):
    def test_stream_stays_open_and_yields_init_after_output_discontinuity(self):
        from apps.proxy.live_proxy.output.fmp4.generator import FMP4StreamGenerator

        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        buf.put_chunk(b"frag-a")
        buf.mark_discontinuity()
        buf.put_chunk(b"frag-b")

        init_key = RedisKeys.output_init(CHANNEL_ID, FMT)
        redis.kv[init_key] = b"init-v2"

        gen = FMP4StreamGenerator(
            CHANNEL_ID, "client-1", "127.0.0.1", "test-agent", False
        )
        gen.fmp4_buffer = buf
        gen.local_index = 0
        gen.proxy_server = MagicMock()
        gen.proxy_server.redis_client = None
        gen._check_resources = lambda: True
        gen._is_timeout = lambda: True  # stop after first empty poll

        with patch("core.utils.RedisClient.get_buffer", return_value=redis):
            chunks = list(gen._stream_data_generator())
        self.assertEqual(chunks, [b"frag-a", b"init-v2", b"frag-b"])

    def _generator(self, redis, buf, local_index=0):
        from apps.proxy.live_proxy.output.fmp4.generator import FMP4StreamGenerator

        gen = FMP4StreamGenerator(
            CHANNEL_ID, "client-1", "127.0.0.1", "test-agent", False
        )
        gen.fmp4_buffer = buf
        gen.local_index = local_index
        gen.proxy_server = MagicMock()
        gen.proxy_server.redis_client = None
        gen._check_resources = lambda: True
        gen._is_timeout = lambda: True
        return gen

    def test_new_client_starts_at_the_latest_restart(self):
        """The init sent at connect matches only the newest era's fragments."""
        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        buf.put_chunk(b"old-1")
        buf.put_chunk(b"old-2")
        buf.mark_discontinuity()
        buf.put_chunk(b"new-1")
        buf.put_chunk(b"new-2")
        redis.kv[RedisKeys.output_init(CHANNEL_ID, FMT)] = b"init-v2"

        gen = self._generator(redis, buf, local_index=0)
        gen._align_start_to_current_era(head=4)

        self.assertEqual(gen.local_index, 2)
        with patch("core.utils.RedisClient.get_buffer", return_value=redis):
            chunks = list(gen._stream_data_generator())
        # No second init: the one sent at connect already covers this era.
        self.assertEqual(chunks, [b"new-1", b"new-2"])

    def test_new_client_already_in_latest_era_is_unchanged(self):
        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        buf.put_chunk(b"old-1")
        buf.mark_discontinuity()
        buf.put_chunk(b"new-1")
        buf.put_chunk(b"new-2")

        gen = self._generator(redis, buf, local_index=2)
        gen._align_start_to_current_era(head=3)
        self.assertEqual(gen.local_index, 2)

    def test_new_client_without_restart_keeps_its_start(self):
        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        buf.put_chunk(b"one")
        buf.put_chunk(b"two")

        gen = self._generator(redis, buf, local_index=0)
        gen._align_start_to_current_era(head=2)
        self.assertEqual(gen.local_index, 0)
        self.assertEqual(gen._init_covers_through, 0)

    def test_restart_after_connect_keeps_the_client_and_sends_the_new_init(self):
        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        buf.put_chunk(b"frag-a")
        gen = self._generator(redis, buf, local_index=0)
        gen._align_start_to_current_era(head=1)

        buf.mark_discontinuity()
        buf.put_chunk(b"frag-b")
        redis.kv[RedisKeys.output_init(CHANNEL_ID, FMT)] = b"init-v2"

        with patch("core.utils.RedisClient.get_buffer", return_value=redis):
            chunks = list(gen._stream_data_generator())
        self.assertEqual(chunks, [b"frag-a", b"init-v2", b"frag-b"])

    def test_initializer_starts_at_the_latest_restart(self):
        """A failover while the channel is starting must not replay the old era."""
        from apps.proxy.live_proxy.output.fmp4.generator import FMP4StreamGenerator

        redis = _BufferRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt=FMT)
        buf.put_chunk(b"old-1")
        buf.put_chunk(b"old-2")
        buf.mark_discontinuity()
        buf.put_chunk(b"new-1")

        gen = FMP4StreamGenerator(
            CHANNEL_ID, "client-1", "127.0.0.1", "test-agent", True
        )
        with patch(
            "apps.proxy.live_proxy.output.fmp4.generator.ProxyServer.get_instance",
            return_value=MagicMock(),
        ), patch("core.utils.RedisClient.get_buffer", return_value=redis):
            self.assertTrue(gen._setup_streaming())
        self.assertEqual(gen.local_index, 2)
        self.assertEqual(gen._init_covers_through, 3)
