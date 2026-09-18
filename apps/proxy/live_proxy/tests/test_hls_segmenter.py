"""
Unit tests for the HLS TS segmenter.

The segmenter itself is dependency-free (stdlib only, no Django/Redis). These
tests stay on unittest so they can still be run without the Django harness:

    python3 -m unittest apps.proxy.live_proxy.tests.test_hls_segmenter
"""

import unittest

from apps.proxy.live_proxy.output.hls.segmenter import (
    TSSegmenter,
    TS_PACKET_SIZE,
    extract_pts,
    packet_pid,
    parse_pat,
    parse_pmt,
    parse_pmt_streams,
    render_media_playlist,
    starts_keyframe,
)

VIDEO_PID = 256
PMT_PID = 4096
MPEG2 = 0x02
H264 = 0x1B
HEVC = 0x24


def make_packet(pid, payload, pusi=False, random_access=False):
    """Build one 188-byte TS packet with the given payload bytes."""
    header = bytearray(4)
    header[0] = 0x47
    header[1] = ((0x40 if pusi else 0x00) | (pid >> 8)) & 0xFF
    header[2] = pid & 0xFF

    if random_access:
        # adaptation field present + payload
        body_len = TS_PACKET_SIZE - 4 - 2 - len(payload)
        assert body_len >= 0, "payload too large for packet with AF"
        header[3] = 0x30  # AF + payload
        af = bytearray([1 + body_len, 0x40])  # af_length, RAI flag
        af.extend(b"\xff" * body_len)
        packet = bytes(header) + bytes(af) + bytes(payload)
    else:
        header[3] = 0x10  # payload only
        packet = bytes(header) + bytes(payload)
        packet += b"\xff" * (TS_PACKET_SIZE - len(packet))
    assert len(packet) == TS_PACKET_SIZE
    return packet


def make_pat():
    # pointer + table header (8 bytes from table_id) + one program entry
    payload = bytearray([0x00])                      # pointer_field
    payload += bytes([0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00])
    payload += bytes([0x00, 0x01, 0xE0 | (PMT_PID >> 8), PMT_PID & 0xFF])
    payload += bytes(4)                              # CRC placeholder
    return make_packet(0, payload, pusi=True)


def make_pmt(stream_type=H264):
    payload = bytearray([0x00])                      # pointer_field
    # table_id, section_length covers from after length to CRC
    es_loop = bytes([stream_type, 0xE0 | (VIDEO_PID >> 8), VIDEO_PID & 0xFF, 0xF0, 0x00])
    section_length = 9 + len(es_loop) + 4            # post-length header + loop + CRC
    payload += bytes([0x02, 0xB0 | (section_length >> 8), section_length & 0xFF])
    payload += bytes([0x00, 0x01, 0xC1, 0x00, 0x00]) # tsid, ver, sec, last
    payload += bytes([0xE0 | (VIDEO_PID >> 8), VIDEO_PID & 0xFF, 0xF0, 0x00])  # PCR PID, prog info len
    payload += es_loop
    payload += bytes(4)                              # CRC placeholder
    return make_packet(PMT_PID, payload, pusi=True)


def make_pes_header(pts_seconds):
    """PES start code, stream_id, and a PTS-only optional header."""
    pts = int(pts_seconds * 90000)
    p = bytearray()
    p += bytes([0x00, 0x00, 0x01, 0xE0, 0x00, 0x00])  # PES start, stream_id, length
    p += bytes([0x80, 0x80, 0x05])                    # flags, PTS-only, header len 5
    p += bytes([
        0x21 | (((pts >> 30) & 0x07) << 1),
        (pts >> 22) & 0xFF,
        0x01 | (((pts >> 15) & 0x7F) << 1),
        (pts >> 7) & 0xFF,
        0x01 | ((pts & 0x7F) << 1),
    ])
    return p


