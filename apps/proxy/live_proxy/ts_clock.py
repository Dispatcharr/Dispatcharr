"""MPEG-TS media clock helpers (PES PTS and PCR) for ingest timing.

Shared by the HLS segmenter and the ingest lag tracker. Prefer PES PTS; fall
back to PCR when a batch has no PTS-bearing packet.
"""

from apps.proxy.ts_psi import TS_PACKET_SIZE, packet_payload_offset, packet_pid

PTS_CLOCK = 90000.0
# 33-bit PTS wraps every ~26.5 hours.
PTS_WRAP = 1 << 33
PTS_WRAP_SECONDS = PTS_WRAP / PTS_CLOCK

CLOCK_PTS = "pts"
CLOCK_PCR = "pcr"
# Newest-clock scan from the end of a socket batch (~8KB reads today). Cap
# so a larger batch cannot force a full walk; a typical GOP still fits.
MAX_CLOCK_SCAN_PACKETS = 64


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


def extract_pcr(packet):
    """PCR base in seconds from the adaptation field, or None."""
    afc = (packet[3] >> 4) & 0x03
    if afc not in (0x02, 0x03) or packet[4] < 7:
        return None
    if not (packet[5] & 0x10):
        return None
    b = packet
    base = (b[6] << 25) | (b[7] << 17) | (b[8] << 9) | (b[9] << 1) | (b[10] >> 7)
    return base / PTS_CLOCK


def packet_random_access(packet):
    """True when the adaptation-field random_access_indicator is set."""
    afc = (packet[3] >> 4) & 0x03
    if afc in (0x02, 0x03) and packet[4] > 0:
        return bool(packet[5] & 0x40)
    return False


def wrap_delta_seconds(newer, older):
    """Signed media-clock delta that tolerates a single 33-bit wrap."""
    delta = newer - older
    if delta > PTS_WRAP_SECONDS / 2:
        delta -= PTS_WRAP_SECONDS
    elif delta < -PTS_WRAP_SECONDS / 2:
        delta += PTS_WRAP_SECONDS
    return delta


def advance_unwrapped_media(raw, last_raw, last_unwrapped):
    """Advance a continuous media timeline across a 33-bit PTS/PCR wrap.

    ``raw`` is the packet clock in ``[0, PTS_WRAP_SECONDS)``. Returns
    ``(raw, unwrapped)`` where ``unwrapped`` continues forward from
    ``last_unwrapped`` (or equals ``raw`` at the start of an era).
    """
    raw = float(raw)
    if last_raw is None or last_unwrapped is None:
        return raw, raw
    return raw, float(last_unwrapped) + wrap_delta_seconds(raw, float(last_raw))


def align_media_to_reference(sample, reference):
    """Shift ``sample`` by whole wraps so it sits near ``reference``.

    Packet PTS/PCR values stay in ``[0, PTS_WRAP_SECONDS)`` while join scores
    may be unwrapped past a wrap. Use the aligned value for at-or-before
    comparisons against a monotonic target.
    """
    if sample is None or reference is None:
        return sample
    aligned = float(sample)
    reference = float(reference)
    half = PTS_WRAP_SECONDS / 2
    while aligned < reference - half:
        aligned += PTS_WRAP_SECONDS
    while aligned > reference + half:
        aligned -= PTS_WRAP_SECONDS
    return aligned


