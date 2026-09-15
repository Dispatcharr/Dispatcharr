"""Tests for StreamBuffer.mark_discontinuity flush + sidecar + in-band stamp."""

from unittest.mock import MagicMock

from django.test import TestCase

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.input.ts_discontinuity import packet_has_discontinuity_indicator


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
