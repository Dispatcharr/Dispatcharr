"""Behind-head join Lua script, run against real Redis.

``_FakeRedis`` reimplements the script in Python, so fractional-target and
wire-format bugs only show up against a real server. These tests use a
dedicated Redis database and only touch keys they create. Skipped when Redis
is unreachable.
"""

import os
import unittest
import uuid

from django.test import SimpleTestCase

from apps.proxy.live_proxy.chunk_time_lookup import (
    FIND_CHUNK_BEHIND_HEAD_LUA,
    behind_head_from_lua_result,
)

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None

TEST_REDIS_DB = int(os.environ.get("CHUNK_BEHIND_LUA_TEST_REDIS_DB", "15"))


def _connect():
    if redis_lib is None:
        return None
    try:
        client = redis_lib.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            db=TEST_REDIS_DB,
            decode_responses=False,
            socket_connect_timeout=0.5,
        )
        client.ping()
        return client
    except Exception:
        return None


@unittest.skipIf(_connect() is None, "Redis is not reachable")
class BehindHeadLuaTests(SimpleTestCase):
    def setUp(self):
        self.redis = _connect()
        suffix = uuid.uuid4().hex[:8]
        self.scores_key = f"test:behind:{suffix}:scores"
        self.index_key = f"test:behind:{suffix}:index"
        self.disc_key = f"test:behind:{suffix}:disc"
        self.script = self.redis.register_script(FIND_CHUNK_BEHIND_HEAD_LUA)
        self.addCleanup(
            self.redis.delete, self.scores_key, self.index_key, self.disc_key
        )

    def _seed(self, scores_by_index, head=None):
        mapping = {str(i).encode(): float(s) for i, s in scores_by_index.items()}
        self.redis.zadd(self.scores_key, mapping)
        head = head if head is not None else max(scores_by_index)
        self.redis.set(self.index_key, head)

    def _eval(self, behind, lookback=8, use_disc=0):
        return self.script(
            keys=[self.scores_key, self.index_key, self.disc_key],
            args=[behind, lookback, use_disc],
        )

    def test_target_media_keeps_fractional_seconds(self):
        """Redis must not truncate head_score - behind to an integer reply."""
        self._seed({1: 100.25, 2: 102.25, 3: 104.25, 4: 106.25})
        raw = self._eval(behind=2.0)
        self.assertIsInstance(raw, (list, tuple))
        self.assertEqual(len(raw), 2)
        # Without tostring(), Redis returns an integer 104 and float() is 104.0.
        self.assertNotIsInstance(raw[1], int)
        last_consumed, target = behind_head_from_lua_result(raw)
        self.assertEqual(last_consumed, 2)
        self.assertAlmostEqual(target, 104.25, places=5)

    def test_join_depth_stays_near_behind_with_monotonic_scores(self):
        """Monotonic scores around a wrap-sized jump keep the requested depth."""
        # Mimics unwrapped scores: ... wrap-2, wrap, wrap+2, wrap+4
        wrap = 95443.7176888889
        self._seed(
            {
                1: wrap - 6.0,
                2: wrap - 4.0,
                3: wrap - 2.0,
                4: wrap,
                5: wrap + 2.0,
                6: wrap + 4.0,
            }
        )
        last_consumed, target = behind_head_from_lua_result(self._eval(behind=6.0))
        self.assertEqual(last_consumed, 2)
        self.assertAlmostEqual(target, (wrap + 4.0) - 6.0, places=5)
