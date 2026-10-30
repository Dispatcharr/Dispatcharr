"""Tests for StreamBuffer.mark_discontinuity flush + sidecar + in-band stamp."""

from unittest.mock import MagicMock

from django.test import TestCase

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.input.ts_discontinuity import packet_has_discontinuity_indicator
from apps.proxy.live_proxy.redis_keys import RedisKeys


CHANNEL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class _FakeRedis:
    def __init__(self):
        self.kv = {}
        self.zsets = {}
        self.ttls = {}
        self._index = 0

    def incr(self, key):
        self._index += 1
        self.kv[key] = str(self._index)
        return self._index

    def set(self, key, value):
        if isinstance(value, (bytes, bytearray)):
            self.kv[key] = bytes(value)
        else:
            self.kv[key] = str(value)
        return True

    def get(self, key):
        return self.kv.get(key)

    def setex(self, key, ttl, value):
        self.kv[key] = value
        self.ttls[key] = ttl

    def expire(self, key, ttl):
        self.ttls[key] = ttl
        return 1

    def zadd(self, key, mapping):
        z = self.zsets.setdefault(key, {})
        for member, score in mapping.items():
            z[str(member)] = float(score)
        return len(mapping)

    def zremrangebyscore(self, key, min_s, max_s):
        z = self.zsets.get(key, {})
        lo = float("-inf") if min_s == "-inf" else float(min_s)
        hi = float("inf") if max_s == "+inf" else float(max_s)
        drop = [m for m, s in z.items() if lo <= s <= hi]
        for m in drop:
            del z[m]
        return len(drop)

    def zrangebyscore(self, key, min_s, max_s):
        z = self.zsets.get(key, {})
        lo = float(min_s)
        hi = float(max_s)
        return [m for m, s in sorted(z.items(), key=lambda kv: kv[1]) if lo <= s <= hi]

    def pipeline(self, transaction=False):
        return _FakePipeline(self)

    def register_script(self, *_a, **_k):
        return None


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def setex(self, *a):
        self.ops.append(("setex", a))
        return self

    def set(self, *a):
        self.ops.append(("set", a))
        return self

    def get(self, *a):
        self.ops.append(("get", a))
        return self

    def zadd(self, *a):
        self.ops.append(("zadd", a))
        return self

    def zremrangebyscore(self, *a):
        self.ops.append(("zremrangebyscore", a))
        return self

    def expire(self, *a):
        self.ops.append(("expire", a))
        return self

    def execute(self):
        results = []
        for op, args in self.ops:
            results.append(getattr(self.redis, op)(*args))
        return results


def _pkt(pid, cc=0):
    p = bytearray(TS_PACKET_SIZE)
    p[0] = 0x47
    p[1] = (pid >> 8) & 0x1F
    p[2] = pid & 0xFF
    p[3] = 0x10 | (cc & 0x0F)  # payload only
    return bytes(p)