def make_video_pes(pts_seconds, keyframe, use_rai=False):
    """A PUSI H.264 packet opening a PES with the given PTS."""
    p = make_pes_header(pts_seconds)
    if keyframe and not use_rai:
        p += bytes([0x00, 0x00, 0x00, 0x01, 0x65])    # IDR slice
    else:
        p += bytes([0x00, 0x00, 0x00, 0x01, 0x41])    # non-IDR slice
    return make_packet(VIDEO_PID, p, pusi=True, random_access=keyframe and use_rai)


def make_filler():
    return make_packet(VIDEO_PID, b"\x00" * 20)


def make_h264_pes(pts_seconds, nal_types):
    """PUSI H.264 PES whose payload starts with the given nal_unit_type list."""
    p = make_pes_header(pts_seconds)
    for nal_type in nal_types:
        # Start code + nal header byte (nal_unit_type in bits 0-4).
        p += bytes([0x00, 0x00, 0x00, 0x01, 0x60 | (nal_type & 0x1F), 0x01])
    return make_packet(VIDEO_PID, p, pusi=True)


def make_hevc_pes(pts_seconds, nal_types):
    """PUSI HEVC PES whose payload starts with the given nal_unit_type list."""
    p = make_pes_header(pts_seconds)
    for nal_type in nal_types:
        # Start code + nal header byte (nal_unit_type in bits 1-6).
        p += bytes([0x00, 0x00, 0x00, 0x01, (nal_type << 1) & 0xFF, 0x01])
    return make_packet(VIDEO_PID, p, pusi=True, random_access=False)


MPEG2_SEQUENCE_HEADER = bytes([0xB3, 0x00, 0x00])
MPEG2_GOP_HEADER = bytes([0xB8, 0x00, 0x00])
# Slice start codes are the slice's vertical position, so their values overlap
# the H.264 nal_unit_type numbering (5 = IDR, 7 = SPS).
MPEG2_SLICE_5 = bytes([0x05, 0x00, 0x00])


def mpeg2_picture(coding_type):
    """A picture header: 10-bit temporal_reference then 3-bit
    picture_coding_type (1 = I, 2 = P, 3 = B)."""
    return bytes([0x00, 0x00, (coding_type & 0x07) << 3])


def make_mpeg2_pes(pts_seconds, units):
    """PUSI MPEG-2 PES carrying the given start-code payloads in order."""
    p = make_pes_header(pts_seconds)
    for unit in units:
        p += b"\x00\x00\x01" + unit
    return make_packet(VIDEO_PID, p, pusi=True)


