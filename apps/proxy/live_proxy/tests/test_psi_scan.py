"""Tests for PAT/PMT location and the scan cache shared between outputs.

    python3 -m unittest apps.proxy.live_proxy.tests.test_psi_scan
"""

import random
import unittest
from unittest.mock import patch

from apps.proxy.live_proxy import psi_scan
from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.output import ts_pmt
from apps.proxy.live_proxy.output.ts_feed import feed_chunk_with_layout_watch
from apps.proxy.live_proxy.output.ts_pmt import PmtLayoutWatcher
from apps.proxy.live_proxy.psi_scan import PsiScanCache, locate_psi_packets
from apps.proxy.live_proxy.tests.test_ts_pmt_watcher import (
    AAC,
    AC3,
    AUDIO_PID,
    H264,
    PMT_PID,
    VIDEO_PID,
    make_filler,
    make_packet,
    make_pat,
    make_pmt,
)

AAC_LAYOUT = [(H264, VIDEO_PID), (AAC, AUDIO_PID)]
AC3_LAYOUT = [(H264, VIDEO_PID), (AC3, AUDIO_PID)]


class LocatePsiPacketsTests(unittest.TestCase):
    def test_finds_pat_and_pmt_in_order(self):
        filler = make_filler()
        data = filler + make_pat() + filler * 3 + make_pmt(AAC_LAYOUT) + filler
        self.assertEqual(
            locate_psi_packets(data, PMT_PID),
            ((TS_PACKET_SIZE, True), (5 * TS_PACKET_SIZE, False)),
        )

    def test_without_a_known_pmt_pid_only_pats_are_reported(self):
        data = make_pmt(AAC_LAYOUT) + make_pat() + make_filler()
        self.assertEqual(
            locate_psi_packets(data, None), ((TS_PACKET_SIZE, True),)
        )

    def test_media_and_look_alikes_are_not_reported(self):
        # PID 0 without PUSI is not a PAT start; other PIDs are media.
        data = (
            make_packet(0, b"\x01" * 20, pusi=False)
            + make_filler()
            + make_packet(0x1FFF, b"")
        )
        self.assertEqual(locate_psi_packets(data, PMT_PID), ())

    def test_pmt_continuation_packets_are_reported_without_pusi(self):
        data = make_pmt(AAC_LAYOUT, pusi=False)
        self.assertEqual(locate_psi_packets(data, PMT_PID), ((0, False),))

    def test_error_and_priority_bits_do_not_hide_a_packet(self):
        pat = bytearray(make_pat())
        pat[1] |= 0x80 | 0x20  # transport_error_indicator, transport_priority
        self.assertEqual(locate_psi_packets(bytes(pat), PMT_PID), ((0, True),))

    def test_unaligned_data_is_left_to_the_resyncing_walk(self):
        data = make_filler() + make_pat()
        self.assertIsNone(locate_psi_packets(b"\x00\x00" + data, PMT_PID))
        self.assertIsNone(locate_psi_packets(data + b"\x47\x00", PMT_PID))
        self.assertIsNone(locate_psi_packets(b"", PMT_PID))
        broken = bytearray(data)
        broken[TS_PACKET_SIZE] = 0x00  # second packet loses its sync byte
        self.assertIsNone(locate_psi_packets(bytes(broken), PMT_PID))


class PsiScanCacheTests(unittest.TestCase):
    def test_second_reader_reuses_the_first_scan(self):
        data = make_pat() + make_pmt(AAC_LAYOUT) + make_filler()
        cache = PsiScanCache()
        with patch.object(
            psi_scan, "locate_psi_packets", wraps=psi_scan.locate_psi_packets
        ) as scan:
            first = PmtLayoutWatcher(scan_cache=cache)
            second = PmtLayoutWatcher(scan_cache=cache)
            first.find_layout_change(data, chunk_index=7)
            second.find_layout_change(data, chunk_index=7)
        # Each watcher learns the PMT PID from the PAT, so a chunk can be
        # looked up under two keys. Two readers still share every lookup.
        self.assertEqual(scan.call_count, 2)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_without_a_chunk_index_nothing_is_cached(self):
        """A remainder or prepended buffer is not the chunk the index names."""
        data = make_pat() + make_pmt(AAC_LAYOUT)
        cache = PsiScanCache()
        watcher = PmtLayoutWatcher(scan_cache=cache)
        with patch.object(
            ts_pmt, "locate_psi_packets", wraps=ts_pmt.locate_psi_packets
        ) as scan:
            watcher.find_layout_change(data)
            watcher.find_layout_change(data)
        self.assertEqual(len(cache._items), 0)
        self.assertGreaterEqual(scan.call_count, 2)

    def test_key_includes_pmt_pid_and_length(self):
        cache = PsiScanCache()
        data = make_pat() + make_pmt(AAC_LAYOUT)
        self.assertEqual(cache.locate(1, data, None), ((0, True),))
        self.assertEqual(cache.locate(1, data, PMT_PID), ((0, True), (TS_PACKET_SIZE, False)))
        self.assertEqual(cache.locate(1, data[:TS_PACKET_SIZE], PMT_PID), ((0, True),))

    def test_oldest_entries_are_evicted(self):
        cache = PsiScanCache(capacity=2)
        data = make_pat()
        for index in (1, 2, 3):
            cache.locate(index, data, PMT_PID)
        self.assertEqual(
            [key[0] for key in cache._items], [2, 3]
        )

    def test_unaligned_result_is_cached_too(self):
        cache = PsiScanCache()
        data = b"\x00" + make_pat()
        self.assertIsNone(cache.locate(1, data, PMT_PID))
        self.assertEqual(len(cache._items), 1)


