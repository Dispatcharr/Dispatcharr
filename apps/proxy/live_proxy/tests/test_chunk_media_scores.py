"""Stream-time join positioning via chunk_media_scores (experimental ingest)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.output import buffer as output_buffer
from apps.proxy.live_proxy.output.buffer import OutputStreamBuffer
from apps.proxy.live_proxy.tests.test_buffer_discontinuity import _FakeRedis
from apps.proxy.live_proxy.tests.test_ts_clock import (
    VIDEO_PID,
    make_filler,
    make_pes_pts,
)
from apps.proxy.live_proxy.ts_clock import (
    CLOCK_PTS,
    PTS_WRAP_SECONDS,
    last_clock_on_pid_with_offset,
)


CHANNEL_ID = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
SETTING = "apps.proxy.live_proxy.input.buffer.ConfigHelper.experimental_ingest_buffer"


def _chunk_with_pts(pts_seconds, packets=4):
    """One Redis-sized chunk whose last packet carries ``pts_seconds`` on VIDEO_PID."""
    return make_filler() * (packets - 1) + make_pes_pts(VIDEO_PID, pts_seconds)


def _ingest_hook(buf):
    """What StreamManager._on_packets_received does for the chunk buffer.

    Ingest parses the locked clock once; the buffer only records the result.
    """

    def hook(data, wall=None):
        media, off = last_clock_on_pid_with_offset(data, VIDEO_PID, CLOCK_PTS)
        if media is not None:
            buf.note_media_clock(media, append_len=len(data), offset_in_append=off)

    return hook


class ChunkMediaScoreJoinTests(SimpleTestCase):
    def setUp(self):
        # Default: experimental off. Readers on other workers consult this.
        patcher = patch(SETTING, return_value=False)
        self.setting = patcher.start()
        self.addCleanup(patcher.stop)

    def _buffer(self, media_index=True):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        if media_index:
            buf.enable_media_index(True)
            buf.on_packets_received = _ingest_hook(buf)
        return buf, redis

    def _write_pts_chunks(self, buf, pts_list):
        for pts in pts_list:
            self.assertTrue(buf.add_chunk(_chunk_with_pts(pts)))

    def test_media_scores_written_when_index_enabled(self):
        buf, redis = self._buffer(media_index=True)
        self._write_pts_chunks(buf, [10.0, 12.0, 14.0])
        scores = redis.zsets[buf.chunk_media_scores_key]
        self.assertEqual(len(scores), 3)
        self.assertAlmostEqual(scores["1"], 10.0, places=3)
        self.assertAlmostEqual(scores["2"], 12.0, places=3)
        self.assertAlmostEqual(scores["3"], 14.0, places=3)
        # Wall timestamps still recorded for the fallback path.
        self.assertEqual(len(redis.zsets[buf.chunk_timestamps_key]), 3)

    def test_media_scores_skipped_when_index_disabled(self):
        buf, redis = self._buffer(media_index=False)
        self._write_pts_chunks(buf, [1.0, 2.0])
        self.assertNotIn(buf.chunk_media_scores_key, redis.zsets)
        self.assertEqual(len(redis.zsets[buf.chunk_timestamps_key]), 2)

    def test_disabling_media_index_deletes_published_scores(self):
        buf, redis = self._buffer(media_index=True)
        self._write_pts_chunks(buf, [100.0, 110.0])
        self.assertIn(buf.chunk_media_scores_key, redis.zsets)
        buf.enable_media_index(False)
        self.assertNotIn(buf.chunk_media_scores_key, redis.zsets)

    def test_enable_needs_a_scores_key(self):
        buf = StreamBuffer(
            CHANNEL_ID,
            redis_client=_FakeRedis(),
            buffer_index_key="custom:index",
            buffer_chunk_prefix="custom:chunk:",
        )
        self.assertEqual(buf.chunk_media_scores_key, "")
        buf.enable_media_index(True)
        self.assertFalse(buf.media_index_enabled)

    def test_reader_on_another_worker_joins_on_published_scores(self):
        """Readers never enable indexing (that clears the scores); the setting decides."""
        writer, redis = self._buffer(media_index=True)
        self._write_pts_chunks(writer, [100.0, 102.0, 104.0, 106.0])
        self.setting.return_value = True
        reader = StreamBuffer(CHANNEL_ID, redis_client=redis)
        self.assertFalse(reader.media_index_enabled)
        reader.index = 1  # stale local index; the script reads the published head
        # 2s behind published head 106 -> chunk 104 (index 3), last-consumed 2.
        self.assertEqual(reader.find_chunk_index_behind(2.0), 2)

    def test_default_join_costs_only_the_wall_clock_script(self):
        """Experimental off: no media lookup and no extra Redis round trip."""
        _writer, redis = self._buffer(media_index=False)
        reader = StreamBuffer(CHANNEL_ID, redis_client=redis)
        reader._find_chunk_behind_sha = MagicMock()
        reader._find_chunk_by_time_sha = MagicMock(return_value=-1)
        redis.exists = MagicMock()
        reader.find_chunk_index_behind(6.0)
        reader._find_chunk_behind_sha.assert_not_called()
        redis.exists.assert_not_called()
        reader._find_chunk_by_time_sha.assert_called_once()

    def test_find_behind_uses_media_scores(self):
        buf, redis = self._buffer(media_index=True)
        self._write_pts_chunks(buf, [100.0, 102.0, 104.0, 106.0])
        # 4s behind head (106) -> chunk at 102 (index 2); last-consumed = 1
        self.assertEqual(buf.find_chunk_index_behind(4.0), 1)
        # Exactly at a scored chunk: last-consumed is that index - 1
        self.assertEqual(buf.find_chunk_index_behind(2.0), 2)
        # Deeper than the buffer: oldest last-consumed
        self.assertEqual(buf.find_chunk_index_behind(60.0), 0)

    def test_find_behind_falls_back_to_wall_without_media(self):
        buf, redis = self._buffer(media_index=False)
        now = 1_700_000_000.0
        # Manually seed wall scores as if chunks arrived one second apart.
        for i, age in enumerate((3.0, 2.0, 1.0, 0.0), start=1):
            key = f"{buf.buffer_prefix}{i}"
            redis.setex(key, 60, _chunk_with_pts(0.0))
            redis.zadd(buf.chunk_timestamps_key, {str(i): now - age})
            redis.set(buf.buffer_index_key, str(i))
            buf.index = i

        import apps.proxy.live_proxy.input.buffer as buffer_mod

        real_time = buffer_mod.time.time
        buffer_mod.time.time = lambda: now
        try:
            # 2.5s behind wall now -> chunk received at now-3 (index 1);
            # last-consumed = 0
            self.assertEqual(buf.find_chunk_index_behind(2.5), 0)
        finally:
            buffer_mod.time.time = real_time

    def test_mark_discontinuity_clears_media_scores(self):
        buf, redis = self._buffer(media_index=True)
        self._write_pts_chunks(buf, [10.0, 12.0])
        self.assertIn(buf.chunk_media_scores_key, redis.zsets)
        buf.mark_discontinuity()
        self.assertNotIn(buf.chunk_media_scores_key, redis.zsets)
        self.assertEqual(buf.chunk_media_map(1), ())
        # New era can score again from a clean slate.
        self._write_pts_chunks(buf, [1.0])
        self.assertAlmostEqual(
            redis.zsets[buf.chunk_media_scores_key][str(buf.index)], 1.0, places=3
        )

    def test_unsampled_chunk_stays_unscored_and_is_never_scanned(self):
        """Ingest owns sampling. A chunk it did not sample is left unscored."""
        buf, redis = self._buffer(media_index=True)
        buf.on_packets_received = lambda data, wall=None: None  # ingest throttled
        body = make_pes_pts(VIDEO_PID, 42.0) + make_filler() * 99
        buf.target_chunk_size = len(body)
        self.assertTrue(buf.add_chunk(body))
        self.assertEqual(buf.index, 1)
        self.assertNotIn("1", redis.zsets.get(buf.chunk_media_scores_key, {}))

    def test_unscored_chunks_still_refresh_media_score_ttl(self):
        buf, redis = self._buffer(media_index=True)
        self._write_pts_chunks(buf, [10.0])
        redis.ttls[buf.chunk_media_scores_key] = 1
        self.assertTrue(buf.add_chunk(make_filler() * 4))  # no clock at all
        self.assertNotIn("2", redis.zsets[buf.chunk_media_scores_key])
        self.assertEqual(redis.ttls[buf.chunk_media_scores_key], buf.chunk_ttl)

    def test_join_uses_redis_head_not_stale_local_index(self):
        buf, redis = self._buffer(media_index=True)
        self._write_pts_chunks(buf, [100.0, 102.0, 104.0, 106.0])
        # A non-owner worker's StreamBuffer.index lags the published head.
        buf.index = 1
        # 2s behind published head (106) -> chunk 104 (index 3), last-consumed 2.
        self.assertEqual(buf.find_chunk_index_behind(2.0), 2)

    def test_join_stays_in_current_discontinuity_era(self):
        buf, redis = self._buffer(media_index=True)
        self._write_pts_chunks(buf, [1.0, 2.0, 100.0, 102.0])
        # Era starts at chunk 3. Do not go through mark_discontinuity, which
        # would delete the scores this case is guarding.
        redis.zadd(buf.discontinuities_key, {"3": 3.0})
        # 3s behind head 102 would otherwise match pre-era score 2.0 (index 2).
        self.assertEqual(buf.find_chunk_index_behind(3.0), 2)

    def test_media_scores_pruned_one_member_per_chunk(self):
        buf, redis = self._buffer(media_index=True)
        buf.chunk_ttl = 1  # keep window is max(64, ttl * 16) == 64
        self._write_pts_chunks(buf, [float(i) for i in range(1, 81)])
        scores = redis.zsets[buf.chunk_media_scores_key]
        # At index 80 the window floor is 80 - 64 = 16: members below it are gone.
        self.assertNotIn("1", scores)
        self.assertNotIn("15", scores)
        self.assertIn("16", scores)
        self.assertIn("80", scores)
        self.assertEqual(len(scores), 65)

    def test_chunk_end_scoring_without_ingest_hook(self):
        """Output-profile rings score the last PTS/PCR in each flushed chunk."""
        from apps.proxy.live_proxy.redis_keys import RedisKeys

        redis = _FakeRedis()
        fmt = "mpegts:p9"
        buf = StreamBuffer(
            CHANNEL_ID,
            redis_client=redis,
            buffer_index_key=RedisKeys.output_buffer_index(CHANNEL_ID, fmt),
            buffer_chunk_prefix=RedisKeys.output_buffer_chunk_prefix(CHANNEL_ID, fmt),
            chunk_timestamps_key=RedisKeys.output_chunk_timestamps(CHANNEL_ID, fmt),
            discontinuities_key=RedisKeys.output_buffer_discontinuities(
                CHANNEL_ID, fmt
            ),
            chunk_media_scores_key=RedisKeys.output_chunk_media_scores(
                CHANNEL_ID, fmt
            ),
        )
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        buf.media_score_from_chunk_end = True
        buf.enable_media_index(True)
        self.assertIsNone(buf.on_packets_received)
        self._write_pts_chunks(buf, [10.0, 12.0, 14.0])
        scores = redis.zsets[buf.chunk_media_scores_key]
        self.assertEqual(len(scores), 3)
        self.assertAlmostEqual(scores["1"], 10.0, places=3)
        self.assertAlmostEqual(scores["3"], 14.0, places=3)
        # No sparse map: clients mid-trim via a one-time scan of the join chunk.
        self.assertEqual(buf.chunk_media_map(1), ())
        self.assertEqual(buf.chunk_media_map(3), ())
        last_consumed, target = buf.resolve_join_position(2.0)
        self.assertIsNotNone(last_consumed)
        self.assertAlmostEqual(target, 12.0, places=3)

    def test_profile_end_scores_drive_client_join_trim(self):
        """Later profile clients join by stream time and mid-chunk trim without a map."""
        from apps.proxy.live_proxy.redis_keys import RedisKeys
        from apps.proxy.live_proxy.tests.test_ts_pmt_watcher import (
            AAC,
            H264,
            make_pat,
            make_pmt,
        )
        from apps.proxy.live_proxy.tests.test_ts_pmt_watcher import AUDIO_PID as PMT_AUDIO

        redis = _FakeRedis()
        fmt = "mpegts:p11"
        buf = StreamBuffer(
            CHANNEL_ID,
            redis_client=redis,
            buffer_index_key=RedisKeys.output_buffer_index(CHANNEL_ID, fmt),
            buffer_chunk_prefix=RedisKeys.output_buffer_chunk_prefix(CHANNEL_ID, fmt),
            chunk_timestamps_key=RedisKeys.output_chunk_timestamps(CHANNEL_ID, fmt),
            discontinuities_key=RedisKeys.output_buffer_discontinuities(
                CHANNEL_ID, fmt
            ),
            chunk_media_scores_key=RedisKeys.output_chunk_media_scores(
                CHANNEL_ID, fmt
            ),
        )
        buf.target_chunk_size = TS_PACKET_SIZE * 8
        buf.media_score_from_chunk_end = True
        buf.enable_media_index(True)

        pat = make_pat()
        pmt = make_pmt([(H264, VIDEO_PID), (AAC, PMT_AUDIO)])

        def scored(pts_end):
            body = (
                pat
                + pmt
                + make_filler() * 2
                + make_pes_pts(VIDEO_PID, pts_end - 0.5)
                + make_pes_pts(VIDEO_PID, pts_end - 0.2, random_access=True)
                + make_pes_pts(VIDEO_PID, pts_end)
            )
            while len(body) < buf.target_chunk_size:
                body += make_filler()
            return body[: buf.target_chunk_size]

        for pts in (100.0, 102.0, 104.0, 106.0):
            self.assertTrue(buf.add_chunk(scored(pts)))

        # Same path as a second TS client on the profile ring: scores exist,
        # owner map does not.
        last_consumed, target = buf.resolve_join_position(2.0)
        self.assertAlmostEqual(target, 104.0, places=3)
        indexed, _new = buf.get_optimized_client_data_indexed(last_consumed)
        chunk_index, chunk = indexed[0]
        self.assertEqual(buf.chunk_media_map(chunk_index), ())
        trimmed = buf.prepare_first_join_chunk(chunk_index, chunk, target)
        self.assertLess(len(trimmed), len(chunk))
        from apps.proxy.live_proxy.join_trim import scan_chunk_media_entries

        entries = scan_chunk_media_entries(trimmed)
        self.assertTrue(entries)
        self.assertTrue(entries[0][2])
        self.assertAlmostEqual(entries[0][1], 103.8, places=2)

    def test_chunk_end_scoring_off_leaves_unsampled_chunks_unscored(self):
        """Input ingest must not invent end scores when the hook skipped a stretch."""
        buf, redis = self._buffer(media_index=True)
        buf.on_packets_received = None
        buf.media_score_from_chunk_end = False
        self.assertTrue(buf.add_chunk(_chunk_with_pts(5.0)))
        self.assertNotIn("1", redis.zsets.get(buf.chunk_media_scores_key, {}))

    def test_media_scores_stay_monotonic_across_pts_wrap(self):
        """Raw PTS wrapping must not send a join back to the oldest chunk."""
        buf, redis = self._buffer(media_index=True)
        before = PTS_WRAP_SECONDS - 2.0
        after = 2.0
        self._write_pts_chunks(buf, [before - 2.0, before, after, after + 2.0])
        scores = redis.zsets[buf.chunk_media_scores_key]
        ordered = [scores[str(i)] for i in range(1, 5)]
        self.assertEqual(ordered, sorted(ordered))
        self.assertGreater(scores["3"], scores["2"])
        # 2s behind the unwrapped head should land near the post-wrap chunk,
        # not at the start of the retained window.
        last_consumed, target = buf.resolve_join_position(2.0)
        self.assertEqual(last_consumed, 2)
        self.assertAlmostEqual(target, scores["4"] - 2.0, places=5)

    def test_resolve_join_preserves_fractional_target(self):
        buf, _redis = self._buffer(media_index=True)
        self._write_pts_chunks(buf, [100.25, 102.25, 104.25, 106.25])
        _last, target = buf.resolve_join_position(2.0)
        self.assertAlmostEqual(target, 104.25, places=5)

    def test_profile_end_scores_lock_to_first_clock_pid(self):
        """Output-profile scoring stays on one PID across chunks."""
        buf, redis = self._buffer(media_index=False)
        buf.media_score_from_chunk_end = True
        buf.enable_media_index(True)
        # First chunk ends on audio; later chunks put video newer in the tail.
        first = (
            make_filler() * 2
            + make_pes_pts(VIDEO_PID, 10.0)
            + make_pes_pts(0x101, 10.5)
        )
        second = (
            make_filler() * 2
            + make_pes_pts(0x101, 11.0)
            + make_pes_pts(VIDEO_PID, 12.0)
        )
        self.assertTrue(buf.add_chunk(first))
        self.assertTrue(buf.add_chunk(second))
        scores = redis.zsets[buf.chunk_media_scores_key]
        # Locked to audio (newest on first chunk), so chunk 2 uses audio 11.0
        # rather than the newer video PTS.
        self.assertAlmostEqual(scores["1"], 10.5, places=3)
        self.assertAlmostEqual(scores["2"], 11.0, places=3)
        self.assertEqual(buf._media_score_pid, 0x101)


class CoalesceMediaMapTests(SimpleTestCase):
    """Ingest pass-through: (offset, media, is_rap) triples follow bytes into their chunk."""

    def setUp(self):
        patcher = patch(SETTING, return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _buffer(self, packets_per_chunk=4):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.target_chunk_size = TS_PACKET_SIZE * packets_per_chunk
        buf.enable_media_index(True)
        buf.on_packets_received = _ingest_hook(buf)
        return buf, redis

    def test_sample_map_offsets_inside_the_chunk(self):
        buf, redis = self._buffer()
        for pkt in (
            make_filler(),
            make_pes_pts(VIDEO_PID, 10.0),
            make_filler(),
            make_pes_pts(VIDEO_PID, 11.0),
        ):
            self.assertTrue(buf.add_chunk(pkt))
        self.assertEqual(buf.index, 1)
        self.assertAlmostEqual(
            redis.zsets[buf.chunk_media_scores_key]["1"], 11.0, places=3
        )
        samples = buf.chunk_media_map(1)
        self.assertEqual(
            [off for off, _media, _rap in samples],
            [TS_PACKET_SIZE, 3 * TS_PACKET_SIZE],
        )
        self.assertAlmostEqual(samples[0][1], 10.0, places=3)
        self.assertAlmostEqual(samples[1][1], 11.0, places=3)
        self.assertFalse(samples[0][2])
        self.assertFalse(samples[1][2])
        self.assertEqual(buf._coalesce_media_map, [])

    def test_sample_past_a_chunk_boundary_is_rebased_into_the_next_chunk(self):
        buf, redis = self._buffer()
        # One 6-packet read: the clock packet is index 4, so it belongs to the
        # next chunk even though the read completed chunk 1.
        read = make_filler() * 4 + make_pes_pts(VIDEO_PID, 7.0) + make_filler()
        self.assertTrue(buf.add_chunk(read))
        self.assertEqual(buf.index, 1)
        self.assertNotIn("1", redis.zsets.get(buf.chunk_media_scores_key, {}))
        self.assertEqual(buf._coalesce_media_map, [(0, 7.0, False)])
        # Two more packets finish chunk 2, which starts at that clock packet.
        self.assertTrue(buf.add_chunk(make_filler() * 2))
        self.assertEqual(buf.index, 2)
        self.assertAlmostEqual(
            redis.zsets[buf.chunk_media_scores_key]["2"], 7.0, places=3
        )
        self.assertEqual(buf.chunk_media_map(2), ((0, 7.0, False),))

    def test_failed_write_drops_that_chunks_samples(self):
        """The bytes are gone after a failed write, so their samples must go too."""
        buf, redis = self._buffer()
        real_pipeline = redis.pipeline
        attempts = {"n": 0}

        def flaky_pipeline(transaction=False):
            pipe = real_pipeline(transaction)
            if attempts["n"] == 0:
                attempts["n"] += 1

                def boom():
                    raise RuntimeError("redis blip")

                pipe.execute = boom
            return pipe

        redis.pipeline = flaky_pipeline
        self.assertTrue(buf.add_chunk(_chunk_with_pts(10.0)))
        self.assertEqual(buf.index, 0)
        self.assertEqual(buf._coalesce_media_map, [])
        self.assertTrue(buf.add_chunk(_chunk_with_pts(20.0)))
        self.assertEqual(buf.index, 1)
        self.assertAlmostEqual(
            redis.zsets[buf.chunk_media_scores_key]["1"], 20.0, places=3
        )
        self.assertEqual(buf.chunk_media_map(1), ((3 * TS_PACKET_SIZE, 20.0, False),))

    def test_note_dropped_when_failover_already_flushed_the_read(self):
        buf, _redis = self._buffer()
        self.assertTrue(buf.add_chunk(make_pes_pts(VIDEO_PID, 1.0)))
        with buf.lock:  # failover flushed or cleared before the note landed
            buf._write_buffer = bytearray()
            buf._coalesce_media_map = []
        buf.note_media_clock(9.0, append_len=TS_PACKET_SIZE, offset_in_append=0)
        self.assertEqual(buf._coalesce_media_map, [])

    def test_note_ignored_when_index_disabled(self):
        buf, _redis = self._buffer()
        buf.enable_media_index(False)
        buf.note_media_clock(9.0, append_len=TS_PACKET_SIZE)
        self.assertEqual(buf._coalesce_media_map, [])

    def test_chunk_maps_are_bounded_to_recent_chunks(self):
        buf, _redis = self._buffer()
        total = buf.MEDIA_MAP_KEEP_CHUNKS + 10
        for i in range(1, total + 1):
            self.assertTrue(buf.add_chunk(_chunk_with_pts(float(i))))
        self.assertEqual(buf.index, total)
        self.assertEqual(len(buf._chunk_media_maps), buf.MEDIA_MAP_KEEP_CHUNKS)
        self.assertEqual(buf.chunk_media_map(1), ())
        self.assertNotEqual(buf.chunk_media_map(total), ())
        self.assertNotEqual(buf.chunk_media_map(total - buf.MEDIA_MAP_KEEP_CHUNKS + 1), ())


class OutputBufferBehindHeadTests(SimpleTestCase):
    def test_fmp4_join_uses_published_media_score(self):
        redis = _FakeRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt="fmp4")
        for end in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0):
            self.assertTrue(buf.put_chunk(b"frag-%s" % str(end).encode(), score=end))
        # 3s behind head (6) -> fragment scored 3 (index 3); last-consumed = 2
        self.assertEqual(buf.find_chunk_index_behind(3.0), 2)
        # Reader object index must not override the published head.
        buf.index = 1
        self.assertEqual(buf.find_chunk_index_behind(3.0), 2)

    def test_fmp4_media_scores_pruned_one_member_per_chunk(self):
        redis = _FakeRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt="fmp4")
        buf.chunk_ttl = 1  # keep window is 64
        for i in range(1, 81):
            self.assertTrue(buf.put_chunk(b"frag", score=float(i)))
        scores = redis.zsets[buf.chunk_timestamps_key]
        self.assertNotIn("15", scores)
        self.assertIn("16", scores)
        self.assertEqual(len(scores), 65)

    def test_hls_wall_scores_still_prune_by_age(self):
        redis = _FakeRedis()
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt="hls")
        buf.chunk_ttl = 60
        now = 1_700_000_100.0
        stamps = iter((now - 120, now))
        real_time = output_buffer.time.time
        output_buffer.time.time = lambda: next(stamps)
        try:
            self.assertTrue(buf.put_chunk(b"old"))
            self.assertTrue(buf.put_chunk(b"new"))
        finally:
            output_buffer.time.time = real_time
        scores = redis.zsets[buf.chunk_timestamps_key]
        self.assertNotIn("1", scores)
        self.assertIn("2", scores)
