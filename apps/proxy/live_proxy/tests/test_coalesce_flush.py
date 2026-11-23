"""Time-capped Redis coalesce flush for low-bitrate / radio feeds."""

import time

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.tests.test_buffer_discontinuity import _FakeRedis, _pkt
from apps.proxy.live_proxy.tests.test_chunk_media_scores import (
    CHANNEL_ID,
    _chunk_with_pts,
    _ingest_hook,
)


class CoalesceTimeFlushTests(SimpleTestCase):
    def _buffer(self, *, media_index=False, target_packets=64):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.target_chunk_size = TS_PACKET_SIZE * target_packets
        if media_index:
            buf.enable_media_index(True)
            buf.on_packets_received = _ingest_hook(buf)
        return buf, redis

    def test_wall_clock_flushes_undersized_coalesce(self):
        """Non-experimental: age alone publishes under target size."""
        buf, redis = self._buffer(media_index=False, target_packets=64)
        self.assertTrue(buf.add_chunk(_pkt(256, 0) + _pkt(256, 1)))
        self.assertEqual(buf.index, 0)
        self.assertGreater(len(buf._write_buffer), 0)
        self.assertIsNotNone(buf._coalesce_started_at)

        buf._coalesce_started_at -= buf.MAX_COALESCE_SECONDS + 0.1
        self.assertTrue(buf.add_chunk(_pkt(256, 2)))
        self.assertEqual(buf.index, 1)
        self.assertEqual(len(buf._write_buffer), 0)
        self.assertIsNone(buf._coalesce_started_at)
        self.assertIn(f"{buf.buffer_prefix}1", redis.kv)

    def test_pts_span_flushes_undersized_coalesce(self):
        """Experimental: media span across samples trips the cap before size."""
        buf, redis = self._buffer(media_index=True, target_packets=64)
        # One packet per add so each note lands in the coalesce map.
        self.assertTrue(buf.add_chunk(_chunk_with_pts(100.0, packets=1)))
        self.assertEqual(buf.index, 0)
        self.assertTrue(buf.add_chunk(_chunk_with_pts(103.0, packets=1)))
        self.assertEqual(buf.index, 0)

        self.assertTrue(buf.add_chunk(_chunk_with_pts(106.5, packets=1)))
        self.assertEqual(buf.index, 1)
        self.assertEqual(len(buf._write_buffer), 0)
        scores = redis.zsets[buf.chunk_media_scores_key]
        self.assertIn("1", scores)
        self.assertAlmostEqual(scores["1"], 106.5, places=3)

    def test_size_limit_still_wins_before_time_cap(self):
        """High bitrate path: full target flush is unchanged."""
        buf, redis = self._buffer(media_index=False, target_packets=4)
        body = _pkt(256, 0) + _pkt(256, 1) + _pkt(256, 2) + _pkt(256, 3)
        self.assertEqual(len(body), buf.target_chunk_size)
        self.assertTrue(buf.add_chunk(body))
        self.assertEqual(buf.index, 1)
        self.assertEqual(len(buf._write_buffer), 0)
        self.assertIsNone(buf._coalesce_started_at)

    def test_remainder_after_full_flush_gets_a_fresh_time_anchor(self):
        """A full chunk leaving a remainder must restart the cap for that remainder.

        Otherwise a steady high-bitrate feed (which never empties the buffer
        exactly) would publish an undersized chunk every cap interval.
        """
        buf, _redis = self._buffer(media_index=False, target_packets=4)
        self.assertTrue(buf.add_chunk(_pkt(256, 0)))
        buf._coalesce_started_at -= buf.MAX_COALESCE_SECONDS + 1.0

        body = _pkt(256, 1) + _pkt(256, 2) + _pkt(256, 3) + _pkt(256, 4)
        self.assertTrue(buf.add_chunk(body))
        self.assertEqual(buf.index, 1)
        self.assertEqual(len(buf._write_buffer), TS_PACKET_SIZE)
        self.assertLess(time.time() - buf._coalesce_started_at, 1.0)

        buf._coalesce_started_at -= buf.MAX_COALESCE_SECONDS + 0.1
        self.assertTrue(buf.add_chunk(_pkt(256, 5)))
        self.assertEqual(buf.index, 2)
        self.assertEqual(len(buf._write_buffer), 0)
        self.assertIsNone(buf._coalesce_started_at)

    def test_remainder_anchor_with_ingest_hook(self):
        """Same re-anchor on the experimental path, where the flush runs after the hook."""
        buf, _redis = self._buffer(media_index=True, target_packets=4)
        self.assertTrue(buf.add_chunk(_chunk_with_pts(100.0, packets=1)))
        buf._coalesce_started_at -= buf.MAX_COALESCE_SECONDS + 1.0

        self.assertTrue(buf.add_chunk(_chunk_with_pts(100.5, packets=4)))
        self.assertEqual(buf.index, 1)
        self.assertEqual(len(buf._write_buffer), TS_PACKET_SIZE)
        self.assertLess(time.time() - buf._coalesce_started_at, 1.0)

    def test_failed_full_write_still_reanchors_remainder(self):
        """Bytes leave the buffer even when Redis rejects the chunk."""
        buf, _redis = self._buffer(media_index=False, target_packets=4)
        self.assertTrue(buf.add_chunk(_pkt(256, 0)))
        buf._coalesce_started_at -= buf.MAX_COALESCE_SECONDS + 1.0
        buf._write_chunk_unlocked = lambda chunk_data: False

        body = _pkt(256, 1) + _pkt(256, 2) + _pkt(256, 3) + _pkt(256, 4)
        self.assertTrue(buf.add_chunk(body))
        self.assertEqual(buf.index, 0)
        self.assertEqual(len(buf._write_buffer), TS_PACKET_SIZE)
        self.assertLess(time.time() - buf._coalesce_started_at, 1.0)

    def test_under_cap_keeps_coalescing(self):
        buf, _redis = self._buffer(media_index=False, target_packets=64)
        self.assertTrue(buf.add_chunk(_pkt(256, 0)))
        started = buf._coalesce_started_at
        self.assertIsNotNone(started)
        buf._coalesce_started_at = started - 1.0
        self.assertTrue(buf.add_chunk(_pkt(256, 1)))
        self.assertEqual(buf.index, 0)
        self.assertGreater(len(buf._write_buffer), 0)
