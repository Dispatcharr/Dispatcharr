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
- A segment may only begin on a video keyframe access unit. Keyframes are
  detected via the adaptation-field random_access_indicator when the
  provider sets it, with a fallback NAL-header scan (H.264 IDR/SPS,
  H.265 IRAP/parameter sets) for providers that do not.
- Segment duration is measured from video PES PTS deltas, cut at the
  first keyframe at or after the target duration.
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

PTS_CLOCK = 90000.0
# 33-bit PTS wraps every ~26.5 hours; treat large negative deltas as a wrap.
PTS_WRAP = 1 << 33


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


def parse_pmt(packet):
    """Return (video_pid, video_stream_type) from a PMT packet, or (None, None)."""
    base = packet_payload_offset(packet)
    if base is None or base + 1 >= TS_PACKET_SIZE:
        return None, None
    pointer = packet[base]
    section = base + 1 + pointer
    if section + 12 >= TS_PACKET_SIZE:
        return None, None
    section_length = ((packet[section + 1] & 0x0F) << 8) | packet[section + 2]
    program_info_length = ((packet[section + 10] & 0x0F) << 8) | packet[section + 11]
    offset = section + 12 + program_info_length
    section_end = min(section + 3 + section_length - 4, TS_PACKET_SIZE - 1)

    while offset + 4 < section_end:
        stream_type = packet[offset]
        es_pid = ((packet[offset + 1] & 0x1F) << 8) | packet[offset + 2]
        es_info_length = ((packet[offset + 3] & 0x0F) << 8) | packet[offset + 4]
        if stream_type in VIDEO_STREAM_TYPES:
            return es_pid, stream_type
        offset += 5 + es_info_length
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


def starts_keyframe(packet, video_stream_type):
    """
    Does this PUSI video packet open a keyframe access unit?

    Prefers the adaptation-field random_access_indicator; falls back to
    scanning visible NAL start codes. Encoders emit parameter sets
    immediately before IDR/IRAP frames, so SPS/VPS in the first packet is
    a reliable keyframe marker even when the keyframe NAL itself starts
    in a later packet of the same PES.
    """
    if packet_random_access(packet):
        return True

    base = packet_payload_offset(packet)
    if base is None or base + 9 >= TS_PACKET_SIZE:
        return False
    header_len = packet[base + 8]
    i = base + 9 + header_len
    end = TS_PACKET_SIZE - 4
    while i < end:
        if packet[i] == 0x00 and packet[i + 1] == 0x00:
            nal_start = -1
            if packet[i + 2] == 0x01:
                nal_start = i + 3
            elif packet[i + 2] == 0x00 and i + 3 < end and packet[i + 3] == 0x01:
                nal_start = i + 4
            if 0 < nal_start < TS_PACKET_SIZE:
                if video_stream_type == 0x24:
                    # H.265: nal_unit_type in bits 1-6 of the first byte.
                    nal_type = (packet[nal_start] >> 1) & 0x3F
                    # IRAP (16-21) or VPS/SPS/PPS (32-34)
                    if 16 <= nal_type <= 21 or 32 <= nal_type <= 34:
                        return True
                else:
                    # H.264: nal_unit_type in bits 0-4.
                    nal_type = packet[nal_start] & 0x1F
                    # IDR (5) or SPS (7)
                    if nal_type in (5, 7):
                        return True
                i = nal_start
                continue
        i += 1
    return False


class TSSegmenter:
    """
    Stateful packet-copy segmenter. Feed it raw TS bytes (any chunking);
    it returns finished Segment objects as keyframe boundaries are crossed.
    """

    def __init__(self, target_duration=4.0, max_segment_duration=None):
        self.target_duration = float(target_duration)
        # Hard ceiling: force a cut before a segment can exceed this, so no
        # emitted EXTINF ever exceeds the frozen advertised TARGETDURATION even
        # on a keyframe drought (RFC 8216 4.3.3.1). Defaults to 2x the target.
        self.max_segment_duration = float(
            max_segment_duration if max_segment_duration else 2 * target_duration)
        self._pending = bytearray()
        self._current = bytearray()
        self._pat_packet = None
        self._pmt_packet = None
        self._pmt_pid = None
        self._video_pid = None
        self._video_stream_type = None
        self._segment_start_pts = None
        # First / most-recent video PTS in the current segment; used to report a
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

    def flag_discontinuity(self):
        """Mark that the NEXT emitted segment follows a stream discontinuity
        (provider failover, buffer skip-ahead)."""
        self._pending_discontinuity = True
        # PTS timeline may jump arbitrarily across the discontinuity.
        self._segment_start_pts = None

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
            video_pid, stream_type = parse_pmt(packet)
            if video_pid is not None:
                # Re-learned continuously so PID/codec changes across
                # provider failovers are tolerated.
                self._video_pid = video_pid
                self._video_stream_type = stream_type
            return None

        if self._video_pid is None:
            return None

        finished = None
        if pid == self._video_pid and packet_pusi(packet):
            pts = extract_pts(packet)
            keyframe = starts_keyframe(packet, self._video_stream_type)
            if pts is not None:
                self._seg_last_pts = pts

            if not self._collecting:
                if keyframe:
                    self._begin_segment(pts)
            elif keyframe and pts is not None:
                if self._segment_start_pts is None:
                    # Discontinuity reset the timeline: cut here, reporting the
                    # measured span of the segment being closed (RFC 8216 4.3.2.1)
                    # rather than substituting the nominal target.
                    finished = self._finish_segment(self._measured_span())
                    self._begin_segment(pts)
                else:
                    elapsed = self._elapsed(pts, self._segment_start_pts)
                    if elapsed >= self.target_duration:
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

    def _elapsed(self, pts, start):
        """Wrap-safe presentation-time delta in seconds."""
        d = pts - start
        if d < 0:
            d += PTS_WRAP / PTS_CLOCK
        return d

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
        return segment


def render_media_playlist(window, target_duration, segment_name="{seq}.ts", adv_target=None):
    """
    Render an HLS media playlist (RFC 8216, version 3) from a window of
    segment descriptors: [{"seq": int, "dur": float, "disc": bool}, ...].
    Segment URIs are relative so they resolve against the playlist URL.

    ``adv_target`` is the manager's frozen EXT-X-TARGETDURATION; when supplied it
    is emitted verbatim so the value never changes across reloads (RFC 8216
    6.2.1). Without it (legacy descriptor) the per-window ceil is used.
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
