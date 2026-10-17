"""Tests for StreamBuffer.mark_discontinuity flush + sidecar + in-band stamp."""

from unittest.mock import MagicMock

from django.test import TestCase

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.output.buffer import OutputStreamBuffer
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.input.ts_discontinuity import packet_has_discontinuity_indicator


CHANNEL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class _FakeRedis:
    def __init__(self):
        self.kv = {}
        self.zsets = {}
        self.ttls = {}
        self._index = 0
        self.round_trips = 0

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
        self.round_trips += 1
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

    def zrevrange(self, key, start, end):
        z = self.zsets.get(key, {})
        return [m for m, _s in sorted(z.items(), key=lambda kv: -kv[1])][start:end + 1]

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

    def zadd(self, *a):
        self.ops.append(("zadd", a))
        return self

    def zremrangebyscore(self, *a):
        self.ops.append(("zremrangebyscore", a))
        return self

    def expire(self, *a):
        self.ops.append(("expire", a))
        return self

    def get(self, *a):
        self.ops.append(("get", a))
        return self

    def zrangebyscore(self, *a):
        self.ops.append(("zrangebyscore", a))
        return self

    def zrevrange(self, *a):
        self.ops.append(("zrevrange", a))
        return self

    def execute(self, raise_on_error=True):
        before = self.redis.round_trips
        results = []
        for op, args in self.ops:
            try:
                results.append(getattr(self.redis, op)(*args))
            except Exception as e:
                if raise_on_error:
                    raise
                results.append(e)
        # One round trip for the whole pipeline, however many gets it carried.
        self.redis.round_trips = before + 1
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


class RecordOutputDiscontinuityTests(TestCase):
    def test_marks_next_index_after_flushing_and_arms_no_stamping(self):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        buf.target_chunk_size = TS_PACKET_SIZE * 4
        buf._write_buffer = bytearray(_pkt(256, 0) + _pkt(256, 1))
        partial = bytearray(b"\x47\x00")
        buf._partial_packet = bytearray(partial)

        buf.record_output_discontinuity()

        self.assertEqual(buf.index, 1)  # pending packets flushed as chunk 1
        self.assertIn("2", redis.zsets[buf.discontinuities_key])
        self.assertEqual(buf._write_buffer, bytearray())
        self.assertEqual(buf._partial_packet, partial)  # kept: encoder output is continuous
        self.assertFalse(buf._disc_stamp_active)

    def test_empty_key_is_a_no_op(self):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis, discontinuities_key="")
        buf.record_output_discontinuity()
        self.assertEqual(redis.zsets, {})


class SwitchMarksTests(TestCase):
    def _buffer(self, head=5, marks=()):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        redis.kv[buf.buffer_index_key] = str(head)
        for m in marks:
            redis.zadd(buf.discontinuities_key, {str(m): float(m)})
        now = [100.0]
        buf.switch_marks._clock = lambda: now[0]
        redis.round_trips = 0
        return buf, redis, now

    def test_read_returns_head_and_newest_mark_in_one_round_trip(self):
        buf, redis, _ = self._buffer(head=5, marks=[2, 3])
        self.assertEqual(buf.switch_marks.read(), ("5", 3))
        self.assertEqual(redis.round_trips, 1)

    def test_no_marks_gives_none(self):
        buf, _, _ = self._buffer(head=5)
        self.assertEqual(buf.switch_marks.read(), ("5", None))

    def test_mark_above_head_is_ignored_for_the_one_below(self):
        # The newest mark was written as head + 1 and its chunk is not stored yet.
        buf, _, _ = self._buffer(head=5, marks=[3, 6])
        self.assertEqual(buf.switch_marks.read(), ("5", 3))

    def test_empty_key_reads_only_the_head(self):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis, discontinuities_key="")
        redis.kv[buf.buffer_index_key] = "5"
        self.assertEqual(buf.switch_marks.read(), ("5", None))

    def test_mark_query_error_gives_no_mark_but_the_head(self):
        buf, redis, _ = self._buffer(head=5, marks=[3])

        def boom(*_a, **_k):
            raise RuntimeError("redis blip")

        redis.zrevrange = boom
        self.assertEqual(buf.switch_marks.read(), ("5", None))

    def test_skip_after_returns_mark_minus_one_only_past_the_next_index(self):
        buf, _, _ = self._buffer(head=5, marks=[4])
        self.assertEqual(buf.switch_marks.skip_after(2), 3)
        self.assertIsNone(buf.switch_marks.skip_after(3))  # mark at the next index: no move
        self.assertIsNone(buf.switch_marks.skip_after(4))

    def test_skip_after_looks_up_at_most_once_per_interval_for_all_callers(self):
        buf, redis, now = self._buffer(head=5)
        self.assertIsNone(buf.switch_marks.skip_after(0))
        redis.zadd(buf.discontinuities_key, {"4": 4.0})
        now[0] += 0.25
        self.assertIsNone(buf.switch_marks.skip_after(0))  # cached: no new lookup yet
        self.assertIsNone(buf.switch_marks.skip_after(1))
        self.assertEqual(redis.round_trips, 1)
        now[0] += 0.25
        self.assertEqual(buf.switch_marks.skip_after(0), 3)
        self.assertEqual(redis.round_trips, 2)

    def test_a_read_refreshes_the_cached_mark(self):
        buf, redis, _ = self._buffer(head=5)
        self.assertIsNone(buf.switch_marks.skip_after(0))
        redis.zadd(buf.discontinuities_key, {"4": 4.0})
        buf.switch_marks.read()
        redis.round_trips = 0
        self.assertEqual(buf.switch_marks.skip_after(0), 3)
        self.assertEqual(redis.round_trips, 0)

    def test_skip_after_error_gives_none_and_waits_an_interval(self):
        buf, redis, now = self._buffer(head=5, marks=[4])

        def boom(*_a, **_k):
            raise RuntimeError("redis blip")

        redis.get = boom
        self.assertIsNone(buf.switch_marks.skip_after(0))
        del redis.get
        self.assertIsNone(buf.switch_marks.skip_after(0))  # no retry inside the interval
        now[0] += 0.5
        self.assertEqual(buf.switch_marks.skip_after(0), 3)


