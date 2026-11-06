"""MPEG-TS inspection for DVR remux.

Capture writes HLS segments with FFmpeg's MPEG-TS muxer. That muxer writes the
program map (PMT) once, from the first source's streams, and never updates it.
When the proxy switches stream, or a source changes its own audio mid-stream,
FFmpeg keeps copying the new packets under the old labels: AAC bytes under an
AC-3 label, tracks that vanish, tracks that come back. Reading the segments
back trusts those labels, so audio that is still in the file decodes as
silence. The same changes can leave a track on a stale clock, far from the
video's or crawling a tick at a time, and FFmpeg corrects a clock jump for a
whole input, so such a track drags the video and every other track with it.

This module reads what the audio payloads really are and which tracks have a
clock that cannot be trusted, and can rewrite the PMT so FFmpeg is told the
truth. It only reads segment files. Rewritten bytes exist only in the stream
handed to FFmpeg.
"""
import os
import struct
from collections import namedtuple

from apps.proxy.ts_psi import (
    DESCRIPTOR_AAC,
    DESCRIPTOR_AC3,
    DESCRIPTOR_DTS,
    DESCRIPTOR_EAC3,
    DESCRIPTOR_ISO_639_LANGUAGE,
    DESCRIPTOR_REGISTRATION,
    REGISTRATION_AC3,
    REGISTRATION_DTS1,
    REGISTRATION_DTS2,
    REGISTRATION_DTS3,
    REGISTRATION_EAC3,
    STREAM_TYPE_AAC_ADTS,
    STREAM_TYPE_AAC_LATM,
    STREAM_TYPE_AC3,
    STREAM_TYPE_AVS,
    STREAM_TYPE_BLURAY_DTS,
    STREAM_TYPE_BLURAY_DTS_HD,
    STREAM_TYPE_BLURAY_DTS_HD_MASTER,
    STREAM_TYPE_BLURAY_EAC3,
    STREAM_TYPE_BLURAY_TRUEHD,
    STREAM_TYPE_EAC3,
    STREAM_TYPE_H264,
    STREAM_TYPE_HEVC,
    STREAM_TYPE_MPEG1_AUDIO,
    STREAM_TYPE_MPEG1_VIDEO,
    STREAM_TYPE_MPEG2_AUDIO,
    STREAM_TYPE_MPEG2_VIDEO,
    STREAM_TYPE_MPEG4_VIDEO,
    STREAM_TYPE_PRIVATE_DATA,
    TS_PACKET_SIZE,
    PsiSectionAssembler,
    packet_payload_offset,
    packet_pid,
    parse_pmt_section,
)

_SYNC_BYTE = 0x47

# Bytes read from each end of a segment. A source change inside one segment
# shows up as different audio at the two ends. Multiple of the packet size.
SCAN_WINDOW_BYTES = 2792 * TS_PACKET_SIZE

# Present, but not a codec this module recognizes.
UNKNOWN_CODEC = "?"

Shape = namedtuple("Shape", "codec channels sample_rate")
PmtEntry = namedtuple("PmtEntry", "stream_type pid descriptors")
PmtInfo = namedtuple("PmtInfo", "program pmt_pid pcr_pid version entries")
SegmentScan = namedtuple("SegmentScan", "pmt head tail skewed")

_AAC_RATES = (
    96000, 88200, 64000, 48000, 44100, 32000, 24000,
    22050, 16000, 12000, 11025, 8000, 7350,
)
# ADTS channel_configuration -> channel count. 0 means a PCE and is unknown.
_AAC_CHANNELS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 8}
_AC3_RATES = (48000, 44100, 32000)
_EAC3_HALF_RATES = (24000, 22050, 16000)
_AC3_FULL_CHANNELS = (2, 1, 2, 3, 3, 4, 4, 5)
_MPEG_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}

