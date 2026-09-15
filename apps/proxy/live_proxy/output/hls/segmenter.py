"""
MPEG-TS HLS segmenter - pure packet-copy splitting, no remux.

The live proxy's source ring already guarantees 188-byte packet alignment
(StreamBuffer.add_chunk), and TS segments are first-class HLS citizens
(RFC 8216 section 3.2), so producing HLS from the ring is a matter of
CUTTING the existing packets into keyframe-aligned segments. No bytes are
rewritten, no subprocess is spawned.

This module is intentionally dependency-free (stdlib only, no Django or
Redis imports) so the parsing logic is unit-testable in isolation.

Segmentation rules:
- Video: a segment may only begin on a video keyframe access unit.
  Keyframes are detected via the adaptation-field random_access_indicator
  when the provider sets it, with a codec-aware start-code scan as a
  fallback (H.264 IDR, H.265 IRAP, MPEG-1/2 sequence header, GOP header or
  I-picture). A parameter set counts as a keyframe marker only when the
  packet carries no non-keyframe slice of its own; many encoders repeat
  parameter sets before every picture. Duration is measured from video
  PES PTS deltas, cut at the first keyframe at or after the target.
- Audio-only: when a parsed PMT lists no video ES (e.g. radio as MPEG-TS
  AAC), switch immediately to cutting on audio PES PTS at the target
  duration. No multi-second wait: the PMT is authoritative once seen.
- Every emitted segment is prefixed with the most recently seen PAT and
  PMT packets so each segment decodes independently, as HLS requires.
"""

TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47

# ISO 13818-1 / ATSC stream_type values
VIDEO_STREAM_TYPES = {
    0x01: "mpeg1",
    0x02: "mpeg2",
    0x1B: "h264",
    0x24: "h265",
}

# Common audio elementary stream types in live MPEG-TS
AUDIO_STREAM_TYPES = {
    0x03: "mpeg1-audio",
    0x04: "mpeg2-audio",
    0x0F: "aac-adts",
    0x11: "aac-latm",
    0x81: "ac3",
    0x87: "eac3",
}

PTS_CLOCK = 90000.0
# 33-bit PTS wraps every ~26.5 hours.
PTS_WRAP = 1 << 33
PTS_WRAP_SECONDS = PTS_WRAP / PTS_CLOCK
# Open-GOP leading pictures are typically tens of ms behind the CRA.
# A multi-second backward jump that is not a 33-bit wrap is an encoder
# timeline reset and must hard-cut, not be mistaken for B-frame reorder.
PTS_RESET_BACKWARD_SECONDS = 2.0


class Segment:
    """One finished HLS media segment."""

    __slots__ = ("data", "duration", "discontinuity")

    def __init__(self, data, duration, discontinuity=False):
        self.data = data
        self.duration = duration
        self.discontinuity = discontinuity


def packet_pid(packet):
    """13-bit PID of a TS packet."""
    return ((packet[1] & 0x1F) << 8) | packet[2]


def packet_pusi(packet):
    """payload_unit_start_indicator flag."""
    return bool(packet[1] & 0x40)


def packet_payload_offset(packet):
    """Byte offset of the payload within the packet, or None if no payload."""
    afc = (packet[3] >> 4) & 0x03
    if afc == 0x01:
        return 4
    if afc == 0x03:
        af_len = packet[4]
        offset = 5 + af_len
        return offset if offset < TS_PACKET_SIZE else None
    return None


def packet_random_access(packet):
    """adaptation-field random_access_indicator, when an AF is present."""
    afc = (packet[3] >> 4) & 0x03
    if afc in (0x02, 0x03) and packet[4] > 0:
        return bool(packet[5] & 0x40)
    return False


def parse_pat(packet):
    """Return the PMT PID of the first non-zero program, or None."""
    base = packet_payload_offset(packet)
    if base is None or base + 1 >= TS_PACKET_SIZE:
        return None
    pointer = packet[base]
    section = base + 1 + pointer
    # table_id(1) section_length(2) tsid(2) ver(1) sec(1) last(1) = 8 bytes,
    # then 4-byte program entries.
    offset = section + 8
    while offset + 3 < TS_PACKET_SIZE:
        program_number = (packet[offset] << 8) | packet[offset + 1]
        pid = ((packet[offset + 2] & 0x1F) << 8) | packet[offset + 3]
        if program_number != 0:
            return pid
        offset += 4
    return None