class ParserTests(unittest.TestCase):
    def test_pat_pmt_roundtrip(self):
        self.assertEqual(parse_pat(make_pat()), PMT_PID)
        video_pid, stream_type = parse_pmt(make_pmt())
        self.assertEqual(video_pid, VIDEO_PID)
        self.assertEqual(stream_type, H264)
        # Normal single-packet PMTs remain fully parseable.
        self.assertEqual(parse_pmt_streams(make_pmt()), [(H264, VIDEO_PID)])
        self.assertEqual(parse_pmt_streams(make_audio_pmt()), [(AAC, AUDIO_PID)])

    def test_incomplete_pmt_section_is_not_authoritative(self):
        """A section_length that spills past this TS packet must not yield a
        partial ES list (audio in packet 1, video in packet 2)."""
        # Build a valid single-packet audio PMT, then lie about section_length
        # so the declared section continues past the packet boundary.
        packet = bytearray(make_audio_pmt())
        base = 4  # payload-only packet, no adaptation field
        pointer = packet[base]
        section = base + 1 + pointer
        # Inflate section_length to claim more bytes than remain in the packet.
        claimed = TS_PACKET_SIZE  # definitely overflows section+3+claimed
        packet[section + 1] = 0xB0 | ((claimed >> 8) & 0x0F)
        packet[section + 2] = claimed & 0xFF
        self.assertIsNone(parse_pmt_streams(bytes(packet)))
        self.assertEqual(parse_pmt(bytes(packet)), (None, None))

    def test_pts_roundtrip(self):
        packet = make_video_pes(1234.5, keyframe=True)
        self.assertAlmostEqual(extract_pts(packet), 1234.5, places=3)

    def test_keyframe_detection_nal_and_rai(self):
        self.assertTrue(starts_keyframe(make_video_pes(0, keyframe=True), H264))
        self.assertFalse(starts_keyframe(make_video_pes(0, keyframe=False), H264))
        self.assertTrue(starts_keyframe(make_video_pes(0, keyframe=True, use_rai=True), H264))

    def test_hevc_pps_alone_is_not_a_keyframe(self):
        # Per-picture PPS is common on broadcast HEVC; it must not cut mid-GOP.
        self.assertFalse(starts_keyframe(make_hevc_pes(0.0, [34]), HEVC))
        self.assertFalse(starts_keyframe(make_hevc_pes(0.0, [34, 1]), HEVC))  # PPS + TRAIL
        self.assertFalse(starts_keyframe(make_hevc_pes(0.0, [32, 1]), HEVC))  # VPS + TRAIL
        self.assertTrue(starts_keyframe(make_hevc_pes(0.0, [21]), HEVC))       # CRA
        self.assertTrue(starts_keyframe(make_hevc_pes(0.0, [34, 21]), HEVC))    # PPS + CRA
        self.assertTrue(starts_keyframe(make_hevc_pes(0.0, [32]), HEVC))       # VPS alone
        self.assertTrue(starts_keyframe(make_hevc_pes(0.0, [33]), HEVC))       # SPS alone

    def test_h264_repeated_parameter_sets_are_not_a_keyframe(self):
        # AUD + SPS + PPS + IDR: the real thing.
        self.assertTrue(starts_keyframe(make_h264_pes(0.0, [9, 7, 8, 5]), H264))
        # Parameter sets alone: the IDR slice starts in a later packet.
        self.assertTrue(starts_keyframe(make_h264_pes(0.0, [9, 7, 8]), H264))
        # Parameter sets repeated ahead of a non-IDR slice must not cut mid-GOP.
        self.assertFalse(starts_keyframe(make_h264_pes(0.0, [9, 7, 8, 1]), H264))
        self.assertFalse(starts_keyframe(make_h264_pes(0.0, [8]), H264))  # PPS alone
        self.assertFalse(starts_keyframe(make_h264_pes(0.0, [9, 1]), H264))

    def test_mpeg2_keyframe_detection(self):
        self.assertTrue(starts_keyframe(
            make_mpeg2_pes(0.0, [MPEG2_SEQUENCE_HEADER, mpeg2_picture(1)]), MPEG2))
        self.assertTrue(starts_keyframe(
            make_mpeg2_pes(0.0, [MPEG2_GOP_HEADER, mpeg2_picture(1)]), MPEG2))
        self.assertTrue(starts_keyframe(make_mpeg2_pes(0.0, [mpeg2_picture(1)]), MPEG2))
        self.assertFalse(starts_keyframe(make_mpeg2_pes(0.0, [mpeg2_picture(2)]), MPEG2))
        self.assertFalse(starts_keyframe(make_mpeg2_pes(0.0, [mpeg2_picture(3)]), MPEG2))
        # Reading MPEG start codes as H.264 NAL headers turns a slice at
        # vertical position 5 into an IDR and cuts in the middle of a picture.
        self.assertFalse(starts_keyframe(
            make_mpeg2_pes(0.0, [mpeg2_picture(2), MPEG2_SLICE_5]), MPEG2))

    def test_pid_extraction(self):
        self.assertEqual(packet_pid(make_pat()), 0)
        self.assertEqual(packet_pid(make_pmt()), PMT_PID)


def feed_stream(segmenter, gop_seconds, gop_count, start_pts=10.0, fillers_per_gop=5):
    """Feed `gop_count` GOPs of `gop_seconds` each; returns finished segments."""
    out = []
    for i in range(gop_count):
        pts = start_pts + i * gop_seconds
        out += segmenter.feed(make_video_pes(pts, keyframe=True))
        for j in range(fillers_per_gop):
            out += segmenter.feed(make_filler())
            out += segmenter.feed(make_video_pes(pts + (j + 1) * 0.2, keyframe=False))
    return out


