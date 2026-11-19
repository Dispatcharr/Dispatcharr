"""H.264/HEVC/MPEG-2 keyframe and parameter-set helpers for MPEG-TS.

Shared by the HLS segmenter (segment cuts / decoder-init splice) and join
trim (mid-chunk RAP start). Stdlib plus ``ts_psi`` / ``ts_clock`` only.
"""

from apps.proxy.ts_psi import (
    TS_PACKET_SIZE,
    packet_payload_offset,
)
from apps.proxy.live_proxy.ts_clock import packet_random_access

TS_SYNC_BYTE = 0x47

# Parameter-set NAL types needed for an independently decodable TS start.
_H264_PARAM_TYPES = (7, 8)       # SPS, PPS
_HEVC_PARAM_TYPES = (32, 33, 34)  # VPS, SPS, PPS
_MAX_PARAM_NAL_BYTES = 512


def packet_continuity_counter(packet):
    """4-bit continuity_counter."""
    return packet[3] & 0x0F


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


def param_types_for(stream_type):
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


def inspect_avc_hevc_packet(packet, stream_type):
    """One start-code walk: (nal_keyframe, param_sets) for H.264 / HEVC.

    Keyframe rules match the previous dedicated scanners: IDR/IRAP is
    definitive; SPS/VPS counts only until a non-keyframe VCL shows up in the
    same packet; HEVC PPS alone is never a keyframe. Parameter sets are only
    returned when the NAL is complete in this packet.
    """
    wanted = param_types_for(stream_type)
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
        keyframe, _ = inspect_avc_hevc_packet(packet, video_stream_type)
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
    _, params = inspect_avc_hevc_packet(packet, stream_type)
    return params


def packet_has_decoder_init(packet, stream_type):
    """True when this packet already carries the parameter sets needed to start."""
    wanted = param_types_for(stream_type)
    if not wanted:
        return False
    # Same inspect extract_parameter_sets uses; avoid a second stream_type gate.
    _keyframe, found = inspect_avc_hevc_packet(packet, stream_type)
    return all(t in found for t in wanted)


def build_parameter_set_packets(pid, param_sets, stream_type):
    """Wrap cached parameter-set NALs in one or more TS packets (PES, no PTS).

    The continuity_counter nibble is left as 0; the caller restamps it to
    fit the real per-PID CC sequence before splicing these packets in.
    """
    order = param_types_for(stream_type)
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