_VIDEO_TYPES = frozenset({
    STREAM_TYPE_MPEG1_VIDEO,
    STREAM_TYPE_MPEG2_VIDEO,
    STREAM_TYPE_MPEG4_VIDEO,
    STREAM_TYPE_H264,
    STREAM_TYPE_HEVC,
    STREAM_TYPE_AVS,
})
# Includes the Blu-ray audio types. 0x86 in that range is also SCTE-35.
_AUDIO_TYPES = frozenset({
    STREAM_TYPE_MPEG1_AUDIO,
    STREAM_TYPE_MPEG2_AUDIO,
    STREAM_TYPE_AAC_ADTS,
    STREAM_TYPE_AAC_LATM,
    STREAM_TYPE_AC3,
    STREAM_TYPE_BLURAY_DTS,
    STREAM_TYPE_BLURAY_TRUEHD,
    STREAM_TYPE_BLURAY_EAC3,
    STREAM_TYPE_BLURAY_DTS_HD,
    STREAM_TYPE_BLURAY_DTS_HD_MASTER,
    STREAM_TYPE_EAC3,
})
# Private PES carries audio when one of these descriptors says so.
_PRIVATE_AUDIO_DESCRIPTORS = frozenset({
    DESCRIPTOR_AC3,
    DESCRIPTOR_EAC3,
    DESCRIPTOR_DTS,
    DESCRIPTOR_AAC,
})
_REGISTRATION_AUDIO = (
    REGISTRATION_AC3,
    REGISTRATION_EAC3,
    REGISTRATION_DTS1,
    REGISTRATION_DTS2,
    REGISTRATION_DTS3,
)

# What FFmpeg's own MPEG-TS muxer writes per codec, so FFmpeg's demuxer
# recognizes it: codec -> (stream_type, descriptors).
_RELABEL_ENTRIES = {
    "aac": (STREAM_TYPE_AAC_ADTS, b""),
    "ac3": (STREAM_TYPE_AC3, bytes([DESCRIPTOR_REGISTRATION, 4]) + REGISTRATION_AC3),
    "eac3": (STREAM_TYPE_EAC3, bytes([DESCRIPTOR_REGISTRATION, 4]) + REGISTRATION_EAC3),
    "mp2": (STREAM_TYPE_MPEG1_AUDIO, b""),
    "mp3": (STREAM_TYPE_MPEG1_AUDIO, b""),
}


def sniff_audio(payload):
    """Identify an audio frame from the start of a PES payload.

    Returns ``Shape`` (codec, channels, sample_rate) read from the frame
    header, or ``None`` when the bytes are not a recognized audio frame.
    """
    if len(payload) < 8:
        return None
    b0, b1 = payload[0], payload[1]
    if b0 == 0x0B and b1 == 0x77:
        return _sniff_ac3(payload)
    if b0 == 0xFF and (b1 & 0xF6) == 0xF0:
        rate_index = (payload[2] >> 2) & 0x0F
        config = ((payload[2] & 0x01) << 2) | (payload[3] >> 6)
        if rate_index >= len(_AAC_RATES):
            return None
        return Shape("aac", _AAC_CHANNELS.get(config, 0), _AAC_RATES[rate_index])
    if b0 == 0xFF and (b1 & 0xE0) == 0xE0:
        return _sniff_mpeg_audio(payload)
    return None


def _sniff_ac3(payload):
    bsid = payload[5] >> 3
    if bsid > 10:
        # E-AC-3: strmtyp, substreamid, frmsiz, then fscod/acmod/lfeon.
        fscod = payload[4] >> 6
        if fscod == 3:
            half = (payload[4] >> 4) & 0x03
            rate = _EAC3_HALF_RATES[half] if half < 3 else 0
        else:
            rate = _AC3_RATES[fscod]
        channels = _AC3_FULL_CHANNELS[(payload[4] >> 1) & 0x07] + (payload[4] & 0x01)
        return Shape("eac3", channels, rate)
    fscod = payload[4] >> 6
    if fscod == 3:
        return None
    acmod = payload[6] >> 5
    # lfeon follows acmod and up to three optional 2-bit fields.
    skip = 0
    if (acmod & 0x01) and acmod != 1:
        skip += 2
    if acmod & 0x04:
        skip += 2
    if acmod == 2:
        skip += 2
    bits = (payload[6] << 8) | payload[7]
    lfeon = (bits >> (15 - 3 - skip)) & 0x01
    return Shape("ac3", _AC3_FULL_CHANNELS[acmod] + lfeon, _AC3_RATES[fscod])