def parse_pmt_streams(packet):
    """Return [(stream_type, es_pid), ...] from a PMT packet, or None if unparseable."""
    base = packet_payload_offset(packet)
    if base is None or base + 1 >= TS_PACKET_SIZE:
        return None
    pointer = packet[base]
    section = base + 1 + pointer
    if section + 12 >= TS_PACKET_SIZE:
        return None
    if packet[section] != 0x02:  # table_id must be PMT
        return None
    section_length = ((packet[section + 1] & 0x0F) << 8) | packet[section + 2]
    program_info_length = ((packet[section + 10] & 0x0F) << 8) | packet[section + 11]
    offset = section + 12 + program_info_length
    section_end = min(section + 3 + section_length - 4, TS_PACKET_SIZE - 1)

    streams = []
    while offset + 4 < section_end:
        stream_type = packet[offset]
        es_pid = ((packet[offset + 1] & 0x1F) << 8) | packet[offset + 2]
        es_info_length = ((packet[offset + 3] & 0x0F) << 8) | packet[offset + 4]
        streams.append((stream_type, es_pid))
        offset += 5 + es_info_length
    return streams


def parse_pmt(packet):
    """Return (video_pid, video_stream_type) from a PMT packet, or (None, None)."""
    streams = parse_pmt_streams(packet)
    if not streams:
        return None, None
    for stream_type, es_pid in streams:
        if stream_type in VIDEO_STREAM_TYPES:
            return es_pid, stream_type
    return None, None


def parse_pmt_audio(packet):
    """Return (audio_pid, audio_stream_type) for the first audio ES, or (None, None)."""
    streams = parse_pmt_streams(packet)
    if not streams:
        return None, None
    for stream_type, es_pid in streams:
        if stream_type in AUDIO_STREAM_TYPES:
            return es_pid, stream_type
    return None, None


def extract_pts(packet):
    """PTS in seconds from a PES header starting in this packet, or None."""
    base = packet_payload_offset(packet)
    if base is None or base + 13 >= TS_PACKET_SIZE:
        return None
    if packet[base] != 0x00 or packet[base + 1] != 0x00 or packet[base + 2] != 0x01:
        return None
    flags = packet[base + 7]
    if not (flags & 0x80):
        return None
    b = packet
    pts = (
        ((b[base + 9] >> 1) & 0x07) << 30
        | b[base + 10] << 22
        | ((b[base + 11] >> 1) & 0x7F) << 15
        | b[base + 12] << 7
        | (b[base + 13] >> 1)
    )
    return pts / PTS_CLOCK


def _iter_start_code_offsets(packet):
    """Yield the offset of the byte following each start code prefix visible in
    this packet's PES payload. A four-byte prefix (00 00 00 01) contains the
    three-byte one, so a single search finds both."""
    base = packet_payload_offset(packet)
    if base is None or base + 9 >= TS_PACKET_SIZE:
        return
    i = base + 9 + packet[base + 8]
    while True:
        found = packet.find(b"\x00\x00\x01", i)
        if found < 0:
            break
        i = found + 3
        if i >= TS_PACKET_SIZE:
            break
        yield i


def _h264_starts_keyframe(packet):
    """IDR (nal_unit_type 5) is definitive. SPS (7) counts only until a
    non-IDR slice (1-4) shows up in the same packet."""
    seen_parameter_set = False
    for offset in _iter_start_code_offsets(packet):
        nal_type = packet[offset] & 0x1F
        if nal_type == 5:
            return True
        if 1 <= nal_type <= 4:
            return False
        if nal_type == 7:
            seen_parameter_set = True
    return seen_parameter_set


