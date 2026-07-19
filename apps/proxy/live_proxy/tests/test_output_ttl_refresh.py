"""Tests for output manager Redis TTL refresh (fMP4 and profile).

Owner/state/init keys use an orphan-backstop TTL. While a manager is alive
those TTLs must be extended so sessions longer than the TTL stay healthy,
without refreshing on every fragment.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.live_proxy.output.fmp4.manager import (
    FMP4_KEY_TTL,
    FMP4_TTL_REFRESH_INTERVAL,
    FMP4RemuxManager,
)
from apps.proxy.live_proxy.output.profile.manager import (
    PROFILE_KEY_TTL,
    PROFILE_TTL_REFRESH_INTERVAL,
    OutputProfileManager,
)
from apps.proxy.live_proxy.redis_keys import RedisKeys


CHANNEL_ID = "b9b44371-14f5-4d48-b041-125cbafabf41"
WORKER_ID = "worker-test-1"
FMT = "fmp4"


class _Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))
        return self

    def execute(self):
        results = []
        for op, key, ttl in self.ops:
            if op == "expire":
                results.append(self.redis.expire(key, ttl))
        return results


class _FakeRedis:
    def __init__(self):
        self.expires = []
        self.keys = set()

    def pipeline(self):
        return _Pipeline(self)

    def expire(self, key, ttl):
        self.expires.append((key, ttl))
        return 1 if key in self.keys else 0


def _make_fmp4_manager(redis_client, buffer_client=None):
    mgr = FMP4RemuxManager.__new__(FMP4RemuxManager)
    mgr.channel_id = CHANNEL_ID
    mgr.worker_id = WORKER_ID
    mgr.fmt = FMT
    mgr._redis = redis_client
    mgr._last_ttl_refresh = 0.0
    mgr.fmp4_buffer = MagicMock()
    return mgr, buffer_client if buffer_client is not None else _FakeRedis()


def _make_profile_manager(redis_client, profile_id=7):
    mgr = OutputProfileManager.__new__(OutputProfileManager)
    mgr.channel_id = CHANNEL_ID
    mgr.profile_id = profile_id
    mgr.worker_id = WORKER_ID
    mgr._redis = redis_client
    mgr._last_ttl_refresh = 0.0
    return mgr


class FMP4TTLRefreshTests(TestCase):
    def test_refresh_expires_owner_state_and_init(self):
        redis = _FakeRedis()
        buf = _FakeRedis()
        owner_key = RedisKeys.output_owner(CHANNEL_ID, FMT)
        state_key = RedisKeys.output_state(CHANNEL_ID, FMT)
        init_key = RedisKeys.output_init(CHANNEL_ID, FMT)
        redis.keys.update({owner_key, state_key})
        buf.keys.add(init_key)

        mgr, _ = _make_fmp4_manager(redis, buf)
        with patch(
            "apps.proxy.live_proxy.output.fmp4.manager.RedisClient.get_buffer",
            return_value=buf,
        ):
            mgr._refresh_redis_ttls()

        self.assertIn((owner_key, FMP4_KEY_TTL), redis.expires)
        self.assertIn((state_key, FMP4_KEY_TTL), redis.expires)
        self.assertIn((init_key, FMP4_KEY_TTL), buf.expires)

    def test_refresh_is_rate_limited(self):
        redis = _FakeRedis()
        buf = _FakeRedis()
        mgr, _ = _make_fmp4_manager(redis, buf)
        with patch(
            "apps.proxy.live_proxy.output.fmp4.manager.RedisClient.get_buffer",
            return_value=buf,
        ):
            mgr._refresh_redis_ttls()
            first_count = len(redis.expires)
            mgr._refresh_redis_ttls()
            self.assertEqual(len(redis.expires), first_count)

            mgr._last_ttl_refresh -= FMP4_TTL_REFRESH_INTERVAL + 1
            mgr._refresh_redis_ttls()
            self.assertEqual(len(redis.expires), first_count + 2)

    def test_refresh_noop_without_redis(self):
        mgr, _ = _make_fmp4_manager(None)
        mgr._refresh_redis_ttls()  # must not raise


class ProfileTTLRefreshTests(TestCase):
    def test_refresh_expires_owner_and_state(self):
        redis = _FakeRedis()
        profile_id = 7
        fmt = f"mpegts:p{profile_id}"
        owner_key = RedisKeys.output_owner(CHANNEL_ID, fmt)
        state_key = RedisKeys.output_state(CHANNEL_ID, fmt)
        redis.keys.update({owner_key, state_key})

        mgr = _make_profile_manager(redis, profile_id=profile_id)
        mgr._refresh_redis_ttls()

        self.assertIn((owner_key, PROFILE_KEY_TTL), redis.expires)
        self.assertIn((state_key, PROFILE_KEY_TTL), redis.expires)

    def test_refresh_is_rate_limited(self):
        redis = _FakeRedis()
        mgr = _make_profile_manager(redis)
        mgr._refresh_redis_ttls()
        first_count = len(redis.expires)
        mgr._refresh_redis_ttls()
        self.assertEqual(len(redis.expires), first_count)

        mgr._last_ttl_refresh -= PROFILE_TTL_REFRESH_INTERVAL + 1
        mgr._refresh_redis_ttls()
        self.assertEqual(len(redis.expires), first_count + 2)