def _sniff_mpeg_audio(payload):
    version = (payload[1] >> 3) & 0x03
    layer = (payload[1] >> 1) & 0x03
    rate_index = (payload[2] >> 2) & 0x03
    if version == 1 or layer == 0 or rate_index == 3 or layer == 3:
        # Reserved version/layer/rate, or Layer I (not used by DVR sources).
        return None
    codec = "mp2" if layer == 2 else "mp3"
    channels = 1 if (payload[3] >> 6) == 3 else 2
    return Shape(codec, channels, _MPEG_RATES[version][rate_index])


def _parse_descriptors(blob):
    found = []
    pos = 0
    while pos + 2 <= len(blob):
        length = blob[pos + 1]
        found.append((blob[pos], blob[pos + 2:pos + 2 + length]))
        pos += 2 + length
    return found


def entry_kind(entry):
    """``"video"``, ``"audio"``, or ``None`` for data and other streams."""
    if entry.stream_type in _VIDEO_TYPES:
        return "video"
    if entry.stream_type in _AUDIO_TYPES:
        return "audio"
    if entry.stream_type == STREAM_TYPE_PRIVATE_DATA:
        for tag, data in _parse_descriptors(entry.descriptors):
            if tag in _PRIVATE_AUDIO_DESCRIPTORS:
                return "audio"
            if tag == DESCRIPTOR_REGISTRATION and data in _REGISTRATION_AUDIO:
                return "audio"
    return None


def audio_entries(pmt):
    return tuple(e for e in pmt.entries if entry_kind(e) == "audio")


def video_entries(pmt):
    return tuple(e for e in pmt.entries if entry_kind(e) == "video")


def entry_codec(entry):
    """The codec this PMT entry claims, or ``None`` when it does not say.

    ``"mpeg"`` stands for MPEG audio, where the PMT does not tell Layer II
    from Layer III.
    """
    stream_type = entry.stream_type
    if stream_type == STREAM_TYPE_AAC_ADTS:
        return "aac"
    if stream_type == STREAM_TYPE_AAC_LATM:
        return "latm"
    if stream_type == STREAM_TYPE_AC3:
        return "ac3"
    if stream_type == STREAM_TYPE_EAC3:
        return "eac3"
    if stream_type in (STREAM_TYPE_MPEG1_AUDIO, STREAM_TYPE_MPEG2_AUDIO):
        return "mpeg"
    if stream_type == STREAM_TYPE_PRIVATE_DATA:
        for tag, data in _parse_descriptors(entry.descriptors):
            registered = tag == DESCRIPTOR_REGISTRATION
            if tag == DESCRIPTOR_AC3 or (registered and data == REGISTRATION_AC3):
                return "ac3"
            if tag == DESCRIPTOR_EAC3 or (registered and data == REGISTRATION_EAC3):
                return "eac3"
    return None


def label_matches(entry, shape):
    """True when the PMT label for ``entry`` agrees with the sniffed ``shape``.

    A label that does not name a codec cannot be wrong, and neither can a
    payload this module does not recognize.
    """
    claimed = entry_codec(entry)
    if claimed is None or shape is None or shape.codec == UNKNOWN_CODEC:
        return True
    if claimed == "mpeg":
        return shape.codec in ("mp2", "mp3")
    return claimed == shape.codec