class SegmenterTests(unittest.TestCase):
    def make_started(self, target=4.0, startup_cuts=0):
        # startup_cuts=0 keeps most tests on steady-state behavior; the
        # fast-start ladder has its own dedicated test.
        seg = TSSegmenter(target_duration=target, startup_keyframe_cuts=startup_cuts)
        seg.feed(make_pat())
        seg.feed(make_pmt())
        return seg

    def test_fast_start_ladder_cuts_first_segments_per_gop(self):
        seg = self.make_started(target=4.0, startup_cuts=3)
        finished = feed_stream(seg, gop_seconds=2.0, gop_count=9)
        durs = [round(s.duration, 3) for s in finished]
        # Cold start: first segments cut every keyframe for a fast window;
        # then the normal 4s target resumes. EXTINF uses keyframe boundary
        # elapsed (2s GOP), not the in-segment last-PTS shortfall.
        self.assertEqual(durs[:3], [2.0, 2.0, 2.0])
        self.assertTrue(all(abs(d - 4.0) < 0.01 for d in durs[3:]), durs)

    def test_cuts_on_keyframes_at_target_duration(self):
        seg = self.make_started(target=4.0)
        # 2-second GOPs: cuts must land every 2 GOPs (4.0s)
        finished = feed_stream(seg, gop_seconds=2.0, gop_count=7)
        self.assertEqual(len(finished), 3)
        for s in finished:
            # 2s GOPs cut every two GOPs: EXTINF is the keyframe boundary (4.0).
            self.assertAlmostEqual(s.duration, 4.0, places=2)

    def test_segments_start_with_pat_pmt(self):
        seg = self.make_started()
        finished = feed_stream(seg, gop_seconds=4.0, gop_count=3)
        self.assertGreaterEqual(len(finished), 1)
        for s in finished:
            self.assertEqual(s.data[0], 0x47)
            self.assertEqual(packet_pid(s.data[:TS_PACKET_SIZE]), 0)  # PAT first
            second = s.data[TS_PACKET_SIZE:2 * TS_PACKET_SIZE]
            self.assertEqual(packet_pid(second), PMT_PID)             # PMT second

    def test_no_segment_before_first_keyframe(self):
        seg = self.make_started()
        out = []
        out += seg.feed(make_video_pes(5.0, keyframe=False))
        out += seg.feed(make_filler())
        self.assertEqual(out, [])
        self.assertFalse(seg._collecting)

    def test_discontinuity_flag_propagates(self):
        seg = self.make_started(target=2.0)
        finished = feed_stream(seg, gop_seconds=2.0, gop_count=2)
        tail = seg.flag_discontinuity()
        if tail is not None:
            finished.append(tail)
        # Timeline jumps far ahead, as after a provider failover
        finished += feed_stream(seg, gop_seconds=2.0, gop_count=3, start_pts=9000.0)
        flagged = [s for s in finished if s.discontinuity]
        self.assertEqual(len(flagged), 1)

    def test_discontinuity_hard_cuts_open_segment(self):
        seg = self.make_started(target=4.0)
        # Open a segment and collect ~1s of frames without reaching the cut.
        seg.feed(make_video_pes(0.0, keyframe=True))
        for i in range(1, 4):
            seg.feed(make_video_pes(i * 0.5, keyframe=False))
        pre_gap_len = len(seg._current)
        self.assertTrue(seg._collecting)

        tail = seg.flag_discontinuity()
        # The open segment is finished immediately from pre-gap bytes only,
        # with its measured span, and is NOT the discontinuity-tagged one.
        self.assertIsNotNone(tail)
        self.assertEqual(len(tail.data), pre_gap_len)
        self.assertAlmostEqual(tail.duration, 1.5, places=3)
        self.assertFalse(tail.discontinuity)
        self.assertFalse(seg._collecting)

        # Post-gap data before a keyframe is dropped; collection resumes at
        # the next keyframe, and THAT segment carries the discontinuity tag.
        out = seg.feed(make_video_pes(9000.2, keyframe=False))
        self.assertEqual(out, [])
        self.assertFalse(seg._collecting)
        seg.feed(make_video_pes(9001.0, keyframe=True))
        self.assertTrue(seg._collecting)
        out = seg.feed(make_video_pes(9006.0, keyframe=True))  # closes it
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].discontinuity)

    def test_discontinuity_discards_empty_open_segment(self):
        seg = self.make_started(target=4.0)
        # Only the opening keyframe collected: measured span is zero.
        seg.feed(make_video_pes(0.0, keyframe=True))
        tail = seg.flag_discontinuity()
        self.assertIsNone(tail)
        self.assertFalse(seg._collecting)
        # The tag still lands on the next started segment.
        seg.feed(make_video_pes(100.0, keyframe=True))
        out = seg.feed(make_video_pes(105.0, keyframe=True))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].discontinuity)

    def test_resync_after_garbage(self):
        seg = self.make_started(target=2.0)
        seg.feed(b"\xde\xad\xbe\xef" * 33)  # garbage, not packet-aligned
        finished = feed_stream(seg, gop_seconds=2.0, gop_count=4)
        self.assertGreaterEqual(len(finished), 2)

    def test_pts_wrap_tolerated(self):
        seg = self.make_started(target=2.0)
        wrap_edge = (1 << 33) / 90000.0
        out = seg.feed(make_video_pes(wrap_edge - 1.0, keyframe=True))
        out += seg.feed(make_video_pes(1.0, keyframe=True))  # wrapped
        durations = [s.duration for s in out]
        for d in durations:
            self.assertGreater(d, 0)
            self.assertLessEqual(d, 8.0)

    def test_open_gop_hevc_with_per_picture_pps(self):
        # Broadcast-style HEVC: CRA every 2s, PPS before every picture, no RAI,
        # and a couple of leading pictures whose PTS is slightly before the CRA.
        seg = TSSegmenter(target_duration=2.0, startup_keyframe_cuts=0)
        seg.feed(make_pat())
        seg.feed(make_pmt(HEVC))
        out = []
        fps = 25.0
        for gop in range(4):
            cra_pts = gop * 2.0
            out += seg.feed(make_hevc_pes(cra_pts, [34, 21]))  # PPS + CRA
            for i in range(1, 50):
                pts = cra_pts + i / fps
                if i <= 2:
                    pts = cra_pts - (3 - i) * 0.04  # open-GOP reorder
                out += seg.feed(make_hevc_pes(pts, [34, 1]))  # PPS + TRAIL
        durs = [round(s.duration, 2) for s in out]
        # One segment per 2s GOP; no mid-GOP shredding from PPS or reorder.
        # EXTINF follows the keyframe boundary (2.0), not last-PTS shortfall.
        self.assertEqual(len(durs), 3)
        for d in durs:
            self.assertAlmostEqual(d, 2.0, places=2)

    def test_encoder_pts_reset_hard_cuts_and_continues(self):
        seg = self.make_started(target=2.0)
        out = []
        out += seg.feed(make_video_pes(100.0, keyframe=True))
        out += seg.feed(make_video_pes(101.0, keyframe=False))
        # Encoder restarts: PTS jumps from ~101 down to 0.
        out += seg.feed(make_video_pes(0.0, keyframe=True))
        out += seg.feed(make_video_pes(2.0, keyframe=True))
        self.assertGreaterEqual(len(out), 2)
        # Segment after the reset is tagged discontinuous.
        flagged = [s for s in out if s.discontinuity]
        self.assertEqual(len(flagged), 1)
        # And the segmenter keeps producing (does not wedge).
        self.assertAlmostEqual(flagged[0].duration, 2.0, places=3)

    def test_extinf_matches_open_gop_pts_span(self):
        """Open-GOP trailing pictures past the next keyframe PTS must not make
        EXTINF shorter than the media in the file."""
        seg = TSSegmenter(target_duration=4.0, startup_keyframe_cuts=0)
        out = []
        out += seg.feed(make_pat() + make_pmt(H264))
        out += seg.feed(make_video_pes(0.0, keyframe=True))
        for t in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.15, 4.28]:
            out += seg.feed(make_video_pes(t, keyframe=False))
        out += seg.feed(make_video_pes(4.104, keyframe=True))
        self.assertEqual(len(out), 1)
        # Keyframe spacing is 4.104; media span is 4.280. EXTINF must follow
        # the larger value so trailing open-GOP pictures are counted.
        self.assertAlmostEqual(out[0].duration, 4.28, places=2)

    def test_extinf_closed_gop_uses_keyframe_boundary(self):
        """Closed GOP: EXTINF is next_keyframe - start, not last_pts - start.

        PTS marks picture start, so last_pts - first_pts alone is ~1 frame
        short of the presentation covered until the next segment.
        """
        seg = TSSegmenter(target_duration=4.0, startup_keyframe_cuts=0)
        out = []
        out += seg.feed(make_pat() + make_pmt(H264))
        out += seg.feed(make_video_pes(0.0, keyframe=True))
        for t in [1.0, 2.0, 3.0, 3.9]:
            out += seg.feed(make_video_pes(t, keyframe=False))
        out += seg.feed(make_video_pes(4.0, keyframe=True))
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0].duration, 4.0, places=2)