class MarkDiscontinuityTests(TestCase):
    def _buffer(self):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        return buf, redis

    def test_flush_then_stamp_first_new_packets(self):
        buf, redis = self._buffer()
        # Under-sized write buffer of old-source packets (3 packets).
        old = _pkt(0, 0) + _pkt(256, 0) + _pkt(256, 1)
        buf._write_buffer = bytearray(old)

        disc_index = buf.mark_discontinuity()
        self.assertEqual(disc_index, 2)  # after flushed old chunk 1
        self.assertEqual(buf.index, 1)
        self.assertIn("2", redis.zsets[buf.discontinuities_key])
        # Old flush must NOT be stamped (stamp arms after flush).
        old_chunk = redis.kv[f"{buf.buffer_prefix}1"]
        self.assertFalse(packet_has_discontinuity_indicator(old_chunk[0:188]))

        # New source: first packet per PID gets the indicator.
        new = _pkt(0, 5) + _pkt(4096, 0) + _pkt(256, 7) + _pkt(256, 8)
        buf.add_chunk(new)
        self.assertEqual(buf.index, 2)
        new_chunk = redis.kv[f"{buf.buffer_prefix}2"]
        self.assertTrue(packet_has_discontinuity_indicator(new_chunk[0:188]))     # PAT
        self.assertTrue(packet_has_discontinuity_indicator(new_chunk[188:376]))   # PMT
        self.assertTrue(packet_has_discontinuity_indicator(new_chunk[376:564]))   # video first
        self.assertFalse(packet_has_discontinuity_indicator(new_chunk[564:752]))  # video second
        self.assertEqual(buf.discontinuities_in_range(0, 2), [2])
        # After the first post-mark chunk, stamping is done.
        self.assertFalse(buf._disc_stamp_active)

    def test_discontinuities_in_range_bounds(self):
        buf, redis = self._buffer()
        buf.mark_discontinuity()  # empty buffer: records index 1
        self.assertEqual(buf.discontinuities_in_range(0, 1), [1])
        self.assertEqual(buf.discontinuities_in_range(1, 5), [])

    def test_failed_chunk_write_does_not_skip_index(self):
        """A pipeline failure must not burn the next index (no permanent hole)."""
        buf, redis = self._buffer()
        buf.target_chunk_size = TS_PACKET_SIZE
        ok = buf.add_chunk(_pkt(256, 0))
        self.assertTrue(ok)
        self.assertEqual(buf.index, 1)

        # Next write: pipeline.execute raises after nothing durable happened.
        real_pipeline = redis.pipeline

        class BoomPipeline:
            def __init__(self, *a, **k):
                pass

            def setex(self, *a):
                return self

            def set(self, *a):
                return self

            def zadd(self, *a):
                return self

            def zremrangebyscore(self, *a):
                return self

            def expire(self, *a):
                return self

            def execute(self):
                raise RuntimeError("redis blip")

        redis.pipeline = lambda transaction=False: BoomPipeline()
        self.assertFalse(buf._write_chunk_unlocked(_pkt(256, 1)))
        self.assertEqual(buf.index, 1)
        self.assertEqual(redis.kv.get(buf.buffer_index_key), "1")

        redis.pipeline = real_pipeline
        self.assertTrue(buf._write_chunk_unlocked(_pkt(256, 2)))
        self.assertEqual(buf.index, 2)
        self.assertIn(f"{buf.buffer_prefix}2", redis.kv)
        self.assertNotIn(f"{buf.buffer_prefix}3", redis.kv)