def _hevc_starts_keyframe(packet):
    """IRAP (16-21) is definitive. VPS/SPS (32-33) count only until a non-IRAP
    VCL NAL (0-15) shows up. PPS (34) is never evidence on its own: many
    encoders emit one before every picture, and treating that as a keyframe
    shreds the GOP into unplayable fragments."""
    seen_parameter_set = False
    for offset in _iter_start_code_offsets(packet):
        nal_type = (packet[offset] >> 1) & 0x3F
        if 16 <= nal_type <= 21:
            return True
        if nal_type <= 15:
            return False
        if nal_type in (32, 33):
            seen_parameter_set = True
    return seen_parameter_set


def _mpeg2_starts_keyframe(packet):
    """MPEG-1/2 random access points: a sequence header, a GOP header, or an
    I-picture. Start-code values are read as start-code values; scanning them
    as H.264 NAL headers makes slice codes 0x05 and 0x07 look like IDR/SPS."""
    for offset in _iter_start_code_offsets(packet):
        code = packet[offset]
        if code in (0xB3, 0xB8):  # sequence_header, group_of_pictures_header
            return True
        if code == 0x00:  # picture_start_code
            if offset + 2 >= TS_PACKET_SIZE:
                return False
            # picture_coding_type follows a 10-bit temporal_reference; 1 = I.
            return ((packet[offset + 2] >> 3) & 0x07) == 1
        if 0x01 <= code <= 0xAF:  # slice: already inside a picture
            return False
    return False


_KEYFRAME_SCANNERS = {
    0x01: _mpeg2_starts_keyframe,
    0x02: _mpeg2_starts_keyframe,
    0x1B: _h264_starts_keyframe,
    0x24: _hevc_starts_keyframe,
}


def starts_keyframe(packet, video_stream_type):
    """
    Does this PUSI video packet open a keyframe access unit?

    Prefers the adaptation-field random_access_indicator; falls back to a
    codec-aware scan of the start codes visible in this packet. Encoders emit
    parameter sets immediately before an IDR/IRAP frame, so a parameter set in
    the first packet marks a keyframe even when the keyframe's own slice
    starts in a later packet of the same PES. A parameter set that shares the
    packet with a non-keyframe slice marks nothing: it is a repeat.
    """
    if packet_random_access(packet):
        return True
    scanner = _KEYFRAME_SCANNERS.get(video_stream_type)
    return scanner(packet) if scanner else False


