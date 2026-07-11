"""Tests for per-user stream limit enforcement in apps.proxy.utils."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys
from apps.proxy.utils import (
    _STOP_REASON_ADMIN,
    _timeshift_stop_channel_id,
    attempt_stream_termination,
    check_user_stream_limits,
    stop_timeshift_client,
)


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = str(value)

    def hget(self, key, field):
        hash_value = self.store.get(key)
        return hash_value.get(field) if isinstance(hash_value, dict) else None

    def hset(self, key, field=None, value=None, mapping=None, **kwargs):
        hash_value = self.store.get(key)
        if not isinstance(hash_value, dict):
            hash_value = {}
            self.store[key] = hash_value
        if field is not None and value is not None:
            hash_value[str(field)] = str(value)
        for f, v in (mapping or {}).items():
            hash_value[str(f)] = str(v)

    def delete(self, *keys):
        count = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                count += 1
        return count

    def exists(self, key):
        return key in self.store

    def sadd(self, key, *members):
        existing = self.store.get(key)
        if not isinstance(existing, set):
            existing = set()
            self.store[key] = existing
        before = len(existing)
        existing.update(str(m) for m in members)
        return len(existing) - before

    def smembers(self, key):
        value = self.store.get(key)
        return set(value) if isinstance(value, set) else set()

    def scan_iter(self, match=None, count=None):  # noqa: ARG002
        import fnmatch

        for key in list(self.store):
            if match is None or fnmatch.fnmatch(str(key), match):
                yield key

    def eval(self, script, numkeys, *keys_and_args):
        if numkeys != 1 or len(keys_and_args) != 2:
            raise NotImplementedError("FakeRedis eval only supports claim script")
        key, token = keys_and_args
        current = self.store.get(key)
        if current is not None and str(current) == str(token):
            self.store.pop(key, None)
            return 1
        return 0


class TimeshiftStopChannelIdTests(TestCase):
    def setUp(self):
        self.redis = _FakeRedis()
        self.stats_channel_id = "8_victim"
        self.client_id = "victim"
        self.programme_vid = "8_2026-06-08-17-00_111"

    def test_resolves_programme_vid_from_stats_metadata(self):
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "programme_vid", self.programme_vid)

        resolved = _timeshift_stop_channel_id(
            self.redis, self.stats_channel_id, self.client_id,
        )
        self.assertEqual(resolved, self.programme_vid)

    def test_falls_back_to_stats_channel_id_for_legacy_entries(self):
        resolved = _timeshift_stop_channel_id(
            self.redis, self.stats_channel_id, self.client_id,
        )
        self.assertEqual(resolved, self.stats_channel_id)


class AttemptStreamTerminationTests(TestCase):
    def setUp(self):
        self.redis = _FakeRedis()
        self.user_id = 5
        self.requesting_client_id = "newsession"
        self.stats_channel_id = "8_victim"
        self.programme_vid = "8_2026-06-08-17-00_111"
        self.victim_client_id = "victim"
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.victim_client_id,
        )
        self.redis.hset(client_key, "programme_vid", self.programme_vid)

    def _connections(self):
        return [{
            "media_id": self.stats_channel_id,
            "client_id": self.victim_client_id,
            "connected_at": 1000.0,
            "type": "timeshift",
        }]

    def _limits_settings(self):
        return {
            "terminate_oldest": True,
            "prioritize_single_client_channels": True,
            "ignore_same_channel_connections": False,
        }

    def test_timeshift_stop_key_targets_programme_vid_not_stats_channel(self):
        with patch("apps.proxy.utils.RedisClient.get_client",
                   return_value=self.redis), \
             patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=self._limits_settings()):
            ok = attempt_stream_termination(
                self.user_id, self.requesting_client_id, self._connections(),
            )

        self.assertTrue(ok)
        programme_stop = RedisKeys.client_stop(
            self.programme_vid, self.victim_client_id,
        )
        stats_stop = RedisKeys.client_stop(
            self.stats_channel_id, self.victim_client_id,
        )
        self.assertIn(programme_stop, self.redis.store)
        self.assertNotIn(stats_stop, self.redis.store)

    def test_timeshift_limit_stop_uses_generation_key_when_metadata_missing(self):
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.victim_client_id,
        )
        self.redis.store.pop(client_key, None)
        generation_key = (
            f"timeshift:stream_gen:{self.programme_vid}:{self.victim_client_id}"
        )
        self.redis.store[generation_key] = "4"

        with patch("apps.proxy.utils.RedisClient.get_client",
                   return_value=self.redis), \
             patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=self._limits_settings()):
            ok = attempt_stream_termination(
                self.user_id, self.requesting_client_id, self._connections(),
            )

        self.assertTrue(ok)
        programme_stop = RedisKeys.client_stop(
            self.programme_vid, self.victim_client_id,
        )
        self.assertIn(programme_stop, self.redis.store)

    def test_limit_termination_allows_new_timeshift_when_victim_stopped(self):
        user = MagicMock(id=5, username="viewer", stream_limit=1)
        new_session = "newsession"
        connections = self._connections()
        settings = {
            **self._limits_settings(),
            "terminate_on_limit_exceeded": True,
        }
        with patch("apps.proxy.utils.get_user_active_connections",
                   return_value=connections), \
             patch("apps.proxy.utils.RedisClient.get_client",
                   return_value=self.redis), \
             patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=settings):
            allowed = check_user_stream_limits(
                user, new_session, media_id="8_2026-06-08-17-30",
            )

        self.assertTrue(allowed)
        programme_stop = RedisKeys.client_stop(
            self.programme_vid, self.victim_client_id,
        )
        self.assertIn(programme_stop, self.redis.store)

    def test_live_termination_still_uses_channel_service(self):
        connections = [{
            "media_id": "42",
            "client_id": "live_client_1",
            "connected_at": 1000.0,
            "type": "live",
        }]
        with patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=self._limits_settings()), \
             patch("apps.proxy.utils.ChannelService.stop_client",
                   return_value={"status": "ok"}) as stop_mock:
            ok = attempt_stream_termination(
                self.user_id, self.requesting_client_id, connections,
            )

        self.assertTrue(ok)
        stop_mock.assert_called_once_with("42", "live_client_1")


class TimeshiftAdminStopTests(TestCase):
    def setUp(self):
        self.redis = _FakeRedis()
        self.stats_channel_id = "8_victim"
        self.programme_vid = "8_2026-06-08-17-00_111"
        self.client_id = "victim"
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "programme_vid", self.programme_vid)
        self.redis.sadd(RedisKeys.clients(self.stats_channel_id), self.client_id)
        self.redis.hset(
            RedisKeys.channel_metadata(self.stats_channel_id),
            "state", "active",
        )

    def test_admin_stop_client_signals_programme_and_unregisters_stats(self):
        session_key = RedisKeys.api_session(self.client_id)
        self.redis.hset(session_key, "user_id", "1")

        with patch("apps.timeshift.views._unregister_stats_client") as unregister_mock, \
             patch("apps.timeshift.views._trigger_timeshift_stats_update") as trigger_mock:
            result = stop_timeshift_client(
                self.redis, self.stats_channel_id, self.client_id,
            )

        self.assertEqual(result["status"], "success")
        programme_stop = RedisKeys.client_stop(self.programme_vid, self.client_id)
        stats_stop = RedisKeys.client_stop(self.stats_channel_id, self.client_id)
        self.assertEqual(self.redis.store.get(programme_stop), _STOP_REASON_ADMIN)
        self.assertNotIn(stats_stop, self.redis.store)
        self.assertNotIn(session_key, self.redis.store)
        unregister_mock.assert_called_once_with(
            self.redis, self.stats_channel_id, self.client_id,
        )
        trigger_mock.assert_called_once_with(self.redis)

    def test_admin_stop_closes_local_upstream_when_registered(self):
        from apps.timeshift.views import _close_active_upstream, _register_active_upstream

        upstream = MagicMock()
        _register_active_upstream(self.programme_vid, self.client_id, upstream)

        with patch("apps.timeshift.views._unregister_stats_client"):
            result = stop_timeshift_client(
                self.redis, self.stats_channel_id, self.client_id,
            )

        self.assertEqual(result["status"], "success")
        upstream.close.assert_called_once()
        _close_active_upstream(self.programme_vid, self.client_id)
        upstream.close.assert_called_once()

    def test_admin_stop_uses_generation_key_when_metadata_missing(self):
        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        self.redis.store.pop(client_key, None)
        generation_key = f"timeshift:stream_gen:{self.programme_vid}:{self.client_id}"
        self.redis.store[generation_key] = "4"

        with patch("apps.timeshift.views._unregister_stats_client"):
            result = stop_timeshift_client(
                self.redis, self.stats_channel_id, self.client_id,
            )

        self.assertEqual(result["status"], "success")
        programme_stop = RedisKeys.client_stop(self.programme_vid, self.client_id)
        self.assertEqual(self.redis.store.get(programme_stop), _STOP_REASON_ADMIN)
        self.assertIn(self.programme_vid, result["stop_channel_ids"])