class IndexedClientDataTests(TestCase):
    """Indexed reads keep Redis indices, and small chunks fill toward 1MB."""

    def _buffer_with_chunks(self, present, head, size=TS_PACKET_SIZE, size_at=None):
        """Seed ``present`` chunk indices (1-based). ``head`` is the buffer index."""
        redis = _FakeRedis()
        redis.kv[RedisKeys.buffer_index(CHANNEL_ID)] = str(head)
        redis._index = head
        size_at = size_at or {}
        prefix = RedisKeys.buffer_chunk_prefix(CHANNEL_ID)
        for idx in present:
            n = size_at.get(idx, size)
            redis.kv[f"{prefix}{idx}"] = b"\x47" + b"\x00" * (n - 1)
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.index = head
        return buf

    def test_primary_batch_new_index_covers_holes(self):
        # Hole at 3: hits are 1,2,4,5. new_index must still land at 5 so 3 is not re-read.
        buf = self._buffer_with_chunks([1, 2, 4, 5], head=5)
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        self.assertEqual([i for i, _ in indexed], [1, 2, 4, 5])
        self.assertEqual(new_index, 5)

    def test_small_chunks_keep_reading_until_the_target(self):
        # 20KB * 20 = 400KB, under the 1MB target, so reading continues.
        # Three batches is 1.2MB and the fourth batch must stay unread.
        buf = self._buffer_with_chunks(list(range(1, 81)), head=80, size=20 * 1024)
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        self.assertEqual([i for i, _ in indexed], list(range(1, 61)))
        self.assertEqual(new_index, 60)
        chunks, plain_index = buf.get_optimized_client_data(0)
        self.assertEqual(len(chunks), 60)
        self.assertEqual(plain_index, 60)

    def test_batch_already_over_target_does_not_read_further(self):
        # 60KB * 20 = 1.2MB. The extra-read path must not run, which is the
        # steady state for the default ~1MB buffer chunks.
        buf = self._buffer_with_chunks(list(range(1, 41)), head=40, size=60 * 1024)
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        self.assertEqual([i for i, _ in indexed], list(range(1, 21)))
        self.assertEqual(new_index, 20)

    def test_additional_batch_over_the_size_cap_is_left_unread(self):
        # 40KB * 20 = 800KB, then 100KB * 20 would push the read past 2MB.
        small = 40 * 1024
        large = 100 * 1024
        buf = self._buffer_with_chunks(
            list(range(1, 41)),
            head=40,
            size=small,
            size_at={i: large for i in range(21, 41)},
        )
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        self.assertEqual([i for i, _ in indexed], list(range(1, 21)))
        self.assertEqual(new_index, 20)
        # The next read takes the large chunks as its first batch.
        indexed, new_index = buf.get_optimized_client_data_indexed(new_index)
        self.assertEqual([i for i, _ in indexed], list(range(21, 41)))
        self.assertEqual(new_index, 40)

    def test_hole_in_a_later_batch_is_skipped_and_reading_continues(self):
        present = list(range(1, 21)) + list(range(41, 81))
        buf = self._buffer_with_chunks(present, head=80, size=20 * 1024)
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        ids = [i for i, _ in indexed]
        self.assertEqual(ids, present)
        self.assertEqual(new_index, 80)
        self.assertNotIn(25, ids)
        self.assertIn(41, ids)

    def test_failed_additional_read_does_not_skip_ahead(self):
        buf = self._buffer_with_chunks(list(range(1, 41)), head=40)
        real = buf._get_chunks_exact_indexed

        def flaky(start_index, count):
            flaky.calls += 1
            if flaky.calls > 1:
                return None
            return real(start_index, count)

        flaky.calls = 0
        buf._get_chunks_exact_indexed = flaky
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        self.assertEqual([i for i, _ in indexed], list(range(1, 21)))
        self.assertEqual(new_index, 20)

        buf._get_chunks_exact_indexed = real
        indexed, new_index = buf.get_optimized_client_data_indexed(new_index)
        self.assertEqual([i for i, _ in indexed], list(range(21, 41)))
        self.assertEqual(new_index, 40)

    def test_failed_first_read_does_not_skip_ahead(self):
        # A small backlog used to advance past unread chunks when Redis failed,
        # because the empty-list path only held the index when way behind.
        buf = self._buffer_with_chunks([1, 2, 3, 4, 5], head=5)
        buf._get_chunks_exact_indexed = lambda *_a, **_k: None
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        self.assertEqual(indexed, [])
        self.assertEqual(new_index, 0)

        buf = self._buffer_with_chunks([1, 2, 3, 4, 5], head=5)
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        self.assertEqual([i for i, _ in indexed], [1, 2, 3, 4, 5])
        self.assertEqual(new_index, 5)

    def test_tiny_chunks_stop_at_the_per_call_ceiling(self):
        # 188-byte chunks never reach 1MB. Reading must still stop after 100
        # chunks rather than issue a Redis round-trip per 20 until the head.
        buf = self._buffer_with_chunks(list(range(1, 501)), head=500)
        calls = []
        real = buf._get_chunks_exact_indexed

        def counting(start_index, count):
            calls.append((start_index, count))
            return real(start_index, count)

        buf._get_chunks_exact_indexed = counting
        indexed, new_index = buf.get_optimized_client_data_indexed(0)
        self.assertEqual([i for i, _ in indexed], list(range(1, 101)))
        self.assertEqual(new_index, 100)
        self.assertEqual(len(calls), 5)  # 5 batches of 20