class ChunkIndexPlumbingTests(unittest.TestCase):
    def test_only_the_untouched_chunk_carries_its_index(self):
        """After a cut the data is a remainder with packets prepended."""
        seen = []

        class SpyWatcher(PmtLayoutWatcher):
            def find_layout_change(self, data, chunk_index=None):
                seen.append(chunk_index)
                return super().find_layout_change(data, chunk_index)

        watcher = SpyWatcher()
        watcher.find_layout_change(make_pat() + make_pmt(AAC_LAYOUT))
        seen.clear()

        chunk = make_filler() + make_pmt(AC3_LAYOUT) + make_filler()
        restarts = []

        def restart(reason, flush=b""):
            restarts.append(flush)
            from apps.proxy.live_proxy.output.pipe_restart import RestartOutcome
            return RestartOutcome.REPLACED

        written = []
        feed_chunk_with_layout_watch(
            chunk, watcher, lambda d: written.append(d) or True, restart, chunk_index=42
        )
        self.assertEqual(len(restarts), 1)
        self.assertEqual(seen, [42, None])


def _random_stream(rng, packets):
    layouts = [AAC_LAYOUT, AC3_LAYOUT, AAC_LAYOUT + [(AC3, 258)]]
    pmt_pids = (4096, 4097)
    current_pmt = rng.choice(pmt_pids)
    layout = rng.choice(layouts)
    out = []
    for _ in range(packets):
        roll = rng.random()
        if roll < 0.03:
            if rng.random() < 0.2:
                current_pmt = rng.choice(pmt_pids)
            out.append(make_pat(current_pmt))
        elif roll < 0.06:
            if rng.random() < 0.3:
                layout = rng.choice(layouts)
            out.append(make_pmt(layout, pmt_pid=current_pmt))
        elif roll < 0.07:
            out.append(make_packet(rng.choice([0, 4096, 4097]), b"\x01" * 20))
        else:
            packet = bytearray(make_filler(rng.choice([VIDEO_PID, AUDIO_PID, 258, 0x1FFF])))
            packet[1] |= rng.choice([0x00, 0x80, 0x20])
            out.append(bytes(packet))
    return out


def _cuts(watcher, find, data):
    """Every cut offset in ``data``, scanning on after each one."""
    cuts, base = [], 0
    while True:
        at = find(watcher, data)
        if at is None:
            return cuts
        cuts.append(base + at)
        watcher.accept_layout_change()
        base += at
        data = data[at:]


def _located(watcher, data):
    return watcher.find_layout_change(data)


def _walked(watcher, data):
    watcher.leading_section = b""
    watcher._pmt_sections.retag_origins(None)
    return watcher._walk_packets(data)


class LocatedPathMatchesPacketWalkTests(unittest.TestCase):
    def test_same_cuts_and_learned_state_on_random_streams(self):
        rng = random.Random(1888)
        for trial in range(120):
            data = b"".join(_random_stream(rng, rng.randrange(1, 200)))
            located, walked = PmtLayoutWatcher(), PmtLayoutWatcher()
            position = 0
            while position < len(data):
                step = TS_PACKET_SIZE * rng.randrange(1, 60)
                chunk = data[position:position + step]
                position += step
                self.assertEqual(
                    _cuts(located, _located, chunk),
                    _cuts(walked, _walked, chunk),
                    f"trial {trial}",
                )
                self.assertEqual(located.fingerprint, walked.fingerprint)
                self.assertEqual(located.pat_packet, walked.pat_packet)
                self.assertEqual(located._pmt_pid, walked._pmt_pid)
                self.assertEqual(located.leading_section, walked.leading_section)

    def test_pmt_on_a_new_pid_after_a_pat_in_the_same_chunk_is_found(self):
        watcher = PmtLayoutWatcher()
        watcher.find_layout_change(make_pat(4096) + make_pmt(AAC_LAYOUT, pmt_pid=4096))
        moved = (
            make_pat(4097)
            + make_filler()
            + make_pmt(AC3_LAYOUT, pmt_pid=4097)
        )
        self.assertEqual(watcher.find_layout_change(moved), 2 * TS_PACKET_SIZE)

    def test_shared_cache_gives_each_reader_its_own_answer(self):
        """Readers at different points in the stream must not borrow state."""
        cache = PsiScanCache()
        chunk = make_filler() + make_pmt(AC3_LAYOUT) + make_filler()

        seeded = PmtLayoutWatcher(scan_cache=cache)
        seeded.find_layout_change(make_pat() + make_pmt(AAC_LAYOUT), chunk_index=1)
        fresh = PmtLayoutWatcher(scan_cache=cache)
        fresh.find_layout_change(make_pat(), chunk_index=1)

        # The reader that knows the AAC layout sees a change; one that has not
        # seen a PMT yet only seeds, though both used the same cached lookup.
        self.assertEqual(seeded.find_layout_change(chunk, chunk_index=2), TS_PACKET_SIZE)
        self.assertIsNone(fresh.find_layout_change(chunk, chunk_index=2))


if __name__ == "__main__":
    unittest.main()
