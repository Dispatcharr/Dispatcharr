"""Unit tests for shared MPEG-TS media clock helpers."""

from django.test import SimpleTestCase

from apps.proxy.live_proxy.ts_clock import (
    CLOCK_PCR,
    CLOCK_PTS,
    MAX_CLOCK_SCAN_PACKETS,
    extract_pcr,
    extract_pts,
    last_clock_on_pid,
    sample_media_clock,
    sample_media_clock_for_relock,
    wrap_delta_seconds,
)
from apps.proxy.ts_psi import TS_PACKET_SIZE

VIDEO_PID = 0x100
AUDIO_PID = 0x101


def make_filler(pid=0x1FFF):
    packet = bytearray(TS_PACKET_SIZE)
    packet[0] = 0x47
    packet[1] = (pid >> 8) & 0x1F
    packet[2] = pid & 0xFF
    packet[3] = 0x10
    return bytes(packet)


def make_pes_pts(pid, pts_seconds, pusi=True):
    packet = bytearray(TS_PACKET_SIZE)
    packet[0] = 0x47
    packet[1] = ((pid >> 8) & 0x1F) | (0x40 if pusi else 0)
    packet[2] = pid & 0xFF
    packet[3] = 0x10
    pts = int(pts_seconds * 90000) & ((1 << 33) - 1)
    base = 4
    packet[base : base + 4] = b"\x00\x00\x01\xe0"
    packet[base + 4] = 0
    packet[base + 5] = 0
    packet[base + 6] = 0x80
    packet[base + 7] = 0x80
    packet[base + 8] = 5
    packet[base + 9] = 0x20 | (((pts >> 30) & 0x07) << 1) | 1
    packet[base + 10] = (pts >> 22) & 0xFF
    packet[base + 11] = (((pts >> 15) & 0x7F) << 1) | 1
    packet[base + 12] = (pts >> 7) & 0xFF
    packet[base + 13] = ((pts & 0x7F) << 1) | 1
    return bytes(packet)


def make_pcr(pid, pcr_seconds):
    packet = bytearray(TS_PACKET_SIZE)
    packet[0] = 0x47
    packet[1] = (pid >> 8) & 0x1F
    packet[2] = pid & 0xFF
    packet[3] = 0x20  # adaptation only
    packet[4] = 7
    packet[5] = 0x10  # PCR flag
    base = int(pcr_seconds * 90000) & ((1 << 33) - 1)
    packet[6] = (base >> 25) & 0xFF
    packet[7] = (base >> 17) & 0xFF
    packet[8] = (base >> 9) & 0xFF
    packet[9] = (base >> 1) & 0xFF
    packet[10] = ((base & 0x01) << 7)
    packet[11] = 0
    packet[12] = 0
    return bytes(packet)


class TsClockTests(SimpleTestCase):
    def test_pts_roundtrip(self):
        packet = make_pes_pts(VIDEO_PID, 1234.5)
        self.assertAlmostEqual(extract_pts(packet), 1234.5, places=3)

    def test_sample_prefers_last_pts(self):
        data = make_filler() * 4 + make_pes_pts(VIDEO_PID, 1.0) + make_pes_pts(VIDEO_PID, 2.0)
        media, kind, pid = sample_media_clock(data)
        self.assertAlmostEqual(media, 2.0, places=3)
        self.assertEqual(kind, CLOCK_PTS)
        self.assertEqual(pid, VIDEO_PID)

    def test_sample_falls_back_to_pcr(self):
        data = make_filler() * 4 + make_pcr(VIDEO_PID, 4.5)
        media, kind, pid = sample_media_clock(data)
        self.assertAlmostEqual(media, 4.5, places=3)
        self.assertEqual(kind, CLOCK_PCR)
        self.assertEqual(pid, VIDEO_PID)

    def test_last_clock_on_pid_ignores_other_pids(self):
        data = make_pes_pts(0x101, 9.0) + make_pes_pts(VIDEO_PID, 3.0)
        self.assertAlmostEqual(last_clock_on_pid(data, VIDEO_PID, CLOCK_PTS), 3.0, places=3)

    def test_sample_scan_ignores_clocks_past_the_tail_cap(self):
        # A PTS older than the tail window must not be found; one inside must.
        old = make_pes_pts(VIDEO_PID, 1.0)
        filler = make_filler()
        self.assertIsNone(
            sample_media_clock(old + filler * MAX_CLOCK_SCAN_PACKETS)[0]
        )
        near = make_pes_pts(VIDEO_PID, 2.0)
        media, kind, pid = sample_media_clock(
            old + filler * (MAX_CLOCK_SCAN_PACKETS - 1) + near
        )
        self.assertAlmostEqual(media, 2.0, places=3)
        self.assertEqual(kind, CLOCK_PTS)
        self.assertEqual(pid, VIDEO_PID)

    def test_wrap_delta_tolerates_pts_wrap(self):
        older = 0.1
        newer = older + 10.0
        self.assertAlmostEqual(wrap_delta_seconds(newer, older), 10.0, places=3)

    def test_relock_prefers_lowest_pid_when_former_is_absent(self):
        # Tail ends on audio PTS; plain sample_media_clock would lock audio.
        data = make_pes_pts(VIDEO_PID, 9.0) + make_pes_pts(AUDIO_PID, 10.0)
        _, _, plain_pid = sample_media_clock(data)
        self.assertEqual(plain_pid, AUDIO_PID)
        media, kind, pid = sample_media_clock_for_relock(
            data, former_pid=VIDEO_PID
        )
        self.assertAlmostEqual(media, 9.0, places=3)
        self.assertEqual(kind, CLOCK_PTS)
        self.assertEqual(pid, VIDEO_PID)

    def test_relock_keeps_former_pid_when_still_in_batch(self):
        data = make_pes_pts(VIDEO_PID, 10.0) + make_pes_pts(AUDIO_PID, 10.0)
        media, kind, pid = sample_media_clock_for_relock(
            data, former_pid=VIDEO_PID
        )
        self.assertAlmostEqual(media, 10.0, places=3)
        self.assertEqual(pid, VIDEO_PID)
