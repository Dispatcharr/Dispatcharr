"""Cold-start session count and abandon-claim scripts, run against real Redis.

The scripts are Lua, so mocks cannot tell whether they are right. These tests
use a dedicated Redis database and only touch keys they create. They are
skipped when no Redis server is reachable.
"""

import os
import time
import unittest
import uuid
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.output.hls import session as hls_session
from apps.proxy.live_proxy.redis_keys import RedisKeys

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None

TEST_REDIS_DB = int(os.environ.get("HLS_LUA_TEST_REDIS_DB", "15"))


def _connect():
    if redis_lib is None:
        return None
    try:
        client = redis_lib.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            db=TEST_REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=0.5,
        )
        client.ping()
        return client
    except Exception:
        return None


@unittest.skipIf(_connect() is None, "Redis is not reachable")
class ColdStartScriptTests(SimpleTestCase):
    def setUp(self):
        hls_session._script_cache.clear()
        self.redis = _connect()
        suffix = uuid.uuid4().hex[:8]
        self.channel_id = f"chan-{suffix}"
        self.client_id = f"client-{suffix}"
        self.token = f"token-{suffix}"
        self.session_key = RedisKeys.hls_session(self.token)
        self.client_key = RedisKeys.client_metadata(self.channel_id, self.client_id)
        self.playlist_key = RedisKeys.output_playlist(self.channel_id, "hls")
        self.addCleanup(
            self.redis.delete,
            self.session_key,
            self.client_key,
            RedisKeys.clients(self.channel_id),
            self.playlist_key,
            RedisKeys.channel_stopping(self.channel_id),
            RedisKeys.client_stop(self.channel_id, self.client_id),
        )

    def _create_session(self, last_active=None):
        self.redis.hset(
            self.session_key,
            mapping={
                "channel_id": self.channel_id,
                "client_id": self.client_id,
                "user_id": "0",
            },
        )
        self.redis.expire(self.session_key, 60)
        self.redis.hset(
            self.client_key,
            mapping={
                "hls_token": self.token,
                "last_active": str(time.time() - 10 if last_active is None else last_active),
            },
        )
        self.redis.expire(self.client_key, 60)

    def _touch(self):
        with patch(
            "apps.proxy.live_proxy.output.hls.session.ConfigHelper.get",
            return_value=60,
        ):
            return hls_session.touch_hls_session(self.redis, self.token)

    def _claim(self, since):
        return hls_session.claim_abandoned_session(
            self.redis, self.token, self.playlist_key, since
        )

    def test_count_goes_up_and_down_and_never_below_zero(self):
        self._create_session()
        self.assertEqual(hls_session.enter_cold_start(self.redis, self.token), 1)
        self.assertEqual(hls_session.enter_cold_start(self.redis, self.token), 2)
        self.assertEqual(hls_session.exit_cold_start(self.redis, self.token), 1)
        self.assertEqual(hls_session.exit_cold_start(self.redis, self.token), 0)
        self.assertEqual(hls_session.exit_cold_start(self.redis, self.token), 0)
        self.assertEqual(self.redis.hget(self.session_key, "cold_streams"), "0")

    def test_missing_session_is_reported_and_never_recreated(self):
        self.assertIsNone(hls_session.enter_cold_start(self.redis, self.token))
        self.assertIsNone(hls_session.exit_cold_start(self.redis, self.token))
        self.assertIsNone(self._claim(time.time()))
        self.assertEqual(self.redis.exists(self.session_key), 0)

    def test_count_keeps_the_session_ttl(self):
        self._create_session()
        hls_session.enter_cold_start(self.redis, self.token)
        hls_session.exit_cold_start(self.redis, self.token)
        self.assertTrue(0 < self.redis.ttl(self.session_key) <= 60)

    def test_count_does_not_disturb_touch(self):
        self._create_session()
        hls_session.enter_cold_start(self.redis, self.token)
        loaded, reason = self._touch()
        self.assertIsNone(reason)
        self.assertEqual(loaded[:2], (self.channel_id, self.client_id))

    def test_nothing_is_claimed_while_a_request_is_held(self):
        self._create_session()
        hls_session.enter_cold_start(self.redis, self.token)
        self.assertIsNone(self._claim(time.time()))
        self.assertEqual(self.redis.exists(self.session_key), 1)

    def test_nothing_is_claimed_once_the_playlist_is_published(self):
        self._create_session()
        self.redis.set(self.playlist_key, "{}", ex=60)
        self.assertIsNone(self._claim(time.time()))
        self.assertEqual(self.redis.exists(self.session_key), 1)

    def test_abandoned_session_is_claimed_once_and_forgotten(self):
        self._create_session()
        hls_session.enter_cold_start(self.redis, self.token)
        hls_session.exit_cold_start(self.redis, self.token)
        self.assertEqual(
            self._claim(time.time()), (self.channel_id, self.client_id)
        )
        self.assertEqual(self.redis.exists(self.session_key), 0)
        self.assertIsNone(self._claim(time.time()))

    def test_claimed_session_gives_a_late_request_a_410_path(self):
        self._create_session()
        self._claim(time.time())
        loaded, reason = self._touch()
        self.assertIsNone(loaded)
        self.assertEqual(reason, "expired")

    def test_request_during_the_grace_cancels_the_claim(self):
        self._create_session()
        hls_session.enter_cold_start(self.redis, self.token)
        hls_session.exit_cold_start(self.redis, self.token)
        disconnected_at = time.time()
        time.sleep(0.02)
        loaded, reason = self._touch()
        self.assertIsNone(reason)
        self.assertIsNone(self._claim(disconnected_at))
        self.assertEqual(self.redis.exists(self.session_key), 1)
        self.assertIsNotNone(loaded)

    def test_request_that_arrived_before_the_disconnect_is_a_held_request(self):
        # The retry opens a second held request first; the old one then
        # disconnects. The count never reaches zero, so nothing is claimed.
        self._create_session()
        hls_session.enter_cold_start(self.redis, self.token)
        hls_session.enter_cold_start(self.redis, self.token)
        self.assertEqual(hls_session.exit_cold_start(self.redis, self.token), 1)
        self.assertIsNone(self._claim(time.time()))
        # The retry itself then leaves for good.
        self.assertEqual(hls_session.exit_cold_start(self.redis, self.token), 0)
        self.assertEqual(
            self._claim(time.time()), (self.channel_id, self.client_id)
        )

    def test_stopped_client_is_not_claimable_through_a_dead_session(self):
        self._create_session()
        self.redis.set(RedisKeys.client_stop(self.channel_id, self.client_id), "true", ex=30)
        loaded, reason = self._touch()
        self.assertIsNone(loaded)
        self.assertEqual(reason, "stopped")
        self.assertIsNone(self._claim(time.time()))