class TSSegmenter:
    """
    Stateful packet-copy segmenter. Feed it raw TS bytes (any chunking);
    it returns finished Segment objects as keyframe boundaries are crossed.
    """

    def __init__(self, target_duration=4.0, max_segment_duration=None,
                 startup_keyframe_cuts=4):
        self.target_duration = float(target_duration)
        # Hard ceiling: force a cut before a segment can exceed this, so no
        # emitted EXTINF ever exceeds the frozen advertised TARGETDURATION even
        # on a keyframe drought (RFC 8216 4.3.3.1). Defaults to 2x the target.
        self.max_segment_duration = float(
            max_segment_duration if max_segment_duration else 2 * target_duration)
        # Fast-start ladder: a cold channel accumulates segments at live
        # cadence, so with a 4s target a player waits ~8-12s for enough
        # media to start. The first N segments therefore cut at EVERY
        # keyframe (one GOP each, typically 1-3s), which gets a playable
        # playlist up in one GOP and 3 segments within a few seconds; the
        # cut target then ramps back to normal. Steady-state output is
        # unchanged, and every starter EXTINF is well under the frozen
        # TARGETDURATION.
        self._startup_cuts_remaining = int(startup_keyframe_cuts)
        self._pending = bytearray()
        self._current = bytearray()
        self._pat_packet = None
        self._pmt_packet = None
        self._pmt_pid = None
        self._video_pid = None
        self._video_stream_type = None
        self._audio_pid = None
        self._audio_only = False
        self._segment_start_pts = None
        # First / most-recent timing PTS in the current segment; used to report a
        # MEASURED duration on the discontinuity cut instead of substituting the
        # nominal target (RFC 8216 4.3.2.1: EXTINF must be accurate).
        self._seg_first_pts = None
        self._seg_last_pts = None
        self._collecting = False
        self._pending_discontinuity = False
        self._current_discontinuity = False

    @property
    def video_detected(self):
        return self._video_pid is not None

    @property
    def audio_only(self):
        return self._audio_only

    def flag_discontinuity(self):
        """Mark a stream discontinuity (provider failover, buffer skip-ahead).

        Hard cut: the in-progress segment is closed IMMEDIATELY from the bytes
        already collected, so pre-gap and post-gap data can never share a
        segment. Collection resumes at the next video keyframe (or audio PES
        with PTS in audio-only mode), and that new segment is the one tagged
        with EXT-X-DISCONTINUITY.

        Returns the finished pre-gap Segment, or None when the open segment
        held nothing playable (its measured span is zero) and was discarded.
        """
        finished = None
        if self._collecting:
            span = 0.0
            if self._seg_first_pts is not None and self._seg_last_pts is not None:
                span = self._elapsed(self._seg_last_pts, self._seg_first_pts)
            if span > 0:
                finished = self._finish_segment(span)
        # Drop any un-finished remainder and wait for the next start point; the
        # PTS timeline may jump arbitrarily across the discontinuity.
        self._collecting = False
        self._current = bytearray()
        self._current_discontinuity = False
        self._segment_start_pts = None
        self._seg_first_pts = None
        self._seg_last_pts = None
        self._pending_discontinuity = True
        return finished

    def feed(self, data):
        """Consume raw TS bytes; return a list of finished Segments (possibly empty)."""
        segments = []
        self._pending.extend(data)

        while len(self._pending) >= TS_PACKET_SIZE:
            if self._pending[0] != TS_SYNC_BYTE:
                sync = self._pending.find(bytes([TS_SYNC_BYTE]))
                if sync < 0:
                    self._pending.clear()
                    break
                del self._pending[:sync]
                continue
            # Require the next packet to also be in sync (or be the tail) so
            # a stray 0x47 in payload cannot fake an alignment point.
            if (
                len(self._pending) >= TS_PACKET_SIZE + 1
                and self._pending[TS_PACKET_SIZE] != TS_SYNC_BYTE
            ):
                del self._pending[:1]
                continue

            packet = bytes(self._pending[:TS_PACKET_SIZE])
            del self._pending[:TS_PACKET_SIZE]
            finished = self._handle_packet(packet)
            if finished is not None:
                segments.append(finished)

        return segments

    def _handle_packet(self, packet):
        pid = packet_pid(packet)

        if pid == 0:
            self._pat_packet = packet
            if self._pmt_pid is None:
                self._pmt_pid = parse_pat(packet)
            return None
        if self._pmt_pid is not None and pid == self._pmt_pid:
            self._pmt_packet = packet
            streams = parse_pmt_streams(packet)
            if streams is None:
                return None
            video_pid, stream_type = None, None
            audio_pid = None
            for st, es_pid in streams:
                if video_pid is None and st in VIDEO_STREAM_TYPES:
                    video_pid, stream_type = es_pid, st
                elif audio_pid is None and st in AUDIO_STREAM_TYPES:
                    audio_pid = es_pid
            if video_pid is not None:
                # Re-learned continuously so PID/codec changes across
                # provider failovers are tolerated.
                self._video_pid = video_pid
                self._video_stream_type = stream_type
                self._audio_only = False
                self._audio_pid = audio_pid
            elif audio_pid is not None:
                # PMT listed elementary streams with no video: audio-only
                # (radio / music channels). Decide immediately from the table;
                # do not wait for a video PID that will never arrive.
                self._audio_pid = audio_pid
                self._audio_only = True
                self._video_pid = None
                self._video_stream_type = None
            return None

        if self._video_pid is None and not self._audio_only:
            return None

        if self._audio_only:
            return self._handle_audio_packet(packet, pid)

        finished = None
        if pid == self._video_pid and packet_pusi(packet):
            pts = extract_pts(packet)
            keyframe = starts_keyframe(packet, self._video_stream_type)

            # Encoder / provider PTS reset (large backward jump that is not a
            # 33-bit wrap). Hard-cut like an input discontinuity so we do not
            # wedge waiting for elapsed to become positive again, and so we
            # do not lean on the old "any negative is a wrap" accident.
            if (
                pts is not None
                and self._collecting
                and self._segment_start_pts is not None
                and self._is_timeline_reset(pts, self._segment_start_pts)
            ):
                finished = self.flag_discontinuity()
                if keyframe:
                    self._begin_segment(pts)
                    self._current.extend(packet)
                return finished

            if pts is not None:
                # Track presentation-max PTS so open-GOP leading pictures
                # (PTS slightly before the CRA) do not pull _seg_last_pts
                # backward and corrupt measured EXTINF.
                if self._seg_first_pts is None:
                    self._seg_last_pts = pts
                elif self._elapsed(pts, self._seg_first_pts) >= self._elapsed(
                    self._seg_last_pts, self._seg_first_pts
                ):
                    self._seg_last_pts = pts

            if not self._collecting:
                if keyframe:
                    self._begin_segment(pts)
            elif keyframe and pts is not None:
                if self._segment_start_pts is None:
                    # Segment was opened on a keyframe PES that had no PTS
                    # (parameter-set-only AU). Close it with a measured span
                    # fallback and re-anchor on this PTS-bearing keyframe.
                    finished = self._finish_segment(self._measured_span())
                    self._begin_segment(pts)
                else:
                    elapsed = self._elapsed(pts, self._segment_start_pts)
                    # Fast-start ladder: while starter cuts remain, any
                    # keyframe closes the segment (elapsed > 0 skips
                    # same-PTS duplicates); afterwards the normal target
                    # applies.
                    cut_at = 0.0 if self._startup_cuts_remaining > 0 else self.target_duration
                    if elapsed >= cut_at and elapsed > 0:
                        finished = self._finish_segment(elapsed)
                        self._begin_segment(pts)
            elif pts is not None and self._collecting and self._segment_start_pts is not None:
                # Keyframe drought: force a cut so the segment cannot exceed the
                # frozen TARGETDURATION. Cutting mid-GOP yields a segment that is
                # not keyframe-independent, an accepted last resort that a healthy
                # GOP (which cuts on its keyframes well under this ceiling) never
                # reaches.
                elapsed = self._elapsed(pts, self._segment_start_pts)
                if elapsed >= self.max_segment_duration:
                    finished = self._finish_segment(elapsed)
                    self._begin_segment(pts)

        if self._collecting:
            self._current.extend(packet)
        return finished

    def _handle_audio_packet(self, packet, pid):
        """Cut on audio PES PTS once the PMT has confirmed there is no video."""
        finished = None
        if pid == self._audio_pid and packet_pusi(packet):
            pts = extract_pts(packet)
            if (
                pts is not None
                and self._collecting
                and self._segment_start_pts is not None
                and self._is_timeline_reset(pts, self._segment_start_pts)
            ):
                finished = self.flag_discontinuity()
                self._begin_segment(pts)
                self._current.extend(packet)
                return finished

            if pts is not None:
                if self._seg_first_pts is None:
                    self._seg_last_pts = pts
                elif self._elapsed(pts, self._seg_first_pts) >= self._elapsed(
                    self._seg_last_pts, self._seg_first_pts
                ):
                    self._seg_last_pts = pts

            if not self._collecting:
                if pts is not None:
                    self._begin_segment(pts)
            elif pts is not None and self._segment_start_pts is not None:
                elapsed = self._elapsed(pts, self._segment_start_pts)
                if elapsed >= self.target_duration and elapsed > 0:
                    finished = self._finish_segment(elapsed)
                    self._begin_segment(pts)

        if self._collecting:
            self._current.extend(packet)
        return finished

    def _elapsed(self, pts, start):
        """Signed presentation-time delta in seconds, wrap-safe.

        Small negative deltas (open-GOP leading pictures) stay negative.
        Only deltas past half the 33-bit wrap period are treated as wraps.
        """
        d = pts - start
        if d < -PTS_WRAP_SECONDS / 2:
            d += PTS_WRAP_SECONDS
        elif d > PTS_WRAP_SECONDS / 2:
            d -= PTS_WRAP_SECONDS
        return d

    def _is_timeline_reset(self, pts, start):
        """True when pts jumped backward far enough to be an encoder reset,
        not open-GOP reorder and not a 33-bit wrap."""
        raw = pts - start
        if raw < -PTS_WRAP_SECONDS / 2:
            return False
        return raw < -PTS_RESET_BACKWARD_SECONDS

    def _measured_span(self):
        """Best measured duration of the segment being closed, from the first and
        last video PTS seen. Falls back to the target only when unmeasurable or
        nonsensical (e.g. a timeline jump)."""
        if self._seg_first_pts is None or self._seg_last_pts is None:
            return self.target_duration
        d = self._elapsed(self._seg_last_pts, self._seg_first_pts)
        if d <= 0 or d > 4 * self.target_duration:
            return self.target_duration
        return d

    def _begin_segment(self, pts):
        self._current = bytearray()
        if self._pat_packet:
            self._current.extend(self._pat_packet)
        if self._pmt_packet:
            self._current.extend(self._pmt_packet)
        self._segment_start_pts = pts
        self._seg_first_pts = pts
        self._seg_last_pts = pts
        self._collecting = True
        self._current_discontinuity = self._pending_discontinuity
        self._pending_discontinuity = False

    def _finish_segment(self, duration):
        if duration <= 0 or duration > 4 * self.target_duration:
            duration = self.target_duration
        segment = Segment(
            bytes(self._current),
            float(duration),
            discontinuity=self._current_discontinuity,
        )
        self._current = bytearray()
        self._current_discontinuity = False
        if self._startup_cuts_remaining > 0:
            self._startup_cuts_remaining -= 1
        return segment


