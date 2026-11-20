"""Mid-chunk join trim: RAP-preferred start and PAT/PMT prepend."""

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.join_trim import (
    collect_parameter_sets,
    discover_layout_in_chunks,
    discover_video_layout,
    find_last_keyframe_offset,
    inject_decoder_init,
    prepare_join_chunk,
    psi_prefix_from_head,
    resolve_start_offset,
    scan_chunk_media_entries,
    snap_back_to_keyframe,
    trim_chunk_at_offset,
)
from apps.proxy.live_proxy.ts_nal import (
    build_parameter_set_packets,
    packet_has_decoder_init,
    starts_keyframe,
)
from apps.proxy.live_proxy.tests.test_buffer_discontinuity import _FakeRedis
from apps.proxy.live_proxy.tests.test_ts_clock import (
    AUDIO_PID,
    VIDEO_PID,
    make_filler,
    make_pes_pts,
)
from apps.proxy.live_proxy.tests.test_ts_pmt_watcher import (
    AAC,
    H264,
    make_pat,
    make_pmt,
)
from apps.proxy.live_proxy.tests.test_ts_pmt_watcher import AUDIO_PID as PMT_AUDIO_PID
from apps.proxy.live_proxy.ts_clock import (
    CLOCK_PTS,
    PTS_WRAP_SECONDS,
    last_clock_on_pid_with_offset,
)


CHANNEL_ID = "cccccccc-dddd-eeee-ffff-000000000001"
SETTING = "apps.proxy.live_proxy.input.buffer.ConfigHelper.experimental_ingest_buffer"


