"""Experimental stream-time channel init buffer readiness."""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.chunk_time_lookup import media_score_depth_seconds
from apps.proxy.live_proxy.constants import ChannelMetadataField, TS_PACKET_SIZE
from apps.proxy.live_proxy.init_buffer import (
    channel_init_buffer_ready,
    clear_depth_error_log,
    effective_init_min_buffer_seconds,
    evaluate_init_buffer_ready,
)
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.tests.test_buffer_discontinuity import _FakeRedis
from apps.proxy.live_proxy.tests.test_chunk_media_scores import (
    CHANNEL_ID,
    _chunk_with_pts,
    _ingest_hook,
)


class EffectiveInitMinTests(SimpleTestCase):
    def test_clamps_to_behind_when_behind_positive(self):
        self.assertEqual(effective_init_min_buffer_seconds(6, 10), 6.0)
        self.assertEqual(effective_init_min_buffer_seconds(6, 2), 2.0)

    def test_behind_zero_keeps_configured_min(self):
        self.assertEqual(effective_init_min_buffer_seconds(0, 2), 2.0)


class EvaluateInitBufferReadyTests(SimpleTestCase):
    def test_non_experimental_uses_chunk_count(self):
        ready, reached, status = evaluate_init_buffer_ready(
            experimental=False,
            buffer_index=3,
            media_depth=None,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=None,
            chunks_needed=4,
            now=100.0,
        )
        self.assertFalse(ready)
        self.assertIsNone(reached)
        self.assertEqual(status.progress_label(), "3/4 chunks")

        ready, reached, status = evaluate_init_buffer_ready(
            experimental=False,
            buffer_index=4,
            media_depth=None,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=None,
            chunks_needed=4,
            now=100.0,
        )
        self.assertTrue(ready)
        self.assertIsNone(reached)
        self.assertEqual(status.progress_label(), "4/4 chunks")

    def test_non_experimental_requires_chunks_needed(self):
        """The function reads no settings, so the chunk gate must be passed in."""
        with self.assertRaises(ValueError):
            evaluate_init_buffer_ready(
                experimental=False,
                buffer_index=4,
                media_depth=None,
                behind_seconds=6,
                min_seconds=2,
                max_wait_seconds=3,
                min_reached_at=None,
                now=100.0,
            )

    def test_experimental_ignores_chunks_needed(self):
        ready, _reached, _status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=99,
            media_depth=1.0,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=None,
            chunks_needed=1,
            now=100.0,
        )
        self.assertFalse(ready)

    def test_experimental_waits_without_scores(self):
        ready, reached, status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=10,
            media_depth=None,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=None,
            now=100.0,
        )
        self.assertFalse(ready)
        self.assertIsNone(reached)
        self.assertEqual(status.progress_label(), "no media scores yet")

    def test_experimental_ready_when_full_behind_met(self):
        ready, reached, status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=10,
            media_depth=6.0,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=None,
            now=100.0,
        )
        self.assertTrue(ready)
        self.assertIsNone(reached)
        self.assertEqual(status.progress_label(), "6.0/6.0s stream")

    def test_experimental_below_min_never_ready(self):
        ready, reached, status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=10,
            media_depth=1.5,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=50.0,
            now=100.0,
        )
        self.assertFalse(ready)
        self.assertIsNone(reached)
        self.assertIn("min 2.0s", status.progress_label())

    def test_experimental_min_met_starts_max_wait(self):
        ready, reached, status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=10,
            media_depth=2.5,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=None,
            now=100.0,
        )
        self.assertFalse(ready)
        self.assertEqual(reached, 100.0)
        self.assertIn("max-wait 3.0s left", status.progress_label())

        ready, reached, status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=10,
            media_depth=2.5,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=100.0,
            now=102.0,
        )
        self.assertFalse(ready)
        self.assertEqual(reached, 100.0)
        self.assertIn("max-wait 1.0s left", status.progress_label())

        ready, reached, status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=10,
            media_depth=2.5,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=100.0,
            now=103.0,
        )
        self.assertTrue(ready)
        self.assertEqual(reached, 100.0)

    def test_experimental_behind_zero_ready_at_min(self):
        ready, reached, status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=10,
            media_depth=2.0,
            behind_seconds=0,
            min_seconds=2,
            max_wait_seconds=3,
            min_reached_at=None,
            now=100.0,
        )
        self.assertTrue(ready)
        self.assertIsNone(reached)
        self.assertEqual(status.progress_label(), "2.0/2.0s stream")

    def test_max_wait_zero_promotes_at_min(self):
        ready, reached, _status = evaluate_init_buffer_ready(
            experimental=True,
            buffer_index=10,
            media_depth=2.0,
            behind_seconds=6,
            min_seconds=2,
            max_wait_seconds=0,
            min_reached_at=None,
            now=100.0,
        )
        self.assertTrue(ready)
        self.assertEqual(reached, 100.0)


