"""Shared MPEG-TS Program Specific Information (PSI) helpers.

PAT, PMT, and PSI section reassembly as defined in ISO/IEC 13818-1. Used by
the HLS segmenter and the output-profile PMT layout watcher. Stdlib only
(plus the live_proxy TS packet size constant), so it stays unit-testable
without Django or Redis.
"""

from .constants import TS_PACKET_SIZE

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


def parse_pmt_section(section):
    """Return [(stream_type, es_pid, descriptors), ...] from a reassembled PMT section.

    ``section`` starts at table_id. ``descriptors`` is that stream's raw ES_info
    loop. Returns None when the section is truncated or internally inconsistent,
    so a partial ES loop is never treated as the whole program.
    """
    if len(section) < 12 or section[0] != 0x02:  # table_id must be PMT
        return None
    # section_length: bytes after the length field, including CRC.
    section_length = ((section[1] & 0x0F) << 8) | section[2]
    end = 3 + section_length
    if section_length < 13 or end > len(section):
        return None
    program_info_length = ((section[10] & 0x0F) << 8) | section[11]
    offset = 12 + program_info_length
    # ES loop ends before the 4-byte CRC.
    section_end = end - 4
    if offset > section_end:
        return None

    streams = []
    while offset + 4 < section_end:
        stream_type = section[offset]
        es_pid = ((section[offset + 1] & 0x1F) << 8) | section[offset + 2]
        es_info_length = ((section[offset + 3] & 0x0F) << 8) | section[offset + 4]
        entry_end = offset + 5 + es_info_length
        if entry_end > section_end:
            # Truncated descriptor inside an otherwise sized section: refuse.
            return None
        streams.append((stream_type, es_pid, bytes(section[offset + 5:entry_end])))
        offset = entry_end
    return streams


class PsiSectionAssembler:
    """Reassemble one PID's PSI sections across TS packets.

    A PMT section is capped at 1024 bytes, so a program with many audio,
    subtitle, or CA descriptors spans multiple 188-byte packets. The first
    packet carries a pointer_field and the section start; the rest continue
    the payload. ``push`` returns each section only once it is complete, along
    with the TS packets that carried it, so callers never parse a partial ES loop.
    """

    def __init__(self):
        self._reset()

    def _reset(self):
        self._active = False
        self._buf = bytearray()
        self._packets = []

    def retag_origins(self, origin):
        """Mark packets already held as not belonging to the buffer about to be scanned."""
        self._packets = [(packet, origin) for packet, _ in self._packets]

    def push(self, packet, origin=None):
        """Feed one TS packet. Return [(section, [(packet, origin), ...]), ...]."""
        base = packet_payload_offset(packet)
        if base is None:
            return []
        payload = packet[base:]
        if not payload:
            return []
        done = []
        raw = bytes(packet)
        if packet_pusi(packet):
            pointer = payload[0]
            if pointer > len(payload) - 1:
                self._reset()
                return []
            if self._active and pointer:
                # pointer_field is the tail of the previous section only.
                self._buf.extend(payload[1:1 + pointer])
                self._packets.append((raw, origin))
                done.extend(self._drain_complete(one=True))
            # One payload may hold several sections back to back. Stuffing
            # (0xFF) ends the packet; anything else is the next section.
            rest = payload[1 + pointer:]
            self._active = True
            self._buf = bytearray(rest)
            self._packets = [(raw, origin)]
            done.extend(self._drain_complete())
        elif self._active:
            self._buf.extend(payload)
            self._packets.append((raw, origin))
            done.extend(self._drain_complete())
        return done

    def _drain_complete(self, one=False):
        """Yield every finished section still in the buffer.

        An unfinished tail stays buffered. ``one`` stops after a single
        section, used for the pointer_field tail of the previous section.
        """
        done = []
        while True:
            if len(self._buf) < 3 or self._buf[0] == 0xFF:
                if self._buf[:1] == b"\xff":
                    self._buf.clear()
                break
            # section_length is 12 bits; a PSI section is at most 1024 bytes.
            need = 3 + (((self._buf[1] & 0x0F) << 8) | self._buf[2])
            if need < 16 or need > 1024:
                self._reset()
                break
            if len(self._buf) < need:
                break
            section = bytes(self._buf[:need])
            packets = list(self._packets)
            del self._buf[:need]
            done.append((section, packets))
            if self._buf and self._packets:
                # The next section starts in the packet that finished this one.
                self._packets = [self._packets[-1]]
            if one:
                break
        if not self._buf:
            self._active = False
            self._packets = []
        return done


def parse_pmt_streams(packet):
    """Return [(stream_type, es_pid), ...] from a PMT packet, or None if unparseable.

    Returns None unless the whole section is in this one packet. A PMT that
    spans packets has to be reassembled with PsiSectionAssembler, because the
    ES loop in the first packet alone is not the program.
    """
    done = PsiSectionAssembler().push(packet)
    if len(done) != 1:
        return None
    streams = parse_pmt_section(done[0][0])
    if streams is None:
        return None
    return [(stream_type, es_pid) for stream_type, es_pid, _ in streams]


def parse_pmt(packet):
    """Return (video_pid, video_stream_type) from a PMT packet, or (None, None)."""
    streams = parse_pmt_streams(packet)
    if not streams:
        return None, None
    for stream_type, es_pid in streams:
        if stream_type in VIDEO_STREAM_TYPES:
            return es_pid, stream_type
    return None, None