def render_media_playlist(window, target_duration, segment_name="{seq}.ts", adv_target=None,
                          disc_sequence=0):
    """
    Render an HLS media playlist (RFC 8216, version 3) from a window of
    segment descriptors: [{"seq": int, "dur": float, "disc": bool}, ...].
    Segment URIs are relative so they resolve against the playlist URL.

    ``adv_target`` is the manager's frozen EXT-X-TARGETDURATION; when supplied it
    is emitted verbatim so the value never changes across reloads (RFC 8216
    6.2.1). Without it (legacy descriptor) the per-window ceil is used.

    ``disc_sequence`` is how many EXT-X-DISCONTINUITY tags have already slid out
    of the window. Emitting it keeps the discontinuity sequence numbers of the
    segments still listed unchanged as the window rolls (RFC 8216 4.3.3.3); an
    absent tag means zero, so it only needs to appear once it is nonzero.
    """
    # Frozen live-edge offset: ~2.5 config target-durations (~10s at the 4s
    # default) so the value is a session constant and never drifts across
    # reloads as the window slides (unlike a window-max derivation).
    start_offset = 2.5 * target_duration
    if not window:
        return (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            # Ceil to match the populated branch; a fractional target must never
            # round DOWN below a real EXTINF (RFC 8216 4.3.3.1).
            f"#EXT-X-TARGETDURATION:{adv_target if adv_target else int(max(target_duration, 1) + 0.999)}\n"
            "#EXT-X-MEDIA-SEQUENCE:0\n"
        )
    total_duration = sum(entry["dur"] for entry in window)
    # TARGETDURATION: prefer the manager's frozen constant. RFC 8216 6.2.1 forbids
    # it changing across reloads; a per-render ceil(window max) flaps on GOP
    # jitter, and AVPlayer latches the first value and stops advancing on a
    # contradiction. Legacy fallback keeps the ceil.
    advertised_target = adv_target if adv_target else int(max(entry["dur"] for entry in window) + 0.999)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{advertised_target}",
        f"#EXT-X-MEDIA-SEQUENCE:{window[0]['seq']}",
    ]
    if disc_sequence:
        lines.append(f"#EXT-X-DISCONTINUITY-SEQUENCE:{disc_sequence}")
    # Emit EXT-X-START only once the window is deep enough to honor the frozen
    # offset, so the tag's value is stable across reloads (RFC 8216 6.2.1). It
    # pins the join point deterministically across players; a client that sets
    # its own offset still overrides it.
    if total_duration >= start_offset:
        lines.append(f"#EXT-X-START:TIME-OFFSET=-{start_offset:.3f},PRECISE=YES")
    for entry in window:
        if entry.get("disc"):
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append(f"#EXTINF:{entry['dur']:.3f},")
        lines.append(segment_name.format(seq=entry["seq"]))
    return "\n".join(lines) + "\n"
