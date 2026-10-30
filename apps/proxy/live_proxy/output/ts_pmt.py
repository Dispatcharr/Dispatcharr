"""Lightweight MPEG-TS PAT/PMT layout fingerprinting for output-profile restarts.

Reassembles PMT sections (including ones that span packets, or share a packet)
and reports the byte offset of the first packet that changes the elementary
stream layout, so a long-lived profile FFmpeg can be restarted at that boundary.
"""

from ..constants import TS_PACKET_SIZE
from .hls.segmenter import PsiSectionAssembler, parse_pat, parse_pmt_section

_SYNC_BYTE = 0x47
_PAT_PID = 0
_PUSI_BIT = 0x40

# Descriptor tags that do not describe the codec and may change between
# programs without the elementary stream changing shape.
_IGNORED_DESCRIPTOR_TAGS = frozenset({
    0x0A,  # ISO 639 language
})
_REGISTRATION_DESCRIPTOR_TAG = 0x05


def _descriptor_signature(descriptors: bytes):
    """Sorted (tag, detail) pairs for the codec-relevant descriptors in an ES loop.

    Streams that share a stream_type (private PES, 0x06) are told apart by
    their descriptors, e.g. AC-3 (0x6A) versus E-AC-3 (0x7A). Only the tag is
    kept, except for registration descriptors where the 4-byte format
    identifier is what names the codec.
    """
    signature = []
    offset = 0
    total = len(descriptors)
    while offset + 2 <= total:
        tag = descriptors[offset]
        length = descriptors[offset + 1]
        body = descriptors[offset + 2:offset + 2 + length]
        offset += 2 + length
        if tag in _IGNORED_DESCRIPTOR_TAGS:
            continue
        if tag == _REGISTRATION_DESCRIPTOR_TAG:
            signature.append((tag, bytes(body[:4])))
        else:
            signature.append((tag, b""))
    return tuple(sorted(signature))


class PmtLayoutWatcher:
    """Learn PAT/PMT layout and detect mid-stream fingerprint changes.

    The first complete PMT section seeds the fingerprint silently. A later
    section whose fingerprint (PMT PID plus, per elementary stream, its type,
    PID and codec-relevant descriptors) differs is a layout change. Sections
    that span TS packets are reassembled before they count; a partial section
    never does.

    The most recent PAT packet is kept so a restarted process can be handed the
    PAT first. ``leading_section`` holds PMT packets from earlier input that
    belong in front of the restarted stream when the section began there.
    """

    def __init__(self):
        self._pmt_pid = None
        self._fingerprint = None
        self._fingerprint_before_change = None
        self._pat_packet = None
        self._pmt_sections = PsiSectionAssembler()
        self.leading_section = b""

    def reset(self):
        """Clear learned state (e.g. after an input discontinuity restart)."""
        self._pmt_pid = None
        self._fingerprint = None
        self._fingerprint_before_change = None
        self._pat_packet = None
        self._pmt_sections = PsiSectionAssembler()
        self.leading_section = b""

    def revert_layout_change(self):
        """Undo the fingerprint update from the most recent change detection.

        Used when a process replacement cannot be spawned: the current process
        keeps running, and a later copy of the new PMT should try again.
        """
        if self._fingerprint_before_change is not None:
            self._fingerprint = self._fingerprint_before_change
        self._fingerprint_before_change = None
        self.leading_section = b""

    @property
    def fingerprint(self):
        """Current layout fingerprint, or None if no PMT has been seen yet."""
        return self._fingerprint

    @property
    def pat_packet(self):
        """Most recent PAT packet (bytes), or b"" if none has been seen."""
        return self._pat_packet or b""

    def find_layout_change(self, data: bytes):
        """Return the byte offset of the first packet that changes PMT layout.

        Returns None when there is no change, including when the first layout
        is being seeded. On a change, updates the stored fingerprint to the
        new layout so the caller can resume without re-seeding; scanning stops
        at the change, so call again on the remainder to find further changes.
        """
        if not data:
            return None

        self.leading_section = b""
        # Packets held from an earlier chunk are no longer in `data`.
        self._pmt_sections.retag_origins(None)

        offset = 0
        length = len(data)
        while offset + TS_PACKET_SIZE <= length:
            if data[offset] != _SYNC_BYTE:
                nxt = data.find(_SYNC_BYTE, offset + 1)
                if nxt < 0:
                    return None
                offset = nxt
                continue

            # A sync byte inside a payload is not a packet boundary: the next
            # packet must start with one too (the last packet has no successor).
            next_offset = offset + TS_PACKET_SIZE
            if next_offset < length and data[next_offset] != _SYNC_BYTE:
                offset += 1
                continue

            pid = ((data[offset + 1] & 0x1F) << 8) | data[offset + 2]
            # Only PAT and PMT packets are sliced out; media packets (nearly
            # all of them) cost no allocation.
            if pid == _PAT_PID and data[offset + 1] & _PUSI_BIT:
                packet = data[offset:next_offset]
                pmt_pid = parse_pat(packet)
                if pmt_pid is not None:
                    self._pmt_pid = pmt_pid
                    self._pat_packet = bytes(packet)
            elif self._pmt_pid is not None and pid == self._pmt_pid:
                change = self._note_pmt_packet(data[offset:next_offset], offset)
                if change is not None:
                    return change

            offset = next_offset

        return None

    def _note_pmt_packet(self, packet, offset):
        """Learn from one PMT packet. Return the restart offset, or None."""
        for section, packets in self._pmt_sections.push(packet, origin=offset):
            fingerprint = self._fingerprint_of(section)
            if fingerprint is None:
                continue
            if self._fingerprint is None:
                self._fingerprint = fingerprint
                continue
            if fingerprint == self._fingerprint:
                continue
            self._fingerprint_before_change = self._fingerprint
            self._fingerprint = fingerprint
            prior = b"".join(pkt for pkt, origin in packets if origin is None)
            here = [origin for _pkt, origin in packets if origin is not None]
            self.leading_section = prior
            # Rescan rebuilds the section. Keeping it would feed the same
            # packets to the assembler twice.
            self._pmt_sections = PsiSectionAssembler()
            return here[0] if here else 0
        return None

    def accept_layout_change(self):
        """Keep the new fingerprint after a successful process replacement."""
        self._fingerprint_before_change = None

    def _fingerprint_of(self, section):
        streams = parse_pmt_section(section)
        if streams is None:
            return None
        return (
            self._pmt_pid,
            tuple(sorted(
                (stream_type, es_pid, _descriptor_signature(descriptors))
                for stream_type, es_pid, descriptors in streams
            )),
        )
