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
        self.hashes = {}
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

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value
        return 1

    def hdel(self, key, *fields):
        bucket = self.hashes.get(key, {})
        removed = 0
        for field in fields:
            if bucket.pop(field, None) is not None:
                removed += 1
        return removed

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
        lo = float("-inf") if min_s == "-inf" else float(min_s)
        hi = float("inf") if max_s in ("+inf", "inf") else float(max_s)
        return [m for m, s in sorted(z.items(), key=lambda kv: kv[1]) if lo <= s <= hi]

    def zrevrangebyscore(self, key, max_s, min_s, start=None, num=None, withscores=False):
        members = list(reversed(self.zrangebyscore(key, min_s, max_s)))
        if start is not None and num is not None:
            members = members[int(start) : int(start) + int(num)]
        if withscores:
            z = self.zsets.get(key, {})
            return [(m, z[m]) for m in members]
        return members

    def zrange(self, key, start, end, withscores=False):
        z = self.zsets.get(key, {})
        ordered = sorted(z.items(), key=lambda kv: kv[1])
        end = None if end == -1 else end + 1
        ordered = ordered[start:end]
        if withscores:
            return [(m, s) for m, s in ordered]
        return [m for m, _s in ordered]

    def zscore(self, key, member):
        z = self.zsets.get(key, {})
        score = z.get(str(member))
        return None if score is None else float(score)

    def zremrangebyrank(self, key, start, end):
        z = self.zsets.get(key, {})
        ordered = sorted(z.items(), key=lambda kv: kv[1])
        end = None if end == -1 else end + 1
        drop = [m for m, _s in ordered[start:end]]
        for m in drop:
            del z[m]
        return len(drop)

    def zrem(self, key, *members):
        z = self.zsets.get(key, {})
        dropped = 0
        for member in members:
            if z.pop(str(member), None) is not None:
                dropped += 1
        return dropped

    def delete(self, *keys):
        n = 0
        for key in keys:
            if key in self.kv:
                del self.kv[key]
                n += 1
            if key in self.zsets:
                del self.zsets[key]
                n += 1
        return n

    def pipeline(self, transaction=False):
        return _FakePipeline(self)

    def register_script(self, script):
        redis = self
        if "head_raw" in script:
            def _behind_head(keys=None, args=None, client=None):
                scores_key = keys[0]
                index_key = keys[1]
                disc_key = keys[2]
                behind = float(args[0])
                lookback = int(float(args[1])) if len(args) > 1 else 0
                use_disc = int(float(args[2])) if len(args) > 2 else 0

                head_raw = redis.kv.get(index_key)
                if head_raw is None:
                    return [-2]
                head = int(head_raw)
                if head <= 0:
                    return [-2]

                era_floor = 0
                if use_disc == 1 and disc_key in redis.zsets:
                    discs = redis.zrevrangebyscore(disc_key, head, "-inf", start=0, num=1)
                    if discs:
                        era_floor = int(discs[0])

                head_score = redis.zscore(scores_key, str(head))
                if head_score is None:
                    low = max(era_floor, head - lookback) if lookback else era_floor
                    for i in range(head - 1, low - 1, -1):
                        head_score = redis.zscore(scores_key, str(i))
                        if head_score is not None:
                            break
                if head_score is None:
                    return [-1]

                target = float(head_score) - behind
                # Match real Redis: target is a string so fractional seconds survive.
                target_s = format(target, ".12g")
                for member in redis.zrevrangebyscore(scores_key, target, "-inf"):
                    if int(member) >= era_floor:
                        return [int(member), target_s]

                members = redis.zrange(scores_key, 0, -1)
                min_idx = None
                for member in members:
                    idx = int(member)
                    if idx >= era_floor and (min_idx is None or idx < min_idx):
                        min_idx = idx
                return [min_idx, target_s] if min_idx is not None else [-1]

            return _behind_head

        def _find(keys=None, args=None, client=None):
            ts_key = keys[0]
            target = float(args[0])
            min_index = int(float(args[1])) if len(args) > 1 else 0
            for member in redis.zrevrangebyscore(ts_key, target, "-inf"):
                if int(member) >= min_index:
                    return int(member)
            return -1

        return _find


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

    def zscore(self, *a):
        self.ops.append(("zscore", a))
        return self

    def zremrangebyscore(self, *a):
        self.ops.append(("zremrangebyscore", a))
        return self

    def expire(self, *a):
        self.ops.append(("expire", a))
        return self

    def zremrangebyrank(self, *a):
        self.ops.append(("zremrangebyrank", a))
        return self

    def zrem(self, *a):
        self.ops.append(("zrem", a))
        return self

    def delete(self, *a):
        self.ops.append(("delete", a))
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
