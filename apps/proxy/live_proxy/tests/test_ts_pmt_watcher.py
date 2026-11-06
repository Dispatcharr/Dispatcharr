"""Unit tests for PmtLayoutWatcher (stdlib only, no Django).

    python3 -m unittest apps.proxy.live_proxy.tests.test_ts_pmt_watcher
"""

import unittest

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.output.ts_pmt import PmtLayoutWatcher

VIDEO_PID = 256
AUDIO_PID = 257
PMT_PID = 4096
H264 = 0x1B
AAC = 0x0F
AC3 = 0x81
PRIVATE_PES = 0x06

# DVB-style private-PES audio is told apart only by its descriptors.
AC3_DESCRIPTOR = bytes([0x6A, 0x01, 0x00])
EAC3_DESCRIPTOR = bytes([0x7A, 0x01, 0x00])
LANG_ENG = bytes([0x0A, 0x04]) + b"eng\x00"
LANG_SPA = bytes([0x0A, 0x04]) + b"spa\x00"


def make_packet(pid, payload, pusi=False):
    header = bytearray(4)
    header[0] = 0x47
    header[1] = ((0x40 if pusi else 0x00) | (pid >> 8)) & 0xFF
    header[2] = pid & 0xFF
    header[3] = 0x10
    packet = bytes(header) + bytes(payload)
    packet += b"\xff" * (TS_PACKET_SIZE - len(packet))
    assert len(packet) == TS_PACKET_SIZE
    return packet


def make_pat(pmt_pid=PMT_PID):
    payload = bytearray([0x00])
    payload += bytes([0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00])
    payload += bytes([0x00, 0x01, 0xE0 | (pmt_pid >> 8), pmt_pid & 0xFF])
    payload += bytes(4)
    return make_packet(0, payload, pusi=True)


def make_pmt(streams, pmt_pid=PMT_PID, pcr_pid=VIDEO_PID, pusi=True):
    """streams: list of (stream_type, es_pid) or (stream_type, es_pid, descriptors)."""
    payload = bytearray([0x00])
    es_loop = bytearray()
    for entry in streams:
        stream_type, es_pid = entry[0], entry[1]
        descriptors = entry[2] if len(entry) > 2 else b""
        es_loop += bytes([
            stream_type,
            0xE0 | (es_pid >> 8),
            es_pid & 0xFF,
            0xF0 | (len(descriptors) >> 8),
            len(descriptors) & 0xFF,
        ])
        es_loop += descriptors
    section_length = 9 + len(es_loop) + 4
    payload += bytes([0x02, 0xB0 | (section_length >> 8), section_length & 0xFF])
    payload += bytes([0x00, 0x01, 0xC1, 0x00, 0x00])
    payload += bytes([0xE0 | (pcr_pid >> 8), pcr_pid & 0xFF, 0xF0, 0x00])
    payload += es_loop
    payload += bytes(4)
    return make_packet(pmt_pid, payload, pusi=pusi)


def make_filler(pid=VIDEO_PID):
    return make_packet(pid, b"\x00" * 20)


def seeded(streams):
    """A watcher that has already learned the given layout."""
    watcher = PmtLayoutWatcher()
    assert watcher.find_layout_change(make_pat() + make_pmt(streams)) is None
    return watcher


