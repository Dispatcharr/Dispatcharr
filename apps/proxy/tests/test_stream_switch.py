"""Tests for stream switch confirmation and metadata persistence."""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.services import channel_service as cs_module
from apps.proxy.live_proxy.services.channel_service import ChannelService


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.hashes = {}
        self.published = []

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = str(value)

    def setex(self, key, ttl, value):
        self.store[key] = str(value)

    def delete(self, *keys):
        count = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                count += 1
            if self.hashes.pop(key, None) is not None:
                count += 1
        return count

    def keys(self, pattern):
        return []

    def exists(self, key):
        return key in self.store or key in self.hashes

    def type(self, key):
        return "hash" if key in self.hashes else "none"

    def hset(self, key, field=None, value=None, mapping=None):
        hash_value = self.hashes.setdefault(key, {})
        if field is not None and value is not None:
            hash_value[str(field)] = str(value)
        for f, v in (mapping or {}).items():
            hash_value[str(f)] = str(v)

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def publish(self, channel, message):
        self.published.append((channel, message))


CHANNEL_ID = "ad8b11c0-4cd2-4bf5-a95b-153aee7f0671"
NEW_URL = "http://provider.example/stream/144065.ts"


def make_proxy_server(redis, owner):
    proxy = MagicMock()
    proxy.redis_client = redis
    proxy.worker_id = "worker-under-test"
    proxy.check_if_channel_exists.return_value = True
    proxy.am_i_owner.return_value = owner
    proxy.stream_managers = {}
    proxy.stream_buffers = {}
    return proxy


class OwnerPathTests(TestCase):
    def _run(self, manager_url="http://provider.example/stream/296622.ts"):
        redis = FakeRedis()
        proxy = make_proxy_server(redis, owner=True)

        manager = MagicMock()
        manager.url = manager_url
        manager.update_url.return_value = True
        proxy.stream_managers[CHANNEL_ID] = manager

        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
             patch("django.db.close_old_connections"):
            result = ChannelService.change_stream_url(
                CHANNEL_ID, NEW_URL, "test-agent",
                target_stream_id=144065, m3u_profile_id=7,
                stream_name="Alt Feed",
            )
        return result, redis, manager

    def test_owner_switch_persists_stream_id_metadata(self):
        result, redis, manager = self._run()

        manager.update_url.assert_called_once_with(NEW_URL, 144065, 7)
        self.assertTrue(result["success"])
        self.assertTrue(result["direct_update"])

        metadata = redis.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
        self.assertEqual(metadata[ChannelMetadataField.URL], NEW_URL)
        self.assertEqual(metadata[ChannelMetadataField.STREAM_ID], "144065")
        self.assertEqual(metadata[ChannelMetadataField.M3U_PROFILE], "7")
        self.assertEqual(metadata[ChannelMetadataField.STREAM_NAME], "Alt Feed")

    def test_owner_same_url_is_success_and_repairs_metadata(self):
        result, redis, manager = self._run(manager_url=NEW_URL)

        manager.update_url.assert_not_called()
        self.assertTrue(result["success"])

        metadata = redis.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
        self.assertEqual(metadata[ChannelMetadataField.STREAM_ID], "144065")


class NonOwnerPathTests(TestCase):
    def _run(self, owner_outcome):
        redis = FakeRedis()
        proxy = make_proxy_server(redis, owner=False)
        status_key = RedisKeys.switch_status(CHANNEL_ID)

        if owner_outcome is not None:
            original_publish = redis.publish

            def publish_and_confirm(channel, message):
                original_publish(channel, message)
                redis.store[status_key] = owner_outcome

            redis.publish = publish_and_confirm

        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
             patch.object(cs_module, "STREAM_SWITCH_CONFIRM_TIMEOUT", 0.3), \
             patch.object(cs_module, "STREAM_SWITCH_POLL_INTERVAL", 0.05):
            result = ChannelService.change_stream_url(
                CHANNEL_ID, NEW_URL, "test-agent",
                target_stream_id=144065, m3u_profile_id=7,
                stream_name="Alt Feed",
            )
        return result, redis

    def test_pubsub_event_carries_stream_id(self):
        result, redis = self._run(owner_outcome="switched")

        self.assertEqual(len(redis.published), 1)
        payload = json.loads(redis.published[0][1])
        self.assertEqual(payload["stream_id"], 144065)
        self.assertEqual(payload["m3u_profile_id"], 7)
        self.assertEqual(payload["stream_name"], "Alt Feed")
        self.assertEqual(payload["url"], NEW_URL)

    def test_switch_confirmed_by_owner_reports_success(self):
        result, _ = self._run(owner_outcome="switched")

        self.assertTrue(result["success"])
        self.assertFalse(result["direct_update"])
        self.assertTrue(result["event_published"])

    def test_switch_failed_by_owner_reports_failure(self):
        result, _ = self._run(owner_outcome="failed")

        self.assertFalse(result["success"])
        self.assertIn("failed", result["message"].lower())

    def test_no_confirmation_times_out_and_reports_failure(self):
        result, _ = self._run(owner_outcome=None)

        self.assertFalse(result["success"])
        self.assertIs(result["confirmed"], False)
        self.assertIn("not confirmed", result["message"])

    def test_stale_status_key_is_cleared_before_publishing(self):
        redis = FakeRedis()
        proxy = make_proxy_server(redis, owner=False)
        status_key = RedisKeys.switch_status(CHANNEL_ID)
        redis.store[status_key] = "switched"

        deleted_before_publish = []
        original_publish = redis.publish

        def tracking_publish(channel, message):
            deleted_before_publish.append(status_key not in redis.store)
            original_publish(channel, message)

        redis.publish = tracking_publish

        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
             patch.object(cs_module, "STREAM_SWITCH_CONFIRM_TIMEOUT", 0.2), \
             patch.object(cs_module, "STREAM_SWITCH_POLL_INTERVAL", 0.05):
            result = ChannelService.change_stream_url(
                CHANNEL_ID, NEW_URL, "test-agent", target_stream_id=144065,
            )

        self.assertEqual(deleted_before_publish, [True])
        self.assertFalse(result["success"])