def sample_media_clock(data):
    """Newest PTS (else PCR) in ``data``, walking packets backward.

    Returns ``(media_seconds, clock_kind, pid)`` or ``(None, None, None)``.
    Only the last ``MAX_CLOCK_SCAN_PACKETS`` packets are searched. Header
    bytes are checked in place; the 188-byte slice is built only for packets
    that can hold a clock.
    """
    if not data:
        return None, None, None
    n = len(data) // TS_PACKET_SIZE
    start = max(0, n - MAX_CLOCK_SCAN_PACKETS)
    for i in range(n - 1, start - 1, -1):
        off = i * TS_PACKET_SIZE
        if data[off] != 0x47:
            continue
        # PUSI in byte 1 bit 6. Non-PUSI packets only matter for PCR.
        if not (data[off + 1] & 0x40):
            afc = (data[off + 3] >> 4) & 0x03
            if afc not in (0x02, 0x03):
                continue
            packet = data[off : off + TS_PACKET_SIZE]
            pcr = extract_pcr(packet)
            if pcr is not None:
                return pcr, CLOCK_PCR, packet_pid(packet)
            continue
        packet = data[off : off + TS_PACKET_SIZE]
        pts = extract_pts(packet)
        if pts is not None:
            return pts, CLOCK_PTS, packet_pid(packet)
        pcr = extract_pcr(packet)
        if pcr is not None:
            return pcr, CLOCK_PCR, packet_pid(packet)
    return None, None, None


def sample_media_clock_for_relock(data, former_pid=None):
    """Choose a clock PID after a PTS jump when the old PID is absent.

    Walks the same tail window as ``sample_media_clock``, but considers every
    PTS in that window. When more than one PID has PTS, prefer the lowest PID
    (common IPTV layout: video near 0x100, audio above it). Falls back to
    ``sample_media_clock`` when no PTS is present.
    """
    if not data:
        return None, None, None
    n = len(data) // TS_PACKET_SIZE
    start = max(0, n - MAX_CLOCK_SCAN_PACKETS)
    newest_pts_by_pid = {}
    for i in range(n - 1, start - 1, -1):
        off = i * TS_PACKET_SIZE
        if data[off] != 0x47 or not (data[off + 1] & 0x40):
            continue
        packet = data[off : off + TS_PACKET_SIZE]
        pts = extract_pts(packet)
        if pts is None:
            continue
        pid = packet_pid(packet)
        if pid not in newest_pts_by_pid:
            newest_pts_by_pid[pid] = pts
    if not newest_pts_by_pid:
        return sample_media_clock(data)
    if former_pid is not None and former_pid in newest_pts_by_pid:
        return newest_pts_by_pid[former_pid], CLOCK_PTS, former_pid
    if len(newest_pts_by_pid) == 1:
        pid = next(iter(newest_pts_by_pid))
    else:
        pid = min(newest_pts_by_pid.keys())
    return newest_pts_by_pid[pid], CLOCK_PTS, pid


def last_clock_on_pid_with_offset(data, pid, clock_kind):
    """Newest ``clock_kind`` clock on ``pid`` and its byte offset, or ``(None, None)``.

    Only the last ``MAX_CLOCK_SCAN_PACKETS`` packets are searched. Sync, PID,
    and PUSI are read from byte offsets so non-matching packets are not sliced.
    The offset is where the clock packet starts in ``data``; ingest passes it
    to the chunk buffer so the sample can be placed inside the Redis chunk.
    """
    if not data or pid is None or clock_kind is None:
        return None, None
    n = len(data) // TS_PACKET_SIZE
    start = max(0, n - MAX_CLOCK_SCAN_PACKETS)
    for i in range(n - 1, start - 1, -1):
        off = i * TS_PACKET_SIZE
        if data[off] != 0x47:
            continue
        if (((data[off + 1] & 0x1F) << 8) | data[off + 2]) != pid:
            continue
        if clock_kind == CLOCK_PTS:
            if not (data[off + 1] & 0x40):
                continue
            pts = extract_pts(data[off : off + TS_PACKET_SIZE])
            if pts is not None:
                return float(pts), off
        elif clock_kind == CLOCK_PCR:
            afc = (data[off + 3] >> 4) & 0x03
            if afc not in (0x02, 0x03):
                continue
            pcr = extract_pcr(data[off : off + TS_PACKET_SIZE])
            if pcr is not None:
                return float(pcr), off
    return None, None
