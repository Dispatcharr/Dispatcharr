"""Dispatcharr#259: fold a per-attempt DVB subtitle sidecar into the final MKV.

dvb_subtitle copies straight into the MKV. dvb_teletext has no Matroska tag
and ffmpeg ships no decoder for it, so it goes through ccextractor to SRT
first. Either way the sidecar (and any intermediate SRT) never survives past
this call - the recording directory always ends up holding just the one
.mkv, same as today.
"""
import os
import tempfile
import time
from collections import namedtuple

from django.test import SimpleTestCase

from apps.channels.tasks import (
    _dvr_build_ffmpeg_cmd,
    _dvr_subtitle_sidecar_path,
    _dvr_sidecar_fold_in_eligible,
    _dvr_fold_subtitle_sidecar_into_mkv,
)


class BuildFfmpegCmdSubtitleOutputTests(SimpleTestCase):
    def _cmd(self, **kwargs):
        return _dvr_build_ffmpeg_cmd(
            "http://127.0.0.1:5656/proxy/ts/stream/uuid",
            71,
            "/data/recordings/.dvr_71_hls/index.m3u8",
            "/data/recordings/.dvr_71_hls/seg_%05d.ts",
            0,
            **kwargs,
        )

    def test_no_sidecar_path_leaves_command_unchanged(self):
        cmd = self._cmd()
        self.assertNotIn("0:s?", cmd)
        self.assertEqual(cmd.count("mpegts"), 0)

    def test_sidecar_path_adds_a_second_subtitle_only_output(self):
        cmd = self._cmd(subtitle_sidecar_path="/data/recordings/.dvr_71_hls/subs_attempt_0.ts")
        self.assertIn("/data/recordings/.dvr_71_hls/subs_attempt_0.ts", cmd)
        idx = cmd.index("0:s?")
        self.assertEqual(cmd[idx - 1], "-map")
        self.assertIn("-c:s", cmd)
        self.assertEqual(cmd[cmd.index("-c:s") + 1], "copy")
        # The sidecar target must be the last argument - a second, separate
        # ffmpeg output, not folded into the HLS output's own flags.
        self.assertEqual(cmd[-1], "/data/recordings/.dvr_71_hls/subs_attempt_0.ts")

    def test_sidecar_output_does_not_disturb_the_hls_output(self):
        cmd = self._cmd(subtitle_sidecar_path="/data/recordings/.dvr_71_hls/subs_attempt_0.ts")
        self.assertIn("/data/recordings/.dvr_71_hls/index.m3u8", cmd)
        self.assertIn("-hls_time", cmd)

FakeResult = namedtuple("FakeResult", ["returncode", "stderr"])


class SidecarPathTests(SimpleTestCase):
    def test_path_is_inside_hls_dir(self):
        path = _dvr_subtitle_sidecar_path("/data/.dvr_5_hls", 0)
        self.assertTrue(path.startswith("/data/.dvr_5_hls/"))

    def test_path_is_distinct_per_attempt(self):
        first = _dvr_subtitle_sidecar_path("/data/.dvr_5_hls", 0)
        second = _dvr_subtitle_sidecar_path("/data/.dvr_5_hls", 1)
        self.assertNotEqual(first, second)


class SidecarFoldInEligibleTests(SimpleTestCase):
    def test_clean_single_attempt_is_eligible(self):
        self.assertTrue(_dvr_sidecar_fold_in_eligible("dvb_teletext", 0, False))

    def test_no_detected_codec_is_not_eligible(self):
        self.assertFalse(_dvr_sidecar_fold_in_eligible(None, 0, False))

    def test_a_retried_attempt_is_not_eligible(self):
        self.assertFalse(_dvr_sidecar_fold_in_eligible("dvb_teletext", 1, False))

    def test_resumed_onto_pre_existing_segments_is_not_eligible(self):
        # A server restart mid-recording resumes into the same HLS dir with
        # zero in-task ffmpeg retries, but the sidecar only covers the
        # post-resume portion of a timeline that already has segments.
        self.assertFalse(_dvr_sidecar_fold_in_eligible("dvb_teletext", 0, True))