def relabeled_entry(entry, shape):
    """``entry`` rewritten to describe ``shape``, keeping its language tag."""
    template = _RELABEL_ENTRIES.get(shape.codec) if shape else None
    if template is None or label_matches(entry, shape):
        return entry
    stream_type, descriptors = template
    for tag, data in _parse_descriptors(entry.descriptors):
        if tag == DESCRIPTOR_ISO_639_LANGUAGE:
            descriptors += bytes([tag, len(data)]) + data
    return PmtEntry(stream_type, entry.pid, descriptors)


def _ts_payload_offset(buf, i):
    """Offset of the payload in the TS packet at ``i``, or ``None`` if it has none."""
    relative = packet_payload_offset(buf[i:i + TS_PACKET_SIZE])
    return None if relative is None else i + relative


def _first_psi_section(buf, pid, table_id):
    """First complete section of ``table_id`` on ``pid``, or ``None``.

    Walks ``buf`` packet by packet. A lost sync byte before the section is
    found means there is no program map. The section may span packets.
    """
    if len(buf) < TS_PACKET_SIZE:
        return None
    assembler = PsiSectionAssembler()
    for offset in range(0, len(buf) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE):
        if buf[offset] != _SYNC_BYTE:
            return None
        packet = buf[offset:offset + TS_PACKET_SIZE]
        if packet_pid(packet) != pid:
            continue
        for section, _carried in assembler.push(packet):
            if section and section[0] == table_id:
                return section
    return None


def _pmt_pid_from_pat(section):
    """PMT PID of the first non-zero program in a PAT section, or ``None``."""
    if len(section) < 16 or section[0] != 0x00:
        return None
    end = 3 + (((section[1] & 0x0F) << 8) | section[2])
    if end > len(section) or end < 16:
        return None
    pos = 8
    while pos + 4 <= end - 4:
        program = (section[pos] << 8) | section[pos + 1]
        if program != 0:
            return ((section[pos + 2] & 0x1F) << 8) | section[pos + 3]
        pos += 4
    return None


def parse_pmt(buf):
    """Program map of the first program in ``buf``, or ``None``.

    A PAT or PMT section that spans TS packets is reassembled. A buffer that
    loses sync before those sections are found has no program map.
    """
    pat = _first_psi_section(buf, 0, 0x00)
    if pat is None:
        return None
    pmt_pid = _pmt_pid_from_pat(pat)
    if pmt_pid is None:
        return None
    section = _first_psi_section(buf, pmt_pid, 0x02)
    if section is None:
        return None
    streams = parse_pmt_section(section)
    if streams is None:
        return None
    return PmtInfo(
        (section[3] << 8) | section[4],
        pmt_pid,
        ((section[8] & 0x1F) << 8) | section[9],
        (section[5] >> 1) & 0x1F,
        tuple(
            PmtEntry(stream_type, pid, descriptors)
            for stream_type, pid, descriptors in streams
        ),
    )


# PES packets needed in a window before their timestamps can be judged, and the
# least one PES must advance the clock (90 kHz ticks, about 4 ms) over the one
# before it. Every audio PES carries at least one frame, so a track that really
# plays advances by a frame or more each time. One step that falls short marks
# a broken clock: it crawls, or stamps the same moment twice.
_SKEW_MIN_PES = 8
_SKEW_MIN_TICKS_PER_PES = 400
# An audio PES is written near the video PES it plays with. A track more than
# this far (2 s) from the video clock is on another clock.
_SKEW_MAX_OFFSET_TICKS = 2 * 90000
_PTS_MODULUS = 1 << 33


def _pes_pts(buf, pos):
    """33-bit PTS from the 5 bytes at ``pos``."""
    return (
        ((buf[pos] >> 1) & 0x07) << 30
        | buf[pos + 1] << 22
        | (buf[pos + 2] >> 1) << 15
        | buf[pos + 3] << 7
        | (buf[pos + 4] >> 1)
    )


