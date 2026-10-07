"""
Unit tests for MPEG-TS discontinuity_indicator helpers and the stream-switch
stamping behavior verified against FFmpeg's mpegts demuxer.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.ts_discontinuity import (
    DISCONTINUITY_INDICATOR,
    NULL_PID,
    packet_has_discontinuity_indicator,
    set_discontinuity_indicator,
    stamp_first_packet_per_pid,
)


def _packet(pid, afc=0x01, cc=0, payload=None, af_flags=0, af_extra=b""):
    """Build one 188-byte TS packet."""
    p = bytearray(TS_PACKET_SIZE)
    p[0] = 0x47
    p[1] = (pid >> 8) & 0x1F
    p[2] = pid & 0xFF
    p[3] = ((afc & 0x03) << 4) | (cc & 0x0F)
    if afc in (0x02, 0x03):
        extra = bytes(af_extra)
        # af_length covers flags + extra (not itself).
        p[4] = 1 + len(extra)
        p[5] = af_flags & 0xFF
        p[6:6 + len(extra)] = extra
        body_start = 5 + p[4]
    else:
        body_start = 4
    if afc in (0x01, 0x03) and payload is not None:
        pl = bytes(payload)
        p[body_start:body_start + len(pl)] = pl[: TS_PACKET_SIZE - body_start]
    return bytes(p)


class DiscontinuityIndicatorTests(unittest.TestCase):
    def test_sets_flag_when_adaptation_present(self):
        pkt = _packet(256, afc=0x03, af_flags=0x10, af_extra=bytes(6), payload=b"\x00" * 20)
        self.assertFalse(packet_has_discontinuity_indicator(pkt))
        out = set_discontinuity_indicator(pkt)
        self.assertTrue(packet_has_discontinuity_indicator(out))
        self.assertEqual(out[5] & DISCONTINUITY_INDICATOR, DISCONTINUITY_INDICATOR)
        # PCR flag preserved (FFmpeg ORs 0x80 onto existing flags).
        self.assertEqual(out[5] & 0x10, 0x10)
        # Continuity counter and PID unchanged.
        self.assertEqual(out[3] & 0x0F, pkt[3] & 0x0F)
        self.assertEqual(out[1:3], pkt[1:3])

    def test_inserts_adaptation_on_payload_only_like_ffmpeg(self):
        payload = bytes(range(184))
        pkt = _packet(0, afc=0x01, cc=3, payload=payload)
        out = set_discontinuity_indicator(pkt)
        self.assertEqual((out[3] >> 4) & 0x03, 0x03)  # adaptation + payload
        self.assertEqual(out[3] & 0x0F, 3)            # same CC
        self.assertEqual(out[4], 1)
        self.assertEqual(out[5], DISCONTINUITY_INDICATOR)
        # Leading payload preserved; trailing 2 bytes dropped (room for AF).
        self.assertEqual(out[6:6 + 182], payload[:182])

    def test_null_pid_untouched(self):
        pkt = _packet(NULL_PID, afc=0x01, payload=b"\xff" * 20)
        self.assertIs(set_discontinuity_indicator(pkt), pkt)

    def test_stamp_first_packet_per_pid_only(self):
        p0a = _packet(0, afc=0x01, cc=0, payload=b"\x00" * 40)
        p0b = _packet(0, afc=0x01, cc=1, payload=b"\x01" * 40)
        p1 = _packet(256, afc=0x01, cc=0, payload=b"\x02" * 40)
        data = p0a + p0b + p1
        stamped, now = stamp_first_packet_per_pid(data)
        self.assertEqual(now, {0, 256})
        self.assertTrue(packet_has_discontinuity_indicator(stamped[0:188]))
        self.assertFalse(packet_has_discontinuity_indicator(stamped[188:376]))
        self.assertTrue(packet_has_discontinuity_indicator(stamped[376:564]))


@unittest.skipUnless(
    os.path.exists("/usr/local/bin/ffmpeg") or os.path.exists("/usr/bin/ffmpeg"),
    "ffmpeg not installed",
)
class FFmpegDiscontinuitySimulationTests(unittest.TestCase):
    """
    Simulate a stream switch by concatenating two independent MPEG-TS files.

    Without discontinuity_indicator on the first packets of the second file,
    FFmpeg's mpegts demuxer reports Packet corrupt (continuity failures).
    After stamp_first_packet_per_pid (same bit FFmpeg's initial_discontinuity
    writes), those continuity corruptions are gone.
    """

    FFMPEG = "/usr/local/bin/ffmpeg" if os.path.exists("/usr/local/bin/ffmpeg") else "ffmpeg"
    FFPROBE = "/usr/local/bin/ffprobe" if os.path.exists("/usr/local/bin/ffprobe") else "ffprobe"

    def _make_ts(self, path, color, duration=1.2):
        cmd = [
            self.FFMPEG, "-y",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:decimals={color}",
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000",
            "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "30",
            "-c:a", "aac",
            "-f", "mpegts", str(path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    def _corrupt_warnings(self, path):
        proc = subprocess.run(
            [self.FFPROBE, "-v", "warning", "-count_packets",
             "-show_entries", "stream=nb_read_packets",
             "-of", "default=nw=1", str(path)],
            capture_output=True, text=True,
        )
        return [ln for ln in proc.stderr.splitlines() if "Packet corrupt" in ln]

    def test_stamped_switch_suppresses_ffmpeg_continuity_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            a = tmp / "a.ts"
            b = tmp / "b.ts"
            self._make_ts(a, color=0)
            self._make_ts(b, color=3)

            raw = tmp / "raw_concat.ts"
            raw.write_bytes(a.read_bytes() + b.read_bytes())
            raw_corrupt = self._corrupt_warnings(raw)
            self.assertGreater(
                len(raw_corrupt), 0,
                "expected continuity corruptions on an unmarked concat",
            )

            stamped_b, stamped_pids = stamp_first_packet_per_pid(b.read_bytes())
            self.assertIn(0, stamped_pids)       # PAT
            self.assertTrue(any(pid != 0 for pid in stamped_pids))

            marked = tmp / "marked_concat.ts"
            marked.write_bytes(a.read_bytes() + stamped_b)
            marked_corrupt = self._corrupt_warnings(marked)
            self.assertEqual(
                marked_corrupt, [],
                f"FFmpeg still reported continuity corruptions after stamping: "
                f"{marked_corrupt}",
            )

            # Decode must also succeed without Packet corrupt on the demuxer.
            dec = subprocess.run(
                [self.FFMPEG, "-v", "warning", "-i", str(marked), "-f", "null", "-"],
                capture_output=True, text=True,
            )
            self.assertNotIn("Packet corrupt", dec.stderr)


if __name__ == "__main__":
    unittest.main()
