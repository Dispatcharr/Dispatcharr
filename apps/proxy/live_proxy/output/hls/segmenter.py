"""
MPEG-TS HLS segmenter - pure packet-copy splitting, no remux.

The live proxy's source ring already guarantees 188-byte packet alignment
(StreamBuffer.add_chunk), and TS segments are first-class HLS citizens
(RFC 8216 section 3.2), so producing HLS from the ring is a matter of
CUTTING the existing packets into keyframe-aligned segments. Existing
bytes are not rewritten; a new segment may get a few extra TS packets
(PAT/PMT, and H.264/HEVC parameter sets when the opening keyframe lacks
them). No subprocess is spawned.

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
- H.264/HEVC parameter sets (SPS/PPS, plus VPS for HEVC) are cached when
  seen and injected after PAT/PMT when a new segment opens on a keyframe
  that lacks them. Apple's HLS Authoring Specification requires video
  segments to start with an IDR (item 7.4); with transport-stream delivery
  there is no separate init segment, so that IDR must carry its own
  parameter sets in-band to be independently decodable.
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

# Parameter-set NAL types needed for an independently decodable TS start.
_H264_PARAM_TYPES = (7, 8)       # SPS, PPS
_HEVC_PARAM_TYPES = (32, 33, 34)  # VPS, SPS, PPS
_MAX_PARAM_NAL_BYTES = 512

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


def packet_continuity_counter(packet):
    """4-bit continuity_counter."""
    return packet[3] & 0x0F


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
    """Return [(stream_type, es_pid), ...] from a PMT packet, or None if unparseable.

    Returns None when the declared section does not fit in this TS packet
    (multi-packet / truncated PMT). Callers must not treat a partial ES loop
    as authoritative, or audio descriptors in packet 1 with video in packet 2
    would look like an audio-only stream.
    """
    base = packet_payload_offset(packet)
    if base is None or base + 1 >= TS_PACKET_SIZE:
        return None
    pointer = packet[base]
    section = base + 1 + pointer
    if section + 12 >= TS_PACKET_SIZE:
        return None
    if packet[section] != 0x02:  # table_id must be PMT
        return None
    # section_length: bytes after the length field, including CRC.
    section_length = ((packet[section + 1] & 0x0F) << 8) | packet[section + 2]
    if section + 3 + section_length > TS_PACKET_SIZE:
        return None
    program_info_length = ((packet[section + 10] & 0x0F) << 8) | packet[section + 11]
    offset = section + 12 + program_info_length
    # ES loop ends before the 4-byte CRC.
    section_end = section + 3 + section_length - 4
    if offset > section_end:
        return None

    streams = []
    while offset + 4 < section_end:
        stream_type = packet[offset]
        es_pid = ((packet[offset + 1] & 0x1F) << 8) | packet[offset + 2]
        es_info_length = ((packet[offset + 3] & 0x0F) << 8) | packet[offset + 4]
        entry_end = offset + 5 + es_info_length
        if entry_end > section_end:
            # Truncated descriptor inside an otherwise sized section: refuse.
            return None
        streams.append((stream_type, es_pid))
        offset = entry_end
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


def _nal_type(header_byte, stream_type):
    if stream_type == 0x1B:
        return header_byte & 0x1F
    if stream_type == 0x24:
        return (header_byte >> 1) & 0x3F
    return None


def _param_types_for(stream_type):
    if stream_type == 0x1B:
        return _H264_PARAM_TYPES
    if stream_type == 0x24:
        return _HEVC_PARAM_TYPES
    return ()


def _start_code_begin(packet, nal_header_offset):
    """Byte index of the 00 00 01 / 00 00 00 01 prefix before a NAL header."""
    sc = nal_header_offset - 3
    if sc > 0 and packet[sc - 1] == 0x00:
        sc -= 1
    return sc


def _pes_es_range(packet):
    """Return (es_start, es_end, bounded) for ES bytes in this packet.

    ``bounded`` is True when the PES payload is known to end here (nonzero
    PES length, or unbounded PES with trailing TS padding). A trailing NAL
    in an unbounded full packet may continue in the next TS packet.
    """
    base = packet_payload_offset(packet)
    if base is None or base + 8 >= TS_PACKET_SIZE:
        return None
    if packet[base] != 0x00 or packet[base + 1] != 0x00 or packet[base + 2] != 0x01:
        return None
    pes_len = (packet[base + 4] << 8) | packet[base + 5]
    es_start = base + 9 + packet[base + 8]
    if es_start >= TS_PACKET_SIZE:
        return None
    if pes_len == 0:
        es_end = TS_PACKET_SIZE
        while es_end > es_start and packet[es_end - 1] == 0xFF:
            es_end -= 1
        bounded = es_end < TS_PACKET_SIZE
    else:
        pes_end = base + 6 + pes_len
        es_end = min(TS_PACKET_SIZE, pes_end)
        bounded = pes_end <= TS_PACKET_SIZE
    if es_end <= es_start:
        return None
    return es_start, es_end, bounded


def _inspect_avc_hevc_packet(packet, stream_type):
    """One start-code walk: (nal_keyframe, param_sets) for H.264 / HEVC.

    Keyframe rules match the previous dedicated scanners: IDR/IRAP is
    definitive; SPS/VPS counts only until a non-keyframe VCL shows up in the
    same packet; HEVC PPS alone is never a keyframe. Parameter sets are only
    returned when the NAL is complete in this packet.
    """
    wanted = _param_types_for(stream_type)
    if not wanted:
        return False, {}
    es = _pes_es_range(packet)
    if es is None:
        return False, {}
    es_start, es_end, bounded = es
    offsets = []
    i = es_start
    while True:
        found = packet.find(b"\x00\x00\x01", i)
        if found < 0 or found + 3 >= es_end:
            break
        offsets.append(found + 3)
        i = found + 3

    keyframe = None  # None until a decisive NAL appears
    seen_parameter_set = False
    params = {}
    for i, off in enumerate(offsets):
        ntype = _nal_type(packet[off], stream_type)
        if ntype is None:
            continue

        if keyframe is None:
            if stream_type == 0x1B:
                if ntype == 5:
                    keyframe = True
                elif 1 <= ntype <= 4:
                    keyframe = False
                elif ntype == 7:
                    seen_parameter_set = True
            else:  # HEVC
                if 16 <= ntype <= 21:
                    keyframe = True
                elif ntype <= 15:
                    keyframe = False
                elif ntype in (32, 33):
                    seen_parameter_set = True

        if ntype not in wanted:
            continue
        sc = _start_code_begin(packet, off)
        if i + 1 < len(offsets):
            nal_end = _start_code_begin(packet, offsets[i + 1])
        else:
            if not bounded:
                continue
            nal_end = es_end
            if nal_end - sc > _MAX_PARAM_NAL_BYTES:
                continue
        if nal_end <= sc:
            continue
        params[ntype] = bytes(packet[sc:nal_end])

    if keyframe is None:
        keyframe = seen_parameter_set
    return keyframe, params


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
    if video_stream_type in (0x1B, 0x24):
        keyframe, _ = _inspect_avc_hevc_packet(packet, video_stream_type)
        return keyframe
    if video_stream_type in (0x01, 0x02):
        return _mpeg2_starts_keyframe(packet)
    return False


def extract_parameter_sets(packet, stream_type):
    """Map nal_type -> Annex-B NAL bytes (with start code) found in this packet.

    Only complete NALs are returned: ended by the next start code, or a
    trailing parameter-set NAL whose PES payload ends in this packet.
    """
    if stream_type not in (0x1B, 0x24):
        return {}
    _, params = _inspect_avc_hevc_packet(packet, stream_type)
    return params


def packet_has_decoder_init(packet, stream_type):
    """True when this packet already carries the parameter sets needed to start."""
    wanted = _param_types_for(stream_type)
    if not wanted:
        return False
    found = extract_parameter_sets(packet, stream_type)
    return all(t in found for t in wanted)


def build_parameter_set_packets(pid, param_sets, stream_type):
    """Wrap cached parameter-set NALs in one or more TS packets (PES, no PTS).

    The continuity_counter nibble is left as 0; the caller restamps it to
    fit the real per-PID CC sequence before splicing these packets in.
    """
    order = _param_types_for(stream_type)
    payload = bytearray()
    for ntype in order:
        nal = param_sets.get(ntype)
        if not nal:
            return []
        payload.extend(nal)
    if not payload:
        return []

    # PES: start code + stream_id + length + flags (no PTS/DTS) + 0 header bytes.
    pes = bytearray(b"\x00\x00\x01\xe0")
    pes.extend(b"\x00\x00")
    pes.extend(b"\x80\x00\x00")
    pes.extend(payload)
    body_len = len(pes) - 6
    pes[4] = (body_len >> 8) & 0xFF
    pes[5] = body_len & 0xFF

    packets = []
    offset = 0
    while offset < len(pes):
        header = bytearray(4)
        header[0] = TS_SYNC_BYTE
        pusi = offset == 0
        header[1] = ((0x40 if pusi else 0x00) | ((pid >> 8) & 0x1F))
        header[2] = pid & 0xFF
        chunk = pes[offset:offset + (TS_PACKET_SIZE - 4)]
        offset += len(chunk)
        if len(chunk) < TS_PACKET_SIZE - 4:
            # Adaptation-field stuffing to fill the packet.
            stuff = (TS_PACKET_SIZE - 4) - len(chunk)
            header[3] = 0x30  # adaptation + payload, CC filled in by caller
            if stuff == 1:
                af = bytearray([0x00])
            else:
                af = bytearray([stuff - 1, 0x00])
                af.extend(b"\xff" * (stuff - 2))
            packets.append(bytes(header) + bytes(af) + bytes(chunk))
        else:
            header[3] = 0x10  # payload only, CC filled in by caller
            packets.append(bytes(header) + bytes(chunk))
    return packets


class TSSegmenter:
    """
    Stateful packet-copy segmenter. Feed it raw TS bytes (any chunking);
    it returns finished Segment objects as keyframe boundaries are crossed.
    """

    def __init__(self, target_duration=4.0, max_segment_duration=None,
                 startup_keyframe_cuts=4):
        self.target_duration = float(target_duration)
        # Hard ceiling: force a cut before a segment can exceed this, so
        # EXTINF rounded to the nearest integer stays <= TARGETDURATION even
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
        # measured duration on the discontinuity cut instead of substituting the
        # nominal target (RFC 8216 4.3.2.1: EXTINF SHOULD be accurate enough
        # that accumulated durations avoid perceptible error).
        self._seg_first_pts = None
        self._seg_last_pts = None
        self._collecting = False
        self._pending_discontinuity = False
        self._current_discontinuity = False
        # Latest H.264 SPS/PPS or HEVC VPS/SPS/PPS seen in-band. Injected
        # after PAT/PMT when a segment opens on a keyframe that lacks them.
        self._param_sets = {}

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
        self._param_sets = {}
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
                if (
                    video_pid != self._video_pid
                    or stream_type != self._video_stream_type
                ):
                    self._param_sets = {}
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
                self._param_sets = {}
            return None

        if self._video_pid is None and not self._audio_only:
            return None

        if self._audio_only:
            return self._handle_audio_packet(packet, pid)

        finished = None
        if pid == self._video_pid and packet_pusi(packet):
            # One start-code walk for H.264/HEVC: keyframe detection and
            # parameter-set cache share the same NAL scan.
            pts = extract_pts(packet)
            if self._video_stream_type in (0x1B, 0x24):
                rai = packet_random_access(packet)
                nal_keyframe, found_in_packet = _inspect_avc_hevc_packet(
                    packet, self._video_stream_type
                )
                if found_in_packet:
                    self._param_sets.update(found_in_packet)
                keyframe = rai or nal_keyframe
            else:
                found_in_packet = {}
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
                    self._begin_segment(pts, opening_packet=packet, opening_params=found_in_packet)
                    self._current.extend(packet)
                return finished

            if not self._collecting:
                if keyframe:
                    self._begin_segment(pts, opening_packet=packet, opening_params=found_in_packet)
            elif keyframe and pts is not None:
                if self._segment_start_pts is None:
                    # Segment was opened on a keyframe PES that had no PTS
                    # (parameter-set-only AU). No keyframe boundary to use;
                    # measured span if any pictures were timed, else target.
                    finished = self._finish_segment(self._extinf_duration())
                    self._begin_segment(pts, opening_packet=packet, opening_params=found_in_packet)
                else:
                    elapsed = self._elapsed(pts, self._segment_start_pts)
                    # Fast-start ladder: while starter cuts remain, any
                    # keyframe closes the segment (elapsed > 0 skips
                    # same-PTS duplicates); afterwards the normal target
                    # applies.
                    cut_at = 0.0 if self._startup_cuts_remaining > 0 else self.target_duration
                    if elapsed >= cut_at and elapsed > 0:
                        # Closing keyframe is not in this segment's bytes; do
                        # not fold its PTS into the measured span before finish.
                        finished = self._finish_segment(self._extinf_duration(elapsed))
                        self._begin_segment(pts, opening_packet=packet, opening_params=found_in_packet)
                    else:
                        self._note_pts(pts)
            elif pts is not None and self._collecting and self._segment_start_pts is not None:
                # Keyframe drought: force a cut so EXTINF cannot exceed the
                # frozen TARGETDURATION. Mid-GOP cuts are a last resort; a
                # healthy GOP never reaches this ceiling.
                elapsed = self._elapsed(pts, self._segment_start_pts)
                if elapsed >= self.max_segment_duration:
                    finished = self._finish_segment(self._extinf_duration(elapsed))
                    # Mid-GOP: no inject (segment is not independently decodable).
                    self._begin_segment(pts)
                else:
                    self._note_pts(pts)
            elif pts is not None and self._collecting:
                self._note_pts(pts)

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

            if not self._collecting:
                if pts is not None:
                    self._begin_segment(pts)
            elif pts is not None and self._segment_start_pts is not None:
                elapsed = self._elapsed(pts, self._segment_start_pts)
                if elapsed >= self.target_duration and elapsed > 0:
                    # Audio AUs do not have open-GOP overlap; PES-to-PES
                    # elapsed is the accurate EXTINF for the cut boundary.
                    finished = self._finish_segment(elapsed)
                    self._begin_segment(pts)
                else:
                    self._note_pts(pts)

        if self._collecting:
            self._current.extend(packet)
        return finished

    def _note_pts(self, pts):
        """Track presentation-max PTS for packets that remain in this segment."""
        if self._seg_first_pts is None:
            self._seg_first_pts = pts
            self._seg_last_pts = pts
            return
        # Open-GOP leading pictures (PTS slightly before the CRA) must not
        # pull _seg_last_pts backward and corrupt measured EXTINF.
        if self._elapsed(pts, self._seg_first_pts) >= self._elapsed(
            self._seg_last_pts, self._seg_first_pts
        ):
            self._seg_last_pts = pts

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
        """Presentation span of PTS already collected in the open segment, or None.

        Used alone for hard cuts (no next-keyframe anchor), and as one input to
        EXTINF on normal cuts so open-GOP trailing pictures past the next
        keyframe PTS are not clipped (RFC 8216 4.3.2.1).
        """
        if self._seg_first_pts is None or self._seg_last_pts is None:
            return None
        d = self._elapsed(self._seg_last_pts, self._seg_first_pts)
        if d <= 0 or d > 4 * self.target_duration:
            return None
        return d

    def _extinf_duration(self, boundary_elapsed=None):
        """EXTINF for the segment being closed.

        On a keyframe cut, ``boundary_elapsed`` is next_start - this_start.
        Take max(measured, boundary) so closed-GOP includes the last picture's
        duration (PTS marks picture start, so measured alone is ~1 frame short)
        and open-GOP media past the next keyframe PTS is not under-counted.
        Hard cuts omit the boundary and use the measured span only.
        """
        span = self._measured_span()
        if boundary_elapsed is not None and boundary_elapsed > 0:
            boundary = float(boundary_elapsed)
            return max(span, boundary) if span is not None else boundary
        if span is not None:
            return span
        return self.target_duration

    def _param_cache_complete(self):
        wanted = _param_types_for(self._video_stream_type)
        return bool(wanted) and all(t in self._param_sets for t in wanted)

    def _maybe_inject_parameter_sets(self, opening_packet, found_in_opening):
        """Prepend cached parameter sets when the opening keyframe lacks them."""
        if self._video_pid is None or self._video_stream_type not in (0x1B, 0x24):
            return
        # Re-seed here: the caller may have just run flag_discontinuity(),
        # which clears _param_sets after the packet was already scanned.
        if found_in_opening:
            self._param_sets.update(found_in_opening)
        wanted = _param_types_for(self._video_stream_type)
        if wanted and all(t in found_in_opening for t in wanted):
            return
        if not self._param_cache_complete():
            return
        packets = build_parameter_set_packets(
            self._video_pid, self._param_sets, self._video_stream_type
        )
        if not packets:
            return
        first_cc = (packet_continuity_counter(opening_packet) - len(packets)) & 0x0F
        for i, pkt in enumerate(packets):
            buf = bytearray(pkt)
            buf[3] = (buf[3] & 0xF0) | ((first_cc + i) & 0x0F)
            self._current.extend(bytes(buf))

    def _begin_segment(self, pts, opening_packet=None, opening_params=None):
        self._current = bytearray()
        if self._pat_packet:
            self._current.extend(self._pat_packet)
        if self._pmt_packet:
            self._current.extend(self._pmt_packet)
        if opening_packet is not None:
            # Skip inject when this keyframe already carries SPS/PPS (VPS);
            # opening_params is the NAL scan the caller already did for this
            # same packet, reused here to avoid a second walk.
            self._maybe_inject_parameter_sets(opening_packet, opening_params or {})
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
                          disc_sequence=0, start_behind_seconds=None):
    """
    Render an HLS media playlist (RFC 8216, version 3) from a window of
    segment descriptors: [{"seq": int, "dur": float, "disc": bool}, ...].
    Segment URIs are relative so they resolve against the playlist URL.

    ``adv_target`` is the manager's frozen EXT-X-TARGETDURATION; when supplied it
    is emitted verbatim so the value never changes across reloads (RFC 8216
    6.2.1). Without it (legacy descriptor) the per-window ceil is used.

    ``disc_sequence`` is how many EXT-X-DISCONTINUITY tags have already slid out
    of the window. Emitting it keeps DSNs of segments still listed unchanged
    as the window rolls (RFC 8216 6.2.2). An absent tag means zero
    (RFC 8216 4.3.3.3), so it only needs to appear once it is nonzero.

    ``start_behind_seconds`` is the preferred live join offset (same policy as
    new_client_behind_seconds). When set and the window is deep enough, emit
    EXT-X-START with a negative TIME-OFFSET from the live edge.
    """
    if not window:
        return (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            # Ceil the cut target so TARGETDURATION is >= EXTINF rounded to
            # the nearest integer (RFC 8216 4.3.3.1).
            f"#EXT-X-TARGETDURATION:{adv_target if adv_target else int(max(target_duration, 1) + 0.999)}\n"
            "#EXT-X-MEDIA-SEQUENCE:0\n"
        )
    total_duration = sum(entry["dur"] for entry in window)
    # Prefer the manager's frozen TARGETDURATION. RFC 8216 6.2.1 forbids it
    # changing across reloads; a per-render ceil of the window max flaps on
    # GOP jitter. Legacy fallback keeps the ceil.
    advertised_target = adv_target if adv_target else int(max(entry["dur"] for entry in window) + 0.999)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{advertised_target}",
        f"#EXT-X-MEDIA-SEQUENCE:{window[0]['seq']}",
    ]
    if disc_sequence:
        lines.append(f"#EXT-X-DISCONTINUITY-SEQUENCE:{disc_sequence}")
    # Preferred join: N seconds before the end of the last listed segment.
    # Emit only once the window can honor the offset (|TIME-OFFSET| SHOULD NOT
    # exceed playlist duration; RFC 8216 4.3.5.2). Keep the value frozen for
    # the session so reloads stay within allowed live-playlist mutations
    # (RFC 8216 6.2.1). PRECISE=YES: start in the containing segment and skip
    # samples before the offset.
    try:
        start_behind = float(start_behind_seconds) if start_behind_seconds is not None else 0.0
    except (TypeError, ValueError):
        start_behind = 0.0
    if start_behind > 0 and total_duration >= start_behind:
        lines.append(f"#EXT-X-START:TIME-OFFSET=-{start_behind:.3f},PRECISE=YES")
    for entry in window:
        if entry.get("disc"):
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append(f"#EXTINF:{entry['dur']:.3f},")
        lines.append(segment_name.format(seq=entry["seq"]))
    return "\n".join(lines) + "\n"