class PlaylistTests(unittest.TestCase):
    def test_render_basic(self):
        window = [
            {"seq": 7, "dur": 4.0, "disc": False},
            {"seq": 8, "dur": 4.2, "disc": False},
            {"seq": 9, "dur": 3.9, "disc": True},
        ]
        text = render_media_playlist(window, 4, start_behind_seconds=5)
        self.assertIn("#EXTM3U", text)
        self.assertIn("#EXT-X-VERSION:3", text)
        self.assertIn("#EXT-X-TARGETDURATION:5", text)       # ceil(4.2)
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:7", text)
        self.assertIn("#EXTINF:4.200,", text)
        self.assertIn("8.ts", text)
        self.assertNotIn("#EXT-X-ENDLIST", text)             # live
        # Join offset matches new_client_behind_seconds; emitted once the
        # window (12.1s) is deep enough to honor it.
        self.assertIn("#EXT-X-START:TIME-OFFSET=-5.000,PRECISE=YES", text)
        # Discontinuity tag must precede its segment
        lines = text.splitlines()
        self.assertEqual(lines[lines.index("#EXT-X-DISCONTINUITY") + 2], "9.ts")

    def test_render_empty_window(self):
        text = render_media_playlist([], 4)
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:0", text)
        self.assertIn("#EXT-X-TARGETDURATION:4", text)       # ceil(4)
        self.assertNotIn("#EXT-X-START", text)               # no segments to offset from

    def test_discontinuity_sequence(self):
        window = [{"seq": 12, "dur": 4.0, "disc": True}, {"seq": 13, "dur": 4.0, "disc": False}]
        # Absent until nonzero: no tag means zero (RFC 8216 4.3.3.3).
        self.assertNotIn("#EXT-X-DISCONTINUITY-SEQUENCE", render_media_playlist(window, 4))
        text = render_media_playlist(window, 4, disc_sequence=2)
        lines = text.splitlines()
        self.assertIn("#EXT-X-DISCONTINUITY-SEQUENCE:2", lines)
        # Must precede the first segment and its discontinuity tag.
        self.assertLess(lines.index("#EXT-X-DISCONTINUITY-SEQUENCE:2"),
                        lines.index("#EXT-X-DISCONTINUITY"))

    def test_targetduration_constant_across_window_shift(self):
        # RFC 8216 6.2.1: TARGETDURATION MUST NOT change across reloads. With a
        # frozen adv_target the emitted value is identical no matter how the
        # window's max EXTINF flaps across integer ceilings.
        adv = 8
        w1 = [{"seq": 1, "dur": 4.05, "disc": False}, {"seq": 2, "dur": 4.60, "disc": False}]
        w2 = [{"seq": 2, "dur": 4.60, "disc": False}, {"seq": 3, "dur": 6.46, "disc": False}]
        w3 = [{"seq": 3, "dur": 6.46, "disc": False}, {"seq": 4, "dur": 5.01, "disc": False}]
        tds = set()
        starts = set()
        for w in (w1, w2, w3):
            text = render_media_playlist(w, 4, adv_target=adv, start_behind_seconds=5)
            td = [ln for ln in text.splitlines() if ln.startswith("#EXT-X-TARGETDURATION")]
            self.assertEqual(td, ["#EXT-X-TARGETDURATION:8"])
            tds.update(td)
            starts.update(ln for ln in text.splitlines() if ln.startswith("#EXT-X-START"))
            # TD must be >= every rounded EXTINF (RFC 8216 4.3.3.1).
            for e in w:
                self.assertLessEqual(round(e["dur"]), adv)
        self.assertEqual(len(tds), 1)      # never changed
        self.assertEqual(len(starts), 1)   # EXT-X-START also byte-stable

    def test_start_behind_gated_until_window_deep_enough(self):
        # Shallow window: offset larger than playlist duration is omitted.
        shallow = [{"seq": 1, "dur": 4.0, "disc": False}]
        text = render_media_playlist(shallow, 4, start_behind_seconds=5)
        self.assertNotIn("#EXT-X-START", text)
        deep = [
            {"seq": 1, "dur": 4.0, "disc": False},
            {"seq": 2, "dur": 4.0, "disc": False},
        ]
        text = render_media_playlist(deep, 4, start_behind_seconds=5)
        self.assertIn("#EXT-X-START:TIME-OFFSET=-5.000,PRECISE=YES", text)