class OutputSwitchMarkTests(TestCase):
    def test_writer_mark_is_seen_by_reader_and_cleared_on_cleanup(self):
        redis = _FakeRedis()
        key = RedisKeys.output_discontinuities(CHANNEL_ID, "fmp4")
        writer = OutputStreamBuffer(
            CHANNEL_ID, redis_client=redis, fmt="fmp4", discontinuities_key=key
        )
        writer.index = 4
        redis.kv[writer.buffer_index_key] = "6"
        writer.record_output_discontinuity()

        reader = OutputStreamBuffer(
            CHANNEL_ID, redis_client=redis, fmt="fmp4", discontinuities_key=key
        )
        self.assertEqual(reader.switch_marks.read(), ("6", 5))

        redis.scan = lambda cursor, match, count: (0, [])
        redis.delete = MagicMock()
        writer.cleanup_redis()
        deleted = [c.args for c in redis.delete.call_args_list]
        self.assertTrue(any(key in args for args in deleted))


class ReadJumpTests(TestCase):
    """Reads start at the newest switch mark ahead of the reader."""

    def _buffer(self, head=6, marks=(), missing=()):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        redis.kv[buf.buffer_index_key] = str(head)
        buf.index = head
        for i in range(1, head + 1):
            if i not in missing:
                redis.kv[f"{buf.buffer_prefix}{i}"] = f"c{i}".encode()
        for m in marks:
            redis.zadd(buf.discontinuities_key, {str(m): float(m)})
        redis.round_trips = 0
        return buf, redis

    def test_no_mark_reads_as_before(self):
        buf, _ = self._buffer()
        self.assertEqual(
            buf.get_optimized_client_data(0),
            ([b"c1", b"c2", b"c3", b"c4", b"c5", b"c6"], 6),
        )
        self.assertIsNone(buf.read_client_batch(0).switch_mark)

    def test_read_jumps_to_the_mark_and_reports_it(self):
        buf, _ = self._buffer(marks=[4])
        batch = buf.read_client_batch(0)
        self.assertEqual(batch.chunks, [b"c4", b"c5", b"c6"])
        self.assertEqual((batch.start_index, batch.next_index, batch.switch_mark), (3, 6, 4))
        self.assertEqual(buf.get_optimized_client_data(0), ([b"c4", b"c5", b"c6"], 6))

    def test_two_marks_read_from_the_newest(self):
        buf, _ = self._buffer(marks=[2, 5])
        self.assertEqual(buf.read_client_batch(0).chunks, [b"c5", b"c6"])

    def test_mark_at_the_next_index_is_reported_without_a_move(self):
        buf, _ = self._buffer(marks=[3])
        batch = buf.read_client_batch(2)
        self.assertEqual((batch.chunks[0], batch.start_index, batch.switch_mark), (b"c3", 2, 3))

    def test_mark_already_passed_is_not_reported(self):
        buf, _ = self._buffer(marks=[3])
        batch = buf.read_client_batch(3)
        self.assertEqual(
            (batch.chunks, batch.start_index, batch.switch_mark),
            ([b"c4", b"c5", b"c6"], 3, None),
        )

    def test_mark_above_the_head_is_not_read_yet(self):
        buf, _ = self._buffer(marks=[7])
        self.assertIsNone(buf.read_client_batch(0).switch_mark)

    def test_expired_chunk_at_the_mark_is_skipped_and_the_mark_still_reported(self):
        buf, _ = self._buffer(marks=[4], missing=[4])
        batch = buf.read_client_batch(0)
        self.assertEqual((batch.chunks, batch.switch_mark), ([b"c5", b"c6"], 4))

    def test_head_and_mark_cost_no_extra_round_trip(self):
        buf, redis = self._buffer(marks=[4])
        buf.read_client_batch(0)
        # One pipeline for head and mark, one for the chunks: the same as a read on dev.
        self.assertEqual(redis.round_trips, 2)

    def test_mark_query_error_reads_as_before(self):
        buf, redis = self._buffer(marks=[4])

        def boom(*_a, **_k):
            raise RuntimeError("redis blip")

        redis.zrevrange = boom
        batch = buf.read_client_batch(0)
        self.assertEqual((len(batch.chunks), batch.switch_mark), (6, None))

    def test_output_buffer_read_jumps_to_the_mark(self):
        redis = _FakeRedis()
        key = RedisKeys.output_discontinuities(CHANNEL_ID, "fmp4")
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt="fmp4", discontinuities_key=key)
        redis.kv[buf.buffer_index_key] = "5"
        for i in range(1, 6):
            redis.kv[RedisKeys.output_buffer_chunk(CHANNEL_ID, "fmp4", i)] = f"f{i}".encode()
        self.assertEqual(buf.get_chunks(start_index=0), ([b"f1", b"f2", b"f3", b"f4", b"f5"], 5))
        redis.zadd(key, {"4": 4.0})
        self.assertEqual(buf.get_chunks(start_index=0), ([b"f4", b"f5"], 5))
        self.assertEqual(buf.get_chunks(start_index=4), ([b"f5"], 5))