def _scan_audio(buf, pids, video_pid=None):
    """Read the audio PES packets of ``pids`` in ``buf``.

    Returns ``(shapes, skewed)``: the shape of each PID's first audio frame
    (``None`` where the PID has no PES), and the PIDs whose clock cannot be
    trusted. After a source change FFmpeg can leave a track on a stale clock:
    far from the video's, or crawling a tick at a time. FFmpeg corrects a clock
    jump for a whole input, so such a track drags everything read with it, and
    copying it keeps the broken timeline. Returns ``None`` when the packets
    lose sync.
    """
    shapes = {pid: None for pid in pids}
    stamps = {pid: [] for pid in pids}
    video_stamp = None
    for i in range(0, len(buf) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE):
        if buf[i] != _SYNC_BYTE:
            return None
        pid = ((buf[i + 1] & 0x1F) << 8) | buf[i + 2]
        is_video = pid == video_pid
        if (pid not in shapes and not is_video) or not buf[i + 1] & 0x40:
            continue
        offset = _ts_payload_offset(buf, i)
        if offset is None or buf[offset:offset + 3] != b"\x00\x00\x01":
            continue
        end = i + TS_PACKET_SIZE
        has_pts = buf[offset + 7] & 0x80 and offset + 14 <= end
        if is_video:
            if video_stamp is None and has_pts:
                video_stamp = _pes_pts(buf, offset + 9)
            continue
        if has_pts:
            stamps[pid].append(_pes_pts(buf, offset + 9))
        if shapes[pid] is None:
            start = offset + 9 + buf[offset + 8]
            if start < end:
                shapes[pid] = sniff_audio(buf[start:end]) or Shape(UNKNOWN_CODEC, 0, 0)
    skewed = set()
    for pid, seen in stamps.items():
        if not seen:
            continue
        if video_stamp is not None:
            gap = (seen[0] - video_stamp) % _PTS_MODULUS
            if min(gap, _PTS_MODULUS - gap) > _SKEW_MAX_OFFSET_TICKS:
                skewed.add(pid)
                continue
        if len(seen) >= _SKEW_MIN_PES and any(
            after - before < _SKEW_MIN_TICKS_PER_PES
            for before, after in zip(seen, seen[1:])
        ):
            skewed.add(pid)
    return shapes, skewed