class PmtLayoutWatcherTests(unittest.TestCase):
    def test_seeds_silently_then_ignores_same_layout(self):
        watcher = PmtLayoutWatcher()
        chunk = make_pat() + make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)]) + make_filler()
        self.assertIsNone(watcher.fingerprint)
        self.assertIsNone(watcher.find_layout_change(chunk))
        self.assertIsNotNone(watcher.fingerprint)
        # Same layout again is not a change.
        self.assertIsNone(watcher.find_layout_change(chunk))

    def test_detects_audio_codec_change_mid_chunk(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        before = watcher.fingerprint

        new_pmt = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)])
        chunk = make_filler() + new_pmt + make_filler()

        change_at = watcher.find_layout_change(chunk)
        self.assertEqual(change_at, TS_PACKET_SIZE)  # after one filler packet
        self.assertEqual(chunk[change_at:change_at + TS_PACKET_SIZE], new_pmt)
        self.assertNotEqual(watcher.fingerprint, before)
        # Feeding the remainder again does not re-trigger.
        self.assertIsNone(watcher.find_layout_change(chunk[change_at:]))

    def test_change_at_offset_zero(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        new_pmt = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)])
        self.assertEqual(watcher.find_layout_change(new_pmt), 0)

    def test_scanning_stops_at_the_first_change_so_later_ones_are_found_on_the_remainder(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        ac3 = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)])
        back_to_aac = make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        data = make_filler() + ac3 + make_filler() + back_to_aac + make_filler()

        first = watcher.find_layout_change(data)
        self.assertEqual(first, TS_PACKET_SIZE)
        rest = data[first:]
        second = watcher.find_layout_change(rest)
        self.assertEqual(rest[second:second + TS_PACKET_SIZE], back_to_aac)
        self.assertIsNone(watcher.find_layout_change(rest[second:]))

    def test_reset_allows_reseed_without_change(self):
        watcher = PmtLayoutWatcher()
        aac = make_pat() + make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        ac3 = make_pat() + make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)])
        self.assertIsNone(watcher.find_layout_change(aac))
        self.assertIsNotNone(watcher.find_layout_change(ac3))

        watcher.reset()
        self.assertIsNone(watcher.fingerprint)
        # After reset, AC3 seeds silently (e.g. post-discontinuity restart).
        self.assertIsNone(watcher.find_layout_change(ac3))
        self.assertIsNotNone(watcher.fingerprint)

    def test_revert_layout_change_allows_the_same_pmt_to_trigger_again(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        before = watcher.fingerprint
        new_pmt = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)])
        self.assertEqual(watcher.find_layout_change(new_pmt), 0)
        self.assertNotEqual(watcher.fingerprint, before)

        watcher.revert_layout_change()
        self.assertEqual(watcher.fingerprint, before)
        self.assertEqual(watcher.find_layout_change(new_pmt), 0)

        watcher.accept_layout_change()
        self.assertIsNone(watcher.find_layout_change(new_pmt))

    def test_pat_packet_is_cached_and_cleared_by_reset(self):
        watcher = PmtLayoutWatcher()
        self.assertEqual(watcher.pat_packet, b"")
        pat = make_pat()
        watcher.find_layout_change(pat + make_pmt([(H264, VIDEO_PID)]))
        self.assertEqual(watcher.pat_packet, pat)
        watcher.reset()
        self.assertEqual(watcher.pat_packet, b"")

    def test_codec_change_within_one_stream_type_is_detected_via_descriptors(self):
        """AC-3 to E-AC-3 in DVB private PES keeps stream_type 0x06 and the PID."""
        watcher = seeded([(H264, VIDEO_PID), (PRIVATE_PES, AUDIO_PID, AC3_DESCRIPTOR)])
        new_pmt = make_pmt([(H264, VIDEO_PID), (PRIVATE_PES, AUDIO_PID, EAC3_DESCRIPTOR)])
        self.assertEqual(watcher.find_layout_change(new_pmt), 0)

    def test_language_descriptor_change_is_not_a_layout_change(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID, LANG_ENG)])
        same_codec = make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID, LANG_SPA)])
        self.assertIsNone(watcher.find_layout_change(same_codec))

    def test_registration_descriptor_format_identifier_is_part_of_the_layout(self):
        opus = bytes([0x05, 0x04]) + b"Opus"
        ac3 = bytes([0x05, 0x04]) + b"AC-3"
        watcher = seeded([(PRIVATE_PES, AUDIO_PID, opus)])
        self.assertEqual(
            watcher.find_layout_change(make_pmt([(PRIVATE_PES, AUDIO_PID, ac3)])), 0
        )

    def test_added_elementary_stream_is_a_layout_change(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        extra = make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID), (AC3, 258)])
        self.assertEqual(watcher.find_layout_change(extra), 0)

    def test_pmt_pid_change_via_pat_is_a_layout_change(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        moved = (
            make_pat(pmt_pid=4200)
            + make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)], pmt_pid=4200)
        )
        self.assertEqual(watcher.find_layout_change(moved), TS_PACKET_SIZE)

    def test_continuation_packets_on_the_pmt_pid_are_ignored(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        # Looks like a different PMT but does not start a section.
        continuation = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)], pusi=False)
        self.assertIsNone(watcher.find_layout_change(continuation))

    def test_multi_packet_pmt_is_not_authoritative(self):
        watcher = seeded([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        packet = bytearray(make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)]))
        section = 4 + 1 + packet[4]
        claimed = TS_PACKET_SIZE  # section_length that spills past this packet
        packet[section + 1] = 0xB0 | ((claimed >> 8) & 0x0F)
        packet[section + 2] = claimed & 0xFF
        self.assertIsNone(watcher.find_layout_change(bytes(packet)))

    def test_resyncs_past_leading_garbage(self):
        watcher = PmtLayoutWatcher()
        seed = b"\x00\x01" + make_pat() + make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        self.assertIsNone(watcher.find_layout_change(seed))
        self.assertIsNotNone(watcher.fingerprint)

        new_pmt = make_pmt([(H264, VIDEO_PID), (AC3, AUDIO_PID)])
        shifted = b"\x00\x01" + make_filler() + new_pmt
        self.assertEqual(watcher.find_layout_change(shifted), 2 + TS_PACKET_SIZE)

    def test_empty_and_short_input(self):
        watcher = PmtLayoutWatcher()
        self.assertIsNone(watcher.find_layout_change(b""))
        self.assertIsNone(watcher.find_layout_change(b"\x47" * 10))