class JoinTrimHelperTests(SimpleTestCase):
    def test_resolve_prefers_last_rap_at_or_before_target(self):
        entries = [
            (0, 10.0, False),
            (TS_PACKET_SIZE, 10.5, True),
            (2 * TS_PACKET_SIZE, 11.0, False),
            (3 * TS_PACKET_SIZE, 11.5, True),
            (4 * TS_PACKET_SIZE, 12.0, False),
        ]
        self.assertEqual(resolve_start_offset(entries, 11.2), TS_PACKET_SIZE)
        self.assertEqual(resolve_start_offset(entries, 11.5), 3 * TS_PACKET_SIZE)
        self.assertEqual(resolve_start_offset(entries, 12.0), 3 * TS_PACKET_SIZE)

    def test_resolve_falls_back_to_last_pts_without_rap(self):
        entries = [
            (0, 10.0, False),
            (TS_PACKET_SIZE, 11.0, False),
            (2 * TS_PACKET_SIZE, 12.0, False),
        ]
        self.assertEqual(resolve_start_offset(entries, 11.5), TS_PACKET_SIZE)

    def test_resolve_aligns_raw_pts_to_unwrapped_target(self):
        """Sparse/raw packet PTS can sit in [0, wrap) while the join target does not."""
        entries = [
            (0, 1.0, False),
            (TS_PACKET_SIZE, 2.0, True),
            (2 * TS_PACKET_SIZE, 4.0, False),
        ]
        target = PTS_WRAP_SECONDS + 3.0
        self.assertEqual(resolve_start_offset(entries, target), TS_PACKET_SIZE)

    def test_scan_records_pts_and_rap(self):
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        data = (
            pat
            + pmt
            + make_filler()
            + make_pes_pts(VIDEO_PID, 1.0)
            + make_pes_pts(VIDEO_PID, 2.0, random_access=True)
        )
        entries = scan_chunk_media_entries(data)
        self.assertEqual(len(entries), 2)
        self.assertAlmostEqual(entries[0][1], 1.0, places=3)
        self.assertFalse(entries[0][2])
        self.assertAlmostEqual(entries[1][1], 2.0, places=3)
        self.assertTrue(entries[1][2])

    def test_trim_prepends_pat_pmt_from_discarded_head(self):
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        early = make_pes_pts(VIDEO_PID, 1.0)
        rap = make_pes_pts(VIDEO_PID, 2.0, random_access=True)
        late = make_pes_pts(VIDEO_PID, 3.0)
        chunk = pat + pmt + early + rap + late
        trimmed = trim_chunk_at_offset(chunk, 3 * TS_PACKET_SIZE)
        self.assertEqual(trimmed[:TS_PACKET_SIZE], pat)
        self.assertEqual(trimmed[TS_PACKET_SIZE : 2 * TS_PACKET_SIZE], pmt)
        self.assertEqual(trimmed[2 * TS_PACKET_SIZE :], rap + late)

    def test_psi_prefix_keeps_multipart_pmt_section(self):
        pat = make_pat()
        pmt_start = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)], pusi=True)
        pmt_cont = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)], pusi=False)
        head = pat + pmt_start + pmt_cont + make_filler()
        prefix = psi_prefix_from_head(head)
        self.assertEqual(prefix, pat + pmt_start + pmt_cont)

    def test_collect_parameter_sets_prefers_newer_nals(self):
        # Two SPS NALs: walking newest-first must keep the later one.
        old_sps = b"\x00\x00\x00\x01\x67" + b"\x11" * 8
        new_sps = b"\x00\x00\x00\x01\x67" + b"\x22" * 8
        pps = b"\x00\x00\x00\x01\x68" + b"\xce" * 4
        old_pkts = build_parameter_set_packets(VIDEO_PID, {7: old_sps, 8: pps}, 0x1B)
        new_pkts = build_parameter_set_packets(VIDEO_PID, {7: new_sps, 8: pps}, 0x1B)
        data = b"".join(old_pkts) + make_filler() + b"".join(new_pkts)
        found = collect_parameter_sets(data, VIDEO_PID, 0x1B)
        self.assertEqual(found[7], new_sps)
        self.assertEqual(found[8], pps)

    def test_audio_rap_does_not_trim_past_video_target(self):
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        video = make_pes_pts(VIDEO_PID, 10.0)
        audio_kf = make_pes_pts(AUDIO_PID, 10.8, random_access=True)
        video_late = make_pes_pts(VIDEO_PID, 11.0)
        chunk = pat + pmt + video + audio_kf + video_late
        out = prepare_join_chunk(chunk, 10.5)
        body = out[2 * TS_PACKET_SIZE :]
        self.assertTrue(body.startswith(video))
        self.assertIn(video_late, body)

    def test_prepare_join_chunk_uses_map_when_present(self):
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        early = make_pes_pts(VIDEO_PID, 10.0)
        rap = make_pes_pts(VIDEO_PID, 10.5, random_access=True)
        late = make_pes_pts(VIDEO_PID, 11.0)
        chunk = pat + pmt + early + rap + late
        media_map = (
            (2 * TS_PACKET_SIZE, 10.0, False),
            (3 * TS_PACKET_SIZE, 10.5, True),
            (4 * TS_PACKET_SIZE, 11.0, False),
        )
        out = prepare_join_chunk(chunk, 10.8, media_map=media_map)
        self.assertEqual(out[:TS_PACKET_SIZE], pat)
        self.assertEqual(out[2 * TS_PACKET_SIZE :], rap + late)

    def test_inject_decoder_init_prepends_before_opening_keyframe(self):
        # Minimal Annex-B SPS (7) + PPS (8) NALs; sizes only need to round-trip
        # through build_parameter_set_packets for the splice test.
        sps = b"\x00\x00\x00\x01\x67" + b"\x42" * 8
        pps = b"\x00\x00\x00\x01\x68" + b"\xce" * 4
        param_packets = build_parameter_set_packets(
            VIDEO_PID, {7: sps, 8: pps}, 0x1B
        )
        self.assertTrue(param_packets)
        # Opening keyframe has RAP but no parameter sets in-band.
        opening = make_pes_pts(VIDEO_PID, 5.0, random_access=True)
        self.assertFalse(packet_has_decoder_init(opening, 0x1B))
        body = make_pat() + make_pmt([(H264, VIDEO_PID)]) + opening
        out = inject_decoder_init(body, VIDEO_PID, 0x1B, {7: sps, 8: pps})
        self.assertGreater(len(out), len(body))
        # Injected packets sit immediately before the opening video packet.
        video_off = out.find(opening)
        self.assertGreater(video_off, 0)
        injected = out[video_off - len(param_packets[0]) * len(param_packets) : video_off]
        self.assertEqual(len(injected) % TS_PACKET_SIZE, 0)

    def test_snap_back_finds_nearest_keyframe_behind_offset(self):
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID)])
        early_rap = make_pes_pts(VIDEO_PID, 1.0, random_access=True)
        mid_rap = make_pes_pts(VIDEO_PID, 2.0, random_access=True)
        p_frame = make_pes_pts(VIDEO_PID, 2.5)
        late_rap = make_pes_pts(VIDEO_PID, 3.0, random_access=True)
        data = pat + pmt + early_rap + mid_rap + p_frame + late_rap
        p_off = 4 * TS_PACKET_SIZE
        # Nearest keyframe at or before the P-frame, not the earlier one or the later one.
        self.assertEqual(
            snap_back_to_keyframe(data, p_off, VIDEO_PID, H264), 3 * TS_PACKET_SIZE
        )
        # Exactly on a keyframe stays put.
        late_off = 5 * TS_PACKET_SIZE
        self.assertEqual(snap_back_to_keyframe(data, late_off, VIDEO_PID, H264), late_off)
        # No keyframe behind the offset leaves it unchanged.
        only_p = pat + pmt + make_pes_pts(VIDEO_PID, 1.0) + make_pes_pts(VIDEO_PID, 2.0)
        self.assertEqual(
            snap_back_to_keyframe(only_p, 3 * TS_PACKET_SIZE, VIDEO_PID, H264),
            3 * TS_PACKET_SIZE,
        )

    def test_find_last_keyframe_offset_walks_back_and_honors_target(self):
        early = make_pes_pts(VIDEO_PID, 9.0, random_access=True)
        late = make_pes_pts(VIDEO_PID, 11.0, random_access=True)
        data = early + make_pes_pts(VIDEO_PID, 9.5) + late + make_pes_pts(VIDEO_PID, 11.5)
        self.assertEqual(
            find_last_keyframe_offset(data, VIDEO_PID, H264), 2 * TS_PACKET_SIZE
        )
        # A keyframe after the target is skipped in favor of the earlier one.
        self.assertEqual(
            find_last_keyframe_offset(data, VIDEO_PID, H264, target_media=10.0), 0
        )
        self.assertIsNone(
            find_last_keyframe_offset(
                make_pes_pts(VIDEO_PID, 9.0), VIDEO_PID, H264, target_media=10.0
            )
        )

    def test_discover_layout_finds_psi_anywhere_in_chunk(self):
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        # A fixed head-of-chunk window would miss PSI this deep.
        for lead in (100, 511, 1500):
            chunk = make_filler() * lead + pat + pmt + make_filler()
            self.assertEqual(discover_video_layout(chunk), (VIDEO_PID, H264), lead)
        self.assertEqual(discover_video_layout(make_filler() * 20), (None, None))

    def test_discover_layout_indexes_headers_once(self):
        from unittest.mock import patch

        from apps.proxy.live_proxy import join_trim
        from apps.proxy.live_proxy.psi_scan import index_psi_headers

        chunk = make_pat() + make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        with patch.object(
            join_trim, "index_psi_headers", wraps=index_psi_headers
        ) as index:
            self.assertEqual(discover_video_layout(chunk), (VIDEO_PID, H264))
        self.assertEqual(index.call_count, 1)

    def test_psi_prefix_filters_pat_headers_once(self):
        from unittest.mock import patch

        from apps.proxy.live_proxy.psi_scan import PsiHeaderIndex

        head = make_pat() + make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        orig = PsiHeaderIndex.pat_offsets
        calls = {"n": 0}

        def counting(self):
            calls["n"] += 1
            return orig(self)

        with patch.object(PsiHeaderIndex, "pat_offsets", counting):
            prefix = psi_prefix_from_head(head)
        self.assertTrue(prefix.startswith(make_pat()))
        # Learn pmt_pid with one PAT filter; locate(pats=...) must not filter again.
        self.assertEqual(calls["n"], 1)

    def test_resolve_join_cut_inspects_non_rap_keyframe_once(self):
        from unittest.mock import patch

        from apps.proxy.live_proxy.join_trim import resolve_join_cut

        sps = b"\x00\x00\x00\x01\x67" + b"\x42" * 8
        pps = b"\x00\x00\x00\x01\x68" + b"\xce" * 4
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID)])
        early = make_pes_pts(VIDEO_PID, 1.0)
        late = make_pes_pts(VIDEO_PID, 2.0)
        chunk = pat + pmt + early + late
        with patch(
            "apps.proxy.live_proxy.join_trim.inspect_avc_hevc_packet",
            return_value=(True, {7: sps, 8: pps}),
        ) as inspect, patch(
            "apps.proxy.live_proxy.join_trim.snap_back_to_keyframe",
            side_effect=lambda data, offset, *a, **k: offset,
        ):
            cut = resolve_join_cut(
                chunk,
                1.5,
                video_pid=VIDEO_PID,
                stream_type=H264,
            )
        self.assertTrue(cut["has_kf"])
        self.assertTrue(cut["skip_prior_fetch"])
        self.assertEqual(inspect.call_count, 1)

    def test_discover_layout_in_chunks_takes_first_hit_newest_first(self):
        with_psi = make_pat() + make_pmt([(H264, VIDEO_PID)]) + make_filler()
        no_psi = make_filler() * 4
        self.assertEqual(
            discover_layout_in_chunks([no_psi, with_psi]), (VIDEO_PID, H264)
        )
        self.assertEqual(discover_layout_in_chunks([no_psi]), (None, None))
        self.assertEqual(discover_layout_in_chunks([]), (None, None))

    def test_prior_chunk_supplies_keyframe_across_boundary(self):
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        # Prior chunk ends with the only RAP at or before the join target.
        prior = (
            pat
            + pmt
            + make_filler()
            + make_pes_pts(VIDEO_PID, 9.5, random_access=True)
            + make_pes_pts(VIDEO_PID, 9.8)
        )
        # Join chunk: target 10.2, only non-RAP video (mid-GOP).
        join = (
            pat
            + pmt
            + make_filler()
            + make_pes_pts(VIDEO_PID, 10.0)
            + make_pes_pts(VIDEO_PID, 10.4)
        )
        join_map = (
            (3 * TS_PACKET_SIZE, 10.0, False),
            (4 * TS_PACKET_SIZE, 10.4, False),
        )
        out = prepare_join_chunk(
            join,
            10.2,
            media_map=join_map,
            prior_chunks=[prior],
        )
        # Delivery starts on the prior RAP and still includes the join chunk.
        self.assertIn(make_pes_pts(VIDEO_PID, 9.5, random_access=True), out)
        self.assertTrue(out.endswith(join) or join in out)
        self.assertGreater(len(out), len(join))


