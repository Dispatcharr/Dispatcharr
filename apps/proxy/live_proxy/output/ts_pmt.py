"""Fingerprint PAT/PMT layout and report the first packet where it changes."""

from apps.proxy.ts_psi import (
    DESCRIPTOR_ISO_639_LANGUAGE,
    DESCRIPTOR_REGISTRATION,
    TS_PACKET_SIZE,
    PsiSectionAssembler,
    parse_pat,
    parse_pmt_section,
)
from ..psi_scan import locate_psi_packets

_SYNC_BYTE = 0x47
_PAT_PID = 0
_PUSI_BIT = 0x40

# Language can change without the elementary stream changing shape.
_IGNORED_DESCRIPTOR_TAGS = frozenset({
    DESCRIPTOR_ISO_639_LANGUAGE,
})


def _descriptor_signature(descriptors: bytes):
    """Codec-relevant descriptors. A registration descriptor keeps its format identifier. The rest keep the tag."""
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
        if tag == DESCRIPTOR_REGISTRATION:
            signature.append((tag, bytes(body[:4])))
        else:
            signature.append((tag, b""))
    return tuple(sorted(signature))


class PmtLayoutWatcher:
    """The first complete PMT seeds the fingerprint. A later one that differs is a layout change.

    Sections that span packets are reassembled before they count, and a
    partial section never does. The latest PAT is kept so a restarted process
    can be handed it first. ``leading_section`` holds PMT packets from earlier
    input when the section that changed began there.
    """

    def __init__(self, scan_cache=None):
        """``scan_cache`` is the channel's shared scan cache, if any."""
        self._scan_cache = scan_cache
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
        """Undo the last change so a later copy of the new PMT can retry the spawn."""
        if self._fingerprint_before_change is not None:
            self._fingerprint = self._fingerprint_before_change
        self._fingerprint_before_change = None
        self.leading_section = b""

    @property
    def fingerprint(self):
        """Current layout fingerprint, or None if no PMT has been seen yet."""
        return self._fingerprint

    @property
    def fingerprint_before_change(self):
        """Layout this change replaced, or None when no change is in progress."""
        return self._fingerprint_before_change

    @property
    def pat_packet(self):
        """Most recent PAT packet (bytes), or b"" if none has been seen."""
        return self._pat_packet or b""

    def find_layout_change(self, data: bytes, chunk_index=None):
        """Byte offset of the first packet that changes the layout, or None.

        None also covers the first layout being seeded. On a change the stored
        fingerprint is already the new one and scanning stops, so call again
        on the remainder. ``chunk_index`` is set only for an unmodified input
        chunk, so the scan cache can be reused. A remainder passes None.
        """
        if not data:
            return None

        self.leading_section = b""
        # Packets held from an earlier chunk are no longer in `data`.
        self._pmt_sections.retag_origins(None)

        located = self._locate(data, chunk_index)
        if located is None:
            return self._walk_packets(data)

        start = 0
        while True:
            for offset, is_pat in located:
                if offset < start:
                    continue
                packet = data[offset:offset + TS_PACKET_SIZE]
                if is_pat:
                    if self._note_pat_packet(packet):
                        # PMT packets later in `data` may be on the new PID.
                        start = offset + TS_PACKET_SIZE
                        located = self._locate(data, chunk_index)
                        break
                else:
                    change = self._note_pmt_packet(packet, offset)
                    if change is not None:
                        return change
            else:
                return None

    def _locate(self, data, chunk_index):
        """PAT/PMT offsets, or None when ``data`` is not packet-aligned."""
        if self._scan_cache is not None and chunk_index is not None:
            return self._scan_cache.locate(chunk_index, data, self._pmt_pid)
        return locate_psi_packets(data, self._pmt_pid)

    def _note_pat_packet(self, packet):
        """Learn the PMT PID from a PAT packet. True when that PID changed."""
        pmt_pid = parse_pat(packet)
        if pmt_pid is None:
            return False
        changed = pmt_pid != self._pmt_pid
        self._pmt_pid = pmt_pid
        self._pat_packet = bytes(packet)
        return changed

    def _walk_packets(self, data):
        """Per-packet walk used when ``locate_psi_packets`` returns None.

        That is input which is not a whole number of packets starting on a
        sync byte, so the strided scan would land mid-packet.
        """
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
            # Media packets, nearly all of them, are not copied.
            if pid == _PAT_PID and data[offset + 1] & _PUSI_BIT:
                self._note_pat_packet(data[offset:next_offset])
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
            # A rescan would otherwise feed these packets to the assembler again.
            self._pmt_sections = PsiSectionAssembler()
            return here[0] if here else 0
        return None

    def accept_layout_change(self):
        """Drop the saved fingerprint once the replacement has spawned."""
        self._fingerprint_before_change = None

    def _fingerprint_of(self, section):
        streams = parse_pmt_section(section)
        if streams is None:
            return None
        # PMT order. fMP4 names aac_adtstoasc by audio index, which is this position.
        return (
            self._pmt_pid,
            tuple(
                (stream_type, es_pid, _descriptor_signature(descriptors))
                for stream_type, es_pid, descriptors in streams
            ),
        )