def scan_segment(path, window=SCAN_WINDOW_BYTES):
    """What a capture segment really carries at its start and at its end.

    Returns ``SegmentScan(pmt, head, tail, skewed)``. ``head`` and ``tail`` map
    each audio PID in the segment's PMT to a ``Shape``, or to ``None`` when no
    audio frame of that PID appears there. ``skewed`` is the set of audio PIDs
    whose clock cannot be trusted at either end. Returns ``None`` when the file
    cannot be read or is not a PAT/PMT-bearing MPEG-TS file.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size <= 2 * window:
                data = handle.read()
                mid = (len(data) // 2 // TS_PACKET_SIZE) * TS_PACKET_SIZE
                head_buf, tail_buf = data[:mid], data[mid:]
                pmt_buf = data
            else:
                head_buf = handle.read(window)
                handle.seek(((size - window) // TS_PACKET_SIZE) * TS_PACKET_SIZE)
                tail_buf = handle.read(window)
                pmt_buf = head_buf
    except OSError:
        return None
    pmt = parse_pmt(pmt_buf)
    if pmt is None:
        return None
    pids = [e.pid for e in audio_entries(pmt)]
    video = video_entries(pmt)
    video_pid = video[0].pid if video else None
    head = _scan_audio(head_buf, pids, video_pid)
    tail = _scan_audio(tail_buf, pids, video_pid)
    if head is None or tail is None:
        return None
    return SegmentScan(pmt, head[0], tail[0], frozenset(head[1] | tail[1]))


def _crc32_mpeg(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def build_pmt_payload(pmt, entries):
    """TS packet payload (184 bytes) carrying a PMT section for ``entries``."""
    pcr_pid = pmt.pcr_pid
    if all(e.pid != pcr_pid for e in entries):
        video = [e.pid for e in entries if entry_kind(e) == "video"]
        pcr_pid = video[0] if video else pcr_pid
    es = bytearray()
    for entry in entries:
        length = len(entry.descriptors)
        es += bytes([
            entry.stream_type,
            0xE0 | (entry.pid >> 8), entry.pid & 0xFF,
            0xF0 | (length >> 8), length & 0xFF,
        ]) + entry.descriptors
    body = (
        struct.pack(">H", pmt.program)
        + bytes([0xC1 | ((pmt.version & 0x1F) << 1), 0, 0])
        + struct.pack(">HH", 0xE000 | pcr_pid, 0xF000)
        + bytes(es)
    )
    length = len(body) + 4
    section = bytes([0x02, 0xB0 | (length >> 8), length & 0xFF]) + body
    section += struct.pack(">I", _crc32_mpeg(section))
    payload = b"\x00" + section
    if len(payload) > TS_PACKET_SIZE - 4:
        raise ValueError("PMT does not fit in one TS packet")
    return payload + b"\xFF" * (TS_PACKET_SIZE - 4 - len(payload))


def _pid_hits(ids, needle):
    """Packet numbers whose two PID bytes in ``ids`` equal ``needle``.

    ``ids`` holds two bytes per packet, so a match that starts on an odd
    offset straddles two packets and is not a PID.
    """
    hit = ids.find(needle)
    while hit != -1:
        if not hit & 1:
            yield hit >> 1
        hit = ids.find(needle, hit + 1)


def _rewrite_pmt_packets(buf, pmt_pid, payload):
    """Rewrite the program map packets in ``buf`` (whole TS packets) in place.

    A packet that starts a PMT section is made payload-only and carries
    ``payload``. Every other packet on the PMT PID, the rest of a longer
    original section, becomes a null packet so it cannot extend the new
    one-packet map. The transport error and priority bits are taken as clear,
    as FFmpeg's muxer writes them.

    Only the two PID bytes of each packet are gathered, with strided slices,
    and searched. That runs at C speed, so the cost does not grow with the
    number of media packets the way a packet-by-packet loop does.
    """
    count = len(buf) // TS_PACKET_SIZE
    end = count * TS_PACKET_SIZE
    ids = bytearray(2 * count)
    ids[0::2] = buf[1:end:TS_PACKET_SIZE]
    ids[1::2] = buf[2:end:TS_PACKET_SIZE]
    for number in _pid_hits(ids, bytes([0x40 | (pmt_pid >> 8), pmt_pid & 0xFF])):
        pos = number * TS_PACKET_SIZE
        if buf[pos] == _SYNC_BYTE:
            # Payload only: the new section starts at byte 4, with any
            # adaptation field gone. The continuity counter is kept.
            buf[pos + 3] = (buf[pos + 3] & 0xCF) | 0x10
            buf[pos + 4:pos + TS_PACKET_SIZE] = payload
    for number in _pid_hits(ids, bytes([pmt_pid >> 8, pmt_pid & 0xFF])):
        pos = number * TS_PACKET_SIZE
        if buf[pos] == _SYNC_BYTE:
            buf[pos + 1] = (buf[pos + 1] & 0xE0) | 0x1F
            buf[pos + 2] = 0xFF


def iter_relabeled(paths, pmt_pid, payload, chunk_packets=5584):
    """Yield the segments' bytes with the program map replaced by ``payload``.

    ``payload`` is the one-packet PMT from ``build_pmt_payload``. Only the
    packets ``_rewrite_pmt_packets`` names change; the rest pass through
    untouched. Each file is read in chunks of ``chunk_packets`` whole packets,
    and each yielded chunk is a fresh buffer the caller may keep.
    """
    chunk_size = chunk_packets * TS_PACKET_SIZE
    for path in paths:
        with open(path, "rb") as handle:
            while True:
                buf = bytearray(chunk_size)
                size = handle.readinto(buf)
                if not size:
                    break
                del buf[size:]
                _rewrite_pmt_packets(buf, pmt_pid, payload)
                yield buf