def _buffer_depth(buf, head_index=None):
    """Depth the way channel init reads it: the shared helper over the buffer's keys."""
    head = buf.index if head_index is None else head_index
    return media_score_depth_seconds(
        buf.redis_client,
        buf.chunk_media_scores_key,
        buf.discontinuities_key,
        head,
        starts_key=buf.chunk_media_starts_key,
    )


class MediaBufferDepthTests(SimpleTestCase):
    """What the ingest buffer writes, read back through the init depth helper."""

    def _buffer(self):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        buf.enable_media_index(True)
        buf.on_packets_received = _ingest_hook(buf)
        return buf, redis

    def test_depth_none_without_media_index(self):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        self.assertTrue(buf.add_chunk(_chunk_with_pts(10.0)))
        self.assertEqual(buf.index, 1)
        self.assertIsNone(_buffer_depth(buf))

    def test_depth_zero_when_single_chunk_start_matches_end(self):
        """One published chunk whose start and end PTS are the same reads 0s deep."""
        buf, _redis = self._buffer()
        self.assertTrue(buf.add_chunk(_chunk_with_pts(10.0)))
        self.assertAlmostEqual(_buffer_depth(buf), 0.0, places=3)

    def test_one_published_chunk_counts_its_own_span(self):
        buf, redis = self._buffer()
        buf.target_chunk_size = TS_PACKET_SIZE * 64
        self.assertTrue(buf.add_chunk(_chunk_with_pts(100.0, packets=1)))
        self.assertEqual(buf.index, 0)
        self.assertTrue(buf.add_chunk(_chunk_with_pts(106.0, packets=1)))
        self.assertEqual(buf.index, 1)
        self.assertAlmostEqual(_buffer_depth(buf), 6.0, places=3)
        self.assertAlmostEqual(
            redis.zsets[buf.chunk_media_starts_key]["1"], 100.0, places=3
        )
        self.assertAlmostEqual(
            redis.zsets[buf.chunk_media_scores_key]["1"], 106.0, places=3
        )

    def test_depth_spans_end_scores(self):
        buf, _redis = self._buffer()
        for pts in (100.0, 102.0, 104.0, 106.0):
            self.assertTrue(buf.add_chunk(_chunk_with_pts(pts)))
        self.assertAlmostEqual(_buffer_depth(buf), 6.0, places=3)

    def test_depth_follows_the_given_head_index(self):
        buf, _redis = self._buffer()
        for pts in (100.0, 102.0, 104.0):
            self.assertTrue(buf.add_chunk(_chunk_with_pts(pts)))
        self.assertAlmostEqual(_buffer_depth(buf, head_index=3), 4.0, places=3)
        self.assertAlmostEqual(_buffer_depth(buf, head_index=2), 2.0, places=3)


class MediaScoreDepthEraTests(SimpleTestCase):
    def test_depth_uses_lowest_chunk_index_not_lowest_pts(self):
        """Zset order is by score; oldest buffer depth follows lowest index."""
        redis = _FakeRedis()
        scores_key = RedisKeys.chunk_media_scores(CHANNEL_ID)
        starts_key = RedisKeys.chunk_media_starts(CHANNEL_ID)
        redis.zadd(starts_key, {"2": 50.0, "1": 100.0})
        redis.zadd(scores_key, {"1": 102.0, "2": 106.0})
        redis.set(RedisKeys.buffer_index(CHANNEL_ID), "2")
        depth = media_score_depth_seconds(
            redis, scores_key, "", 2, starts_key=starts_key
        )
        self.assertAlmostEqual(depth, 6.0, places=3)