AUDIO_PID = 256
AAC = 0x0F


def make_audio_pmt():
    payload = bytearray([0x00])
    es_loop = bytes([AAC, 0xE0 | (AUDIO_PID >> 8), AUDIO_PID & 0xFF, 0xF0, 0x00])
    section_length = 9 + len(es_loop) + 4
    payload += bytes([0x02, 0xB0 | (section_length >> 8), section_length & 0xFF])
    payload += bytes([0x00, 0x01, 0xC1, 0x00, 0x00])
    payload += bytes([0xE0 | (AUDIO_PID >> 8), AUDIO_PID & 0xFF, 0xF0, 0x00])
    payload += es_loop
    payload += bytes(4)
    return make_packet(PMT_PID, payload, pusi=True)


def make_audio_pes(pts_seconds):
    """PUSI AAC PES with PTS (stream_id 0xC0); extract_pts only needs the PTS."""
    p = make_pes_header(pts_seconds)
    p[3] = 0xC0  # audio stream_id
    p += bytes([0xFF, 0xF1, 0x50, 0x80, 0x01, 0x1F, 0xFC])  # ADTS-ish filler
    return make_packet(AUDIO_PID, p, pusi=True)


class AudioOnlySegmenterTests(unittest.TestCase):
    def test_pmt_without_video_enables_audio_mode_immediately(self):
        seg = TSSegmenter(target_duration=4.0, startup_keyframe_cuts=0)
        self.assertEqual(seg.feed(make_pat() + make_audio_pmt()), [])
        self.assertTrue(seg.audio_only)
        self.assertFalse(seg.video_detected)

    def test_audio_only_cuts_on_pts_target(self):
        seg = TSSegmenter(target_duration=4.0, startup_keyframe_cuts=0)
        out = []
        out.extend(seg.feed(make_pat() + make_audio_pmt()))
        # Open on first PTS-bearing audio AU, then cut at +4s.
        out.extend(seg.feed(make_audio_pes(10.0)))
        out.extend(seg.feed(make_packet(AUDIO_PID, b"\x00" * 20)))
        out.extend(seg.feed(make_audio_pes(12.0)))
        self.assertEqual(out, [])
        out.extend(seg.feed(make_audio_pes(14.0)))
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0].duration, 4.0, places=2)
        self.assertGreater(len(out[0].data), TS_PACKET_SIZE * 2)


if __name__ == "__main__":
    unittest.main()