class FlushPendingTests(TestCase):
    """StreamBuffer.flush_pending publishes bytes below target_chunk_size once they age."""

    def _buf(self):
        redis = _FakeRedis()
        buf = StreamBuffer(CHANNEL_ID, redis_client=redis)
        now = [0.0]
        buf._clock = lambda: now[0]
        return buf, redis, now

    def test_nothing_pending_returns_false(self):
        buf, _redis, _now = self._buf()
        self.assertFalse(buf.flush_pending(0.5))
        self.assertEqual(buf.index, 0)

    def test_young_pending_bytes_are_not_published(self):
        buf, redis, now = self._buf()
        now[0] = 0.0
        buf.add_chunk(_pkt(256, 0) + _pkt(256, 1))
        now[0] = 0.3
        self.assertFalse(buf.flush_pending(0.5))
        self.assertEqual(buf.index, 0)
        self.assertFalse(any(k.startswith(buf.buffer_prefix) for k in redis.kv))

    def test_aged_pending_bytes_publish_whole_packets_only(self):
        buf, redis, now = self._buf()
        now[0] = 0.0
        buf.add_chunk(_pkt(256, 0) + _pkt(256, 1) + bytes(50))
        now[0] = 0.6
        self.assertTrue(buf.flush_pending(0.5))
        self.assertEqual(buf.index, 1)
        published = redis.kv[buf.buffer_prefix + "1"]
        self.assertEqual(len(published), 2 * TS_PACKET_SIZE)
        self.assertEqual(len(published) % TS_PACKET_SIZE, 0)
        # The 50-byte partial packet stays behind, and nothing is pending any more.
        self.assertEqual(len(buf._partial_packet), 50)
        self.assertEqual(len(buf._write_buffer), 0)
        self.assertIsNone(buf._pending_since)
        self.assertFalse(buf.flush_pending(0.5))

    def test_redis_error_returns_false_without_raising(self):
        buf, redis, now = self._buf()
        now[0] = 0.0
        buf.add_chunk(_pkt(256, 0) + _pkt(256, 1))

        class BoomPipeline:
            def __getattr__(self, _name):
                return lambda *a, **k: self

            def execute(self):
                raise RuntimeError("redis blip")

        redis.pipeline = lambda transaction=False: BoomPipeline()
        now[0] = 0.6
        self.assertFalse(buf.flush_pending(0.5))
        self.assertEqual(buf.index, 0)

    def test_remainder_after_a_full_chunk_is_timed_from_its_own_arrival(self):
        buf, redis, now = self._buf()
        buf.target_chunk_size = 3 * TS_PACKET_SIZE
        now[0] = 0.0
        buf.add_chunk(_pkt(256, 0))
        now[0] = 0.2
        buf.add_chunk(_pkt(256, 1) + _pkt(256, 2) + _pkt(256, 3))
        # One full chunk went out and one new packet remains, which arrived at 0.2.
        self.assertEqual(buf.index, 1)
        now[0] = 0.5  # 0.3 s after the remainder arrived
        self.assertFalse(buf.flush_pending(0.5))
        now[0] = 0.8  # 0.6 s after the remainder arrived (0.7 - 0.2 is not exact in floats)
        self.assertTrue(buf.flush_pending(0.5))
        self.assertEqual(buf.index, 2)