class ChannelInitBufferReadyTests(SimpleTestCase):
    def _redis_with_scores(self, head, scores):
        """Scores are chunk index -> end media time. No local stream manager."""
        redis = _FakeRedis()
        redis.set(RedisKeys.buffer_index(CHANNEL_ID), str(head))
        if scores:
            redis.zadd(
                RedisKeys.chunk_media_scores(CHANNEL_ID),
                {str(idx): float(score) for idx, score in scores.items()},
            )
        return redis

    def _patches(self):
        return (
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.experimental_ingest_buffer",
                return_value=True,
            ),
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.new_client_behind_seconds",
                return_value=6,
            ),
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.init_min_buffer_seconds",
                return_value=2,
            ),
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.init_buffer_max_wait_seconds",
                return_value=3,
            ),
        )

    def test_promotes_from_redis_scores_without_stream_manager(self):
        # 6s of scored media at the head. A non-owner worker has no buffer object.
        redis = self._redis_with_scores(4, {1: 100.0, 2: 102.0, 3: 104.0, 4: 106.0})
        patches = self._patches()
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        ready, status = channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=50.0
        )
        self.assertTrue(ready)
        self.assertEqual(status.progress_label(), "6.0/6.0s stream")

    def test_max_wait_clock_is_shared_in_redis(self):
        redis = self._redis_with_scores(3, {1: 100.0, 2: 101.2, 3: 102.5})
        patches = self._patches()
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        ready, status = channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=50.0
        )
        self.assertFalse(ready)
        self.assertIn("2.5/6.0s stream", status.progress_label())
        clock = redis.hget(
            RedisKeys.channel_metadata(CHANNEL_ID),
            ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT,
        )
        self.assertEqual(clock, "50.0")

        # A later call on any worker continues the same clock.
        ready, status = channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=53.0
        )
        self.assertTrue(ready)
        self.assertEqual(
            redis.hget(
                RedisKeys.channel_metadata(CHANNEL_ID),
                ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT,
            ),
            "50.0",
        )

    def test_unchanged_max_wait_clock_skips_redis_write(self):
        redis = self._redis_with_scores(3, {1: 100.0, 2: 101.2, 3: 102.5})
        patches = self._patches()
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=50.0
        )
        writes = {"hset": 0, "hdel": 0}
        original_hset = redis.hset
        original_hdel = redis.hdel

        def counting_hset(key, field, value):
            writes["hset"] += 1
            return original_hset(key, field, value)

        def counting_hdel(key, *fields):
            writes["hdel"] += 1
            return original_hdel(key, *fields)

        redis.hset = counting_hset
        redis.hdel = counting_hdel

        # Same clock already stored: no rewrite while still waiting.
        ready, _status = channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=51.0
        )
        self.assertFalse(ready)
        self.assertEqual(writes["hset"], 0)
        self.assertEqual(writes["hdel"], 0)

    def test_depth_read_failure_keeps_max_wait_clock(self):
        """A Redis blip must not restart a wait that already started."""
        redis = self._redis_with_scores(3, {1: 100.0, 2: 101.2, 3: 102.5})
        for item in self._patches():
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(clear_depth_error_log, CHANNEL_ID)

        channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=50.0
        )
        metadata = RedisKeys.channel_metadata(CHANNEL_ID)
        clock_field = ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT
        self.assertEqual(redis.hget(metadata, clock_field), "50.0")

        with patch(
            "apps.proxy.live_proxy.init_buffer.media_score_depth_seconds",
            side_effect=RuntimeError("redis down"),
        ):
            ready, _status = channel_init_buffer_ready(
                CHANNEL_ID, redis, stream_manager=None, now=53.0
            )
        self.assertFalse(ready)
        self.assertEqual(redis.hget(metadata, clock_field), "50.0")

        ready, _status = channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=53.0
        )
        self.assertTrue(ready)
        self.assertEqual(redis.hget(metadata, clock_field), "50.0")

    def test_clock_read_failure_does_not_rewrite_anchor(self):
        redis = self._redis_with_scores(3, {1: 100.0, 2: 101.2, 3: 102.5})
        for item in self._patches():
            item.start()
            self.addCleanup(item.stop)

        channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=50.0
        )
        metadata = RedisKeys.channel_metadata(CHANNEL_ID)
        clock_field = ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT
        original_hget = redis.hget

        def flaky_hget(key, field):
            if field == clock_field:
                raise RuntimeError("redis down")
            return original_hget(key, field)

        redis.hget = flaky_hget
        ready, _status = channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=53.0
        )
        redis.hget = original_hget
        self.assertFalse(ready)
        self.assertEqual(redis.hget(metadata, clock_field), "50.0")

    def test_missing_scores_clear_max_wait_clock(self):
        """An empty timeline drops the anchor so the next fill starts clean."""
        redis = self._redis_with_scores(3, {1: 100.0, 2: 101.2, 3: 102.5})
        for item in self._patches():
            item.start()
            self.addCleanup(item.stop)

        channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=50.0
        )
        metadata = RedisKeys.channel_metadata(CHANNEL_ID)
        clock_field = ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT
        self.assertEqual(redis.hget(metadata, clock_field), "50.0")

        redis.delete(
            RedisKeys.chunk_media_scores(CHANNEL_ID),
            RedisKeys.chunk_media_starts(CHANNEL_ID),
        )
        ready, _status = channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=52.0
        )
        self.assertFalse(ready)
        self.assertIsNone(redis.hget(metadata, clock_field))

    def test_no_new_client_buffer_stores_no_max_wait_clock(self):
        """With nothing to wait for beyond the minimum, no anchor is written."""
        redis = self._redis_with_scores(2, {1: 100.0, 2: 102.5})
        for item in self._patches():
            item.start()
            self.addCleanup(item.stop)
        behind = patch(
            "apps.proxy.live_proxy.init_buffer.ConfigHelper.new_client_behind_seconds",
            return_value=0,
        )
        behind.start()
        self.addCleanup(behind.stop)

        ready, _status = channel_init_buffer_ready(
            CHANNEL_ID, redis, stream_manager=None, now=50.0
        )
        self.assertTrue(ready)
        self.assertIsNone(
            redis.hget(
                RedisKeys.channel_metadata(CHANNEL_ID),
                ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT,
            )
        )

    def test_frozen_metadata_flag_overrides_live_setting(self):
        # Live setting off, but this channel started with experimental on.
        redis = self._redis_with_scores(4, {1: 100.0, 2: 102.0, 3: 104.0, 4: 106.0})
        redis.hset(
            RedisKeys.channel_metadata(CHANNEL_ID),
            ChannelMetadataField.EXPERIMENTAL_INGEST_BUFFER,
            "1",
        )
        with (
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.experimental_ingest_buffer",
                return_value=False,
            ),
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.new_client_behind_seconds",
                return_value=6,
            ),
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.init_min_buffer_seconds",
                return_value=2,
            ),
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.init_buffer_max_wait_seconds",
                return_value=3,
            ),
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.initial_behind_chunks",
                return_value=4,
            ),
        ):
            ready, status = channel_init_buffer_ready(
                CHANNEL_ID, redis, stream_manager=None, now=50.0
            )
        self.assertTrue(ready)
        self.assertTrue(status.experimental)
        self.assertEqual(status.progress_label(), "6.0/6.0s stream")

    def test_frozen_metadata_off_keeps_chunk_gate(self):
        # Live setting on, but this channel started with experimental off.
        redis = self._redis_with_scores(4, {1: 100.0, 2: 102.0, 3: 104.0, 4: 106.0})
        redis.hset(
            RedisKeys.channel_metadata(CHANNEL_ID),
            ChannelMetadataField.EXPERIMENTAL_INGEST_BUFFER,
            "0",
        )
        with (
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.experimental_ingest_buffer",
                return_value=True,
            ),
            patch(
                "apps.proxy.live_proxy.init_buffer.ConfigHelper.initial_behind_chunks",
                return_value=4,
            ),
        ):
            ready, status = channel_init_buffer_ready(
                CHANNEL_ID, redis, stream_manager=None, now=50.0
            )
        self.assertTrue(ready)
        self.assertFalse(status.experimental)
        self.assertEqual(status.progress_label(), "4/4 chunks")


class ClearDepthErrorLogTests(SimpleTestCase):
    def test_clear_one_channel(self):
        from apps.proxy.live_proxy import init_buffer as ib

        ib._depth_error_logged.add("chan-a")
        ib._depth_error_logged.add("chan-b")
        clear_depth_error_log("chan-a")
        self.assertNotIn("chan-a", ib._depth_error_logged)
        self.assertIn("chan-b", ib._depth_error_logged)
        clear_depth_error_log()
        self.assertEqual(ib._depth_error_logged, set())