class JoinTrimBufferTests(SimpleTestCase):
    def setUp(self):
        from unittest.mock import patch

        patcher = patch(SETTING, return_value=True)
        self.setting = patcher.start()
        self.addCleanup(patcher.stop)

    def _buffer(self):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.target_chunk_size = TS_PACKET_SIZE * 8
        buf.enable_media_index(True)

        def hook(data, wall=None):
            media, off = last_clock_on_pid_with_offset(data, VIDEO_PID, CLOCK_PTS)
            if media is not None:
                buf.note_media_clock(media, append_len=len(data), offset_in_append=off)

        buf.on_packets_received = hook
        return buf, redis

    def test_note_records_rap_flag_from_clock_packet(self):
        buf, _redis = self._buffer()
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        # The sampled clock is the RAP packet itself (newest PTS in the read).
        rap = make_pes_pts(VIDEO_PID, 5.0, random_access=True)
        self.assertTrue(buf.add_chunk(make_filler() * 3 + rap))
        samples = buf.chunk_media_map(1)
        self.assertEqual(len(samples), 1)
        self.assertTrue(samples[0][2])

    def test_resolve_join_returns_target_and_prepare_trims_first_chunk(self):
        buf, _redis = self._buffer()
        # Four scored chunks ending at 100,102,104,106. 2s behind -> target 104,
        # start chunk index 3 (last-consumed 2). Mid-chunk RAP is not the
        # sampled clock; prepare snaps back to it from the chunk bytes.
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        for pts in (100.0, 102.0, 104.0, 106.0):
            self.assertTrue(
                buf.add_chunk(
                    pat
                    + pmt
                    + make_filler() * 3
                    + make_pes_pts(VIDEO_PID, pts - 0.5)
                    + make_pes_pts(VIDEO_PID, pts - 0.2, random_access=True)
                    + make_filler()
                    + make_pes_pts(VIDEO_PID, pts)
                    + make_filler()
                )
            )
        last_consumed, target = buf.resolve_join_position(2.0)
        self.assertAlmostEqual(target, 104.0, places=3)
        self.assertIsNotNone(last_consumed)

        indexed, _new = buf.get_optimized_client_data_indexed(last_consumed)
        chunk_index, chunk = indexed[0]
        self.assertGreaterEqual(chunk_index, 3)
        trimmed = buf.prepare_first_join_chunk(chunk_index, chunk, target)
        self.assertLess(len(trimmed), len(chunk))
        # Trimmed body should open on the RAP packet (after optional PSI).
        entries = scan_chunk_media_entries(trimmed)
        self.assertTrue(entries)
        self.assertTrue(entries[0][2])
        self.assertAlmostEqual(entries[0][1], 103.8, places=2)

    def test_prepare_ignores_parameter_sets_from_before_discontinuity(self):
        buf, _redis = self._buffer()
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        # Chunks 1-2: old era with parameter sets. Disc at 3 starts the new era.
        sps = b"\x00\x00\x00\x01\x67" + b"\x42" * 8
        pps = b"\x00\x00\x00\x01\x68" + b"\xce" * 4
        param_pkts = build_parameter_set_packets(VIDEO_PID, {7: sps, 8: pps}, 0x1B)
        old = make_pat() + make_pmt([(H264, VIDEO_PID)]) + b"".join(param_pkts)
        # Pad to chunk size.
        while len(old) < buf.target_chunk_size:
            old += make_filler()
        old = old[: buf.target_chunk_size]
        self.assertTrue(buf.add_chunk(old))
        self.assertTrue(buf.add_chunk(old))
        buf.mark_discontinuity()
        # New-era chunks 3-4: layout only, no parameter sets.
        fresh = make_pat() + make_pmt([(H264, VIDEO_PID)]) + make_filler() * 2
        self.assertTrue(buf.add_chunk(fresh))
        self.assertTrue(buf.add_chunk(fresh))
        # Join on chunk 4 must not inject SPS/PPS from before the disc at 3.
        trimmed = buf.prepare_first_join_chunk(4, fresh, 1.0)
        self.assertNotIn(sps, trimmed)
        self.assertNotIn(pps, trimmed)

    def test_prepare_pulls_prior_chunk_when_join_chunk_has_no_rap(self):
        buf, redis = self._buffer()
        buf.target_chunk_size = TS_PACKET_SIZE * 6
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])

        def scored(pts_end, with_rap):
            body = pat + pmt + make_filler()
            if with_rap:
                body += make_pes_pts(VIDEO_PID, pts_end - 0.4, random_access=True)
            body += make_pes_pts(VIDEO_PID, pts_end - 0.1)
            body += make_pes_pts(VIDEO_PID, pts_end)
            while len(body) < buf.target_chunk_size:
                body += make_filler()
            return body[: buf.target_chunk_size]

        # Chunk 1: RAP. Chunk 2: mid-GOP only, scored later.
        self.assertTrue(buf.add_chunk(scored(100.0, with_rap=True)))
        self.assertTrue(buf.add_chunk(scored(101.0, with_rap=False)))
        join_idx = 2
        join = redis.kv.get(f"{buf.buffer_prefix}{join_idx}")
        trimmed = buf.prepare_first_join_chunk(join_idx, join, 100.7)
        # Must be longer than the join chunk alone (prior RAP tail prepended).
        self.assertGreater(len(trimmed), len(join))
        entries = scan_chunk_media_entries(trimmed)
        self.assertTrue(entries)
        self.assertTrue(entries[0][2])

    def _padded(self, buf, *parts):
        body = b"".join(parts)
        while len(body) < buf.target_chunk_size:
            body += make_filler()
        return body[: buf.target_chunk_size]

    def test_join_chunk_without_psi_learns_layout_from_older_chunk(self):
        """PAT/PMT often ride only with keyframes, so a chunk can have none."""
        buf, redis = self._buffer()
        buf.target_chunk_size = TS_PACKET_SIZE * 12
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])
        rap = make_pes_pts(VIDEO_PID, 100.5, random_access=True)
        # Chunk 1 carries the PSI. Chunk 2 has none: a keyframe mid-chunk.
        first = self._padded(buf, pat, pmt, make_pes_pts(VIDEO_PID, 100.0))
        second = self._padded(
            buf,
            make_filler() * 3,
            make_pes_pts(VIDEO_PID, 100.2),
            make_filler(),
            rap,
            make_filler() * 2,
            make_pes_pts(VIDEO_PID, 101.0),
        )
        self.assertTrue(buf.add_chunk(first))
        self.assertTrue(buf.add_chunk(second))
        self.assertEqual(discover_video_layout(second), (None, None))

        # The join chunk ends (101.0) at or before the target, as the join
        # script guarantees.
        trimmed = buf.prepare_first_join_chunk(2, second, 101.2)
        self.assertLess(len(trimmed), len(second))
        # Without the layout fallback this cut lands on a non-keyframe.
        self.assertTrue(trimmed.startswith(rap))
        self.assertTrue(starts_keyframe(trimmed[:TS_PACKET_SIZE], H264))

    def test_prior_walk_stops_at_missing_chunk(self):
        buf, redis = self._buffer()
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        key = buf.chunk_media_scores_key
        for idx, score in ((1, 98.5), (2, 99.0), (3, 99.5)):
            redis.zadd(key, {str(idx): score})
        # Chunk 3 present, chunk 2 expired, chunk 1 still present (stale).
        redis.setex(f"{buf.buffer_prefix}3", 60, b"\x47" * TS_PACKET_SIZE * 4)
        redis.setex(f"{buf.buffer_prefix}1", 60, b"\x47" * TS_PACKET_SIZE * 4)
        priors = buf._load_join_prior_chunks(4, target_media=100.0)
        self.assertEqual(len(priors), 1)

    def test_join_prior_indexes_start_at_newest_chunk_before_window(self):
        """Span starts at the newest chunk that appears to end before the window.

        Chunk 1 is scored just under the window edge, but scores come from the
        last sampled clock so it can run past that. Chunk 2 is unscored and
        sits between chunk 1 and the scored chunk 3. Both may hold the keyframe
        at the window edge, and chunks older than 1 cannot.
        """
        buf, redis = self._buffer()
        key = buf.chunk_media_scores_key
        redis.zadd(key, {"0": 90.0})
        redis.zadd(key, {"1": 98.9})
        redis.zadd(key, {"3": 100.5})
        indexes = buf._join_prior_indexes(4, target_media=101.0)
        self.assertEqual(indexes, [3, 2, 1])

    def test_join_prior_indexes_reach_era_floor_when_nothing_ends_before_window(self):
        buf, redis = self._buffer()
        redis.zadd(buf.chunk_media_scores_key, {"3": 100.5})
        self.assertEqual(buf._join_prior_indexes(4, target_media=101.0), [3, 2, 1])

    def test_join_prior_indexes_are_capped(self):
        from apps.proxy.live_proxy.join_trim import KEYFRAME_LOOKBACK_MAX_CHUNKS

        buf, redis = self._buffer()
        join_idx = KEYFRAME_LOOKBACK_MAX_CHUNKS + 10
        indexes = buf._join_prior_indexes(join_idx, target_media=500.0)
        self.assertEqual(len(indexes), KEYFRAME_LOOKBACK_MAX_CHUNKS)
        self.assertEqual(indexes[0], join_idx - 1)

    def test_score_window_reaches_beyond_three_chunks(self):
        """~2s media window includes a RAP more than three chunks back."""
        buf, redis = self._buffer()
        buf.target_chunk_size = TS_PACKET_SIZE * 6
        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO_PID)])

        def scored(pts_end, with_rap=False):
            body = pat + pmt + make_filler()
            if with_rap:
                body += make_pes_pts(VIDEO_PID, pts_end - 0.2, random_access=True)
            body += make_pes_pts(VIDEO_PID, pts_end)
            while len(body) < buf.target_chunk_size:
                body += make_filler()
            return body[: buf.target_chunk_size]

        # Five short chunks spanning ~1.6s. RAP only on chunk 1; join on 5.
        # A fixed three-chunk step would only load 4..2 and miss the RAP.
        self.assertTrue(buf.add_chunk(scored(100.0, with_rap=True)))
        for pts in (100.4, 100.8, 101.2, 101.6):
            self.assertTrue(buf.add_chunk(scored(pts)))
        join_idx = 5
        join = redis.kv.get(f"{buf.buffer_prefix}{join_idx}")
        indexes = buf._join_prior_indexes(join_idx, target_media=101.5)
        self.assertIn(1, indexes)
        self.assertGreater(len(indexes), 3)
        trimmed = buf.prepare_first_join_chunk(join_idx, join, 101.5)
        self.assertGreater(len(trimmed), len(join))
        entries = scan_chunk_media_entries(trimmed)
        self.assertTrue(entries)
        self.assertTrue(entries[0][2])
        self.assertAlmostEqual(entries[0][1], 99.8, places=2)