class FoldSidecarIntoMkvTests(SimpleTestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output_path = os.path.join(self.tmpdir, "recording.mkv")
        self.sidecar_path = os.path.join(self.tmpdir, "subs_attempt_0.ts")
        with open(self.output_path, "wb") as f:
            f.write(b"original mkv bytes")
        self.deadline = time.monotonic() + 60
        self.calls = []

    def _write_output_and_succeed(self, cmd, log_label, step_label, deadline):
        self.calls.append((step_label, cmd))
        # Simulate the tool actually producing its declared output file.
        out = cmd[-1]
        with open(out, "wb") as f:
            f.write(b"tool output")
        return FakeResult(returncode=0, stderr="")

    def _fail(self, cmd, log_label, step_label, deadline):
        self.calls.append((step_label, cmd))
        return FakeResult(returncode=1, stderr="boom")

    def test_missing_sidecar_is_a_noop(self):
        result = _dvr_fold_subtitle_sidecar_into_mkv(
            self.sidecar_path, "dvb_subtitle", self.output_path,
            "test", self.deadline, run_cmd=self._write_output_and_succeed,
        )
        self.assertFalse(result)
        self.assertEqual(self.calls, [])

    def test_empty_sidecar_is_a_noop_and_is_removed(self):
        open(self.sidecar_path, "wb").close()
        result = _dvr_fold_subtitle_sidecar_into_mkv(
            self.sidecar_path, "dvb_subtitle", self.output_path,
            "test", self.deadline, run_cmd=self._write_output_and_succeed,
        )
        self.assertFalse(result)
        self.assertFalse(os.path.exists(self.sidecar_path))

    def test_unsupported_codec_is_a_noop_and_calls_nothing(self):
        with open(self.sidecar_path, "wb") as f:
            f.write(b"data")
        result = _dvr_fold_subtitle_sidecar_into_mkv(
            self.sidecar_path, "mov_text", self.output_path,
            "test", self.deadline, run_cmd=self._write_output_and_succeed,
        )
        self.assertFalse(result)
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(self.sidecar_path))

    def test_dvb_subtitle_copies_straight_in_on_success(self):
        with open(self.sidecar_path, "wb") as f:
            f.write(b"dvbsub bitstream")
        result = _dvr_fold_subtitle_sidecar_into_mkv(
            self.sidecar_path, "dvb_subtitle", self.output_path,
            "test", self.deadline, run_cmd=self._write_output_and_succeed,
        )
        self.assertTrue(result)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "fold subtitle sidecar into MKV")
        self.assertFalse(os.path.exists(self.sidecar_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), b"tool output")

    def test_mux_command_forces_matroska_output_format(self):
        # The temp output is named "<recording>.mkv.with_subs.tmp" - ffmpeg
        # infers the muxer from the extension, and ".tmp" isn't one, so the
        # format must be forced explicitly or ffmpeg can't select a muxer.
        with open(self.sidecar_path, "wb") as f:
            f.write(b"dvbsub bitstream")
        _dvr_fold_subtitle_sidecar_into_mkv(
            self.sidecar_path, "dvb_subtitle", self.output_path,
            "test", self.deadline, run_cmd=self._write_output_and_succeed,
        )
        mux_cmd = self.calls[0][1]
        self.assertIn("-f", mux_cmd)
        self.assertEqual(mux_cmd[mux_cmd.index("-f") + 1], "matroska")

    def test_dvb_subtitle_mux_failure_leaves_original_mkv_untouched(self):
        with open(self.sidecar_path, "wb") as f:
            f.write(b"dvbsub bitstream")
        result = _dvr_fold_subtitle_sidecar_into_mkv(
            self.sidecar_path, "dvb_subtitle", self.output_path,
            "test", self.deadline, run_cmd=self._fail,
        )
        self.assertFalse(result)
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), b"original mkv bytes")
        self.assertFalse(os.path.exists(self.sidecar_path))

    def test_dvb_teletext_decodes_via_ccextractor_then_muxes(self):
        with open(self.sidecar_path, "wb") as f:
            f.write(b"teletext bitstream")
        result = _dvr_fold_subtitle_sidecar_into_mkv(
            self.sidecar_path, "dvb_teletext", self.output_path,
            "test", self.deadline, run_cmd=self._write_output_and_succeed,
        )
        self.assertTrue(result)
        self.assertEqual(
            [c[0] for c in self.calls],
            ["ccextractor teletext decode", "fold subtitle sidecar into MKV"],
        )
        self.assertFalse(os.path.exists(self.sidecar_path))
        srt_path = f"{self.sidecar_path}.srt"
        self.assertFalse(os.path.exists(srt_path))

    def test_dvb_teletext_decode_failure_skips_mux_entirely(self):
        with open(self.sidecar_path, "wb") as f:
            f.write(b"teletext bitstream")
        result = _dvr_fold_subtitle_sidecar_into_mkv(
            self.sidecar_path, "dvb_teletext", self.output_path,
            "test", self.deadline, run_cmd=self._fail,
        )
        self.assertFalse(result)
        self.assertEqual([c[0] for c in self.calls], ["ccextractor teletext decode"])
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), b"original mkv bytes")
        self.assertFalse(os.path.exists(self.sidecar_path))
        self.assertFalse(os.path.exists(f"{self.sidecar_path}.srt"))
