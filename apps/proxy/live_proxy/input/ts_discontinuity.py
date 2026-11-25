"""
MPEG-TS discontinuity_indicator helpers (ISO/IEC 13818-1).

The adaptation_field discontinuity_indicator (1 bit) marks that the
discontinuity state is true for the current Transport Stream packet. It
covers two cases called out by the standard:

- continuity_counter discontinuities for that PID
- system time-base (PCR) discontinuities when set on a PCR-bearing packet
  of the PCR_PID

FFmpeg's mpegts muxer ``initial_discontinuity`` flag writes the same bit
(adaptation flags ``0x80``) on the first packet of each PID so concatenated
streams do not fail continuity checks. Demuxers that honor the bit (including
FFmpeg's mpegts demuxer) accept a CC/PCR jump on that packet; demuxers that
ignore it treat the packet as ordinary TS.

This module only sets the indicator on real 188-byte packets. It does not
invent proprietary sentinels.
"""

from ..constants import TS_PACKET_SIZE

# adaptation_field flags bit 7: discontinuity_indicator (ISO 13818-1).
DISCONTINUITY_INDICATOR = 0x80
# Null packets carry no elementary stream; stamping them helps nobody.
NULL_PID = 0x1FFF


def packet_pid(packet):
    """13-bit PID of a TS packet."""
    return ((packet[1] & 0x1F) << 8) | packet[2]


def packet_has_discontinuity_indicator(packet):
    """True when this packet's adaptation field has discontinuity_indicator=1."""
    if not packet or len(packet) < 6 or packet[0] != 0x47:
        return False
    afc = (packet[3] >> 4) & 0x03
    if afc not in (0x02, 0x03):
        return False
    if packet[4] < 1:
        return False
    return bool(packet[5] & DISCONTINUITY_INDICATOR)


def set_discontinuity_indicator(packet):
    """
    Return a copy of ``packet`` with discontinuity_indicator set.

    Matches FFmpeg's ``set_af_flag(pkt, 0x80)`` / ``initial_discontinuity``
    layout when an adaptation field must be introduced:

    - adaptation already present: OR ``0x80`` into the flags byte
    - payload only: insert a 2-byte adaptation field (length=1, flags=0x80)
      and keep the leading payload bytes (trailing 2 bytes dropped), preserving
      the continuity_counter

    Returns the original object unchanged when the input is not a valid
    188-byte TS packet or is a null packet.
    """
    if not packet or len(packet) != TS_PACKET_SIZE or packet[0] != 0x47:
        return packet
    pid = packet_pid(packet)
    if pid == NULL_PID:
        return packet

    afc = (packet[3] >> 4) & 0x03
    if afc in (0x02, 0x03):
        if packet[4] < 1:
            return packet
        if packet[5] & DISCONTINUITY_INDICATOR:
            return packet
        out = bytearray(packet)
        out[5] |= DISCONTINUITY_INDICATOR
        return bytes(out)

    if afc != 0x01:
        # No payload and no adaptation (reserved 00): nothing to stamp.
        return packet

    # Payload only: introduce a 1-byte adaptation field + flags, same as
    # FFmpeg mpegtsenc when initial_discontinuity forces an AF onto the first
    # packet of a PID. Payload shrinks by 2 bytes (trailing bytes dropped).
    out = bytearray(TS_PACKET_SIZE)
    out[0:3] = packet[0:3]
    out[3] = (packet[3] & 0x0F) | 0x30  # adaptation + payload, same CC
    out[4] = 1
    out[5] = DISCONTINUITY_INDICATOR
    payload = packet[4:TS_PACKET_SIZE - 2]
    out[6:6 + len(payload)] = payload
    return bytes(out)


def stamp_first_packet_per_pid(data, already_stamped=None):
    """
    Stamp discontinuity_indicator on the first packet of each PID in ``data``.

    ``data`` must be a multiple of 188 bytes (complete packets only).
    ``already_stamped`` is a set of PIDs stamped earlier in this discontinuity
    generation; it is updated in place.

    Returns ``(possibly_new_bytes, stamped_pids_this_call)``.
    """
    if already_stamped is None:
        already_stamped = set()
    if not data:
        return data, set()
    if len(data) % TS_PACKET_SIZE:
        raise ValueError("stamp_first_packet_per_pid requires packet-aligned data")

    out = None
    stamped_now = set()
    for offset in range(0, len(data), TS_PACKET_SIZE):
        packet = data[offset:offset + TS_PACKET_SIZE]
        if packet[0] != 0x47:
            continue
        pid = packet_pid(packet)
        if pid == NULL_PID or pid in already_stamped:
            continue
        stamped = set_discontinuity_indicator(packet)
        already_stamped.add(pid)
        stamped_now.add(pid)
        if stamped is not packet:
            if out is None:
                out = bytearray(data)
            out[offset:offset + TS_PACKET_SIZE] = stamped
    return (bytes(out) if out is not None else data), stamped_now