def pmt_section(streams):
    """A PMT section (starting at table_id) for the given (type, pid) list."""
    es_loop = bytearray()
    for stream_type, es_pid in streams:
        es_loop += bytes([
            stream_type,
            0xE0 | (es_pid >> 8),
            es_pid & 0xFF,
            0xF0,
            0x00,
        ])
    section_length = 9 + len(es_loop) + 4
    section = bytearray([0x02, 0xB0 | (section_length >> 8), section_length & 0xFF])
    section += bytes([0x00, 0x01, 0xC1, 0x00, 0x00])
    section += bytes([0xE1, 0x00, 0xF0, 0x00])  # PCR pid 0x100, no program info
    section += es_loop
    section += bytes(4)
    return bytes(section)


def split_pmt(streams):
    """TS packets carrying a PMT section too long for one packet."""
    section = pmt_section(streams)
    assert len(section) > 183
    packets = [make_packet(PMT_PID, bytes([0x00]) + section[:183], pusi=True)]
    rest = section[183:]
    while rest:
        packets.append(make_packet(PMT_PID, rest[:184], pusi=False))
        rest = rest[184:]
    return packets


def wide_streams(audio_type):
    """Enough elementary streams that the PMT section spans two packets."""
    streams = [(H264, VIDEO_PID), (audio_type, AUDIO_PID)]
    streams += [(AAC, 0x200 + i) for i in range(32)]
    return streams


class MultiPacketPmtTests(unittest.TestCase):
    def test_section_split_across_packets_is_one_layout(self):
        watcher = PmtLayoutWatcher()
        packets = split_pmt(wide_streams(AAC))
        self.assertGreater(len(packets), 1)
        # The first packet alone is not a program.
        self.assertIsNone(watcher.find_layout_change(make_pat() + packets[0]))
        self.assertIsNone(watcher.fingerprint)
        self.assertIsNone(watcher.find_layout_change(b"".join(packets[1:])))
        self.assertIsNotNone(watcher.fingerprint)

    def test_codec_change_in_a_split_section_restarts_at_its_first_packet(self):
        watcher = PmtLayoutWatcher()
        self.assertIsNone(
            watcher.find_layout_change(make_pat() + b"".join(split_pmt(wide_streams(AAC))))
        )
        changed = split_pmt(wide_streams(AC3))
        data = make_filler() + b"".join(changed)
        change_at = watcher.find_layout_change(data)
        self.assertEqual(change_at, TS_PACKET_SIZE)
        self.assertEqual(watcher.leading_section, b"")
        self.assertTrue(data[change_at:].startswith(changed[0]))

    def test_section_split_across_chunks_is_prepended_on_restart(self):
        watcher = PmtLayoutWatcher()
        self.assertIsNone(
            watcher.find_layout_change(make_pat() + b"".join(split_pmt(wide_streams(AAC))))
        )
        first, second = split_pmt(wide_streams(AC3))[:2]
        self.assertIsNone(watcher.find_layout_change(first))
        rest = second + make_filler()
        change_at = watcher.find_layout_change(rest)
        self.assertEqual(change_at, 0)
        self.assertEqual(watcher.leading_section, first)
        handed_to_new_process = watcher.pat_packet + watcher.leading_section + rest[change_at:]
        self.assertIn(first, handed_to_new_process)
        self.assertLess(
            handed_to_new_process.index(first),
            handed_to_new_process.index(second),
        )

    def test_two_sections_in_one_packet_keep_the_later_layout(self):
        watcher = PmtLayoutWatcher()
        self.assertIsNone(
            watcher.find_layout_change(
                make_pat() + make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
            )
        )
        packet = make_packet(
            PMT_PID,
            bytes([0x00])
            + pmt_section([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
            + pmt_section([(H264, VIDEO_PID), (AC3, AUDIO_PID)]),
            pusi=True,
        )
        self.assertEqual(watcher.find_layout_change(packet), 0)
        stream_types = {stream_type for stream_type, _pid, _desc in watcher.fingerprint[1]}
        self.assertIn(AC3, stream_types)
        self.assertNotIn(AAC, stream_types)
