"""Metadata fallback must not free a channel slot while releasing a preview."""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.channels.models import Stream
from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer


class _Redis:
    def __init__(self):
        self.strings = {}
        self.hashes = {}

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, mapping=None, **kwargs):
        bucket = self.hashes.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        bucket.update(kwargs)

    def hdel(self, key, *fields):
        bucket = self.hashes.get(key)
        if not bucket:
            return 0
        removed = 0
        for field in fields:
            if field in bucket:
                del bucket[field]
                removed += 1
        return removed

    def delete(self, key):
        self.strings.pop(key, None)
        return 1


def _server(redis):
    server = ProxyServer.__new__(ProxyServer)
    server.redis_client = redis
    return server


class MetadataSlotReleaseTests(SimpleTestCase):
    def setUp(self):
        self.redis = _Redis()
        self.stream_id = 42
        self.profile_id = 7
        self.channel_pk = 3
        self.bare_key = f"stream_profile:{self.stream_id}"
        self.preview_key = Stream.preview_profile_key(self.stream_id)
        self.scoped_key = f"stream_profile:{self.stream_id}:p{self.profile_id}"
        self.channel_stream_key = f"channel_stream:{self.channel_pk}"

    def _seed_channel_keys(self):
        self.redis.strings[self.bare_key] = self.profile_id
        self.redis.strings[self.preview_key] = self.profile_id
        self.redis.strings[self.scoped_key] = self.profile_id
        self.redis.strings[self.channel_stream_key] = self.stream_id

    def _seed_metadata(self, worker_id):
        self.redis.hset(
            RedisKeys.channel_metadata(worker_id),
            {
                ChannelMetadataField.STREAM_ID: str(self.stream_id),
                ChannelMetadataField.M3U_PROFILE: str(self.profile_id),
                ChannelMetadataField.CHANNEL_ID: str(self.channel_pk),
                ChannelMetadataField.STATE: "stopped",
            },
        )

    @patch("apps.proxy.live_proxy.slot_release.release_profile_slot")
    def test_channel_uuid_keeps_preview_keys(self, mock_release):
        worker_id = "11111111-2222-3333-4444-555555555555"
        self._seed_channel_keys()
        self._seed_metadata(worker_id)

        released = _server(self.redis)._release_profile_slot_from_redis_metadata(
            worker_id
        )

        self.assertTrue(released)
        mock_release.assert_called_once_with(self.profile_id, self.redis)
        self.assertNotIn(self.bare_key, self.redis.strings)
        self.assertNotIn(self.channel_stream_key, self.redis.strings)
        self.assertIn(self.preview_key, self.redis.strings)
        self.assertIn(self.scoped_key, self.redis.strings)
        metadata = self.redis.hashes[RedisKeys.channel_metadata(worker_id)]
        self.assertNotIn(ChannelMetadataField.M3U_PROFILE, metadata)
        self.assertEqual(metadata[ChannelMetadataField.STATE], "stopped")

    @patch("apps.proxy.live_proxy.slot_release.release_profile_slot")
    def test_stream_hash_deletes_preview_key_only(self, mock_release):
        worker_id = "a" * 64
        self._seed_channel_keys()
        self._seed_metadata(worker_id)

        released = _server(self.redis)._release_profile_slot_from_redis_metadata(
            worker_id
        )

        self.assertTrue(released)
        mock_release.assert_called_once_with(self.profile_id, self.redis)
        self.assertNotIn(self.preview_key, self.redis.strings)
        self.assertIn(self.bare_key, self.redis.strings)
        self.assertIn(self.channel_stream_key, self.redis.strings)
        self.assertIn(self.scoped_key, self.redis.strings)

    @patch("apps.proxy.live_proxy.slot_release.release_profile_slot")
    def test_scoped_worker_deletes_scoped_key_only(self, mock_release):
        worker_id = f"{'b' * 64}.p{self.profile_id}"
        self._seed_channel_keys()
        self._seed_metadata(worker_id)

        released = _server(self.redis)._release_profile_slot_from_redis_metadata(
            worker_id
        )

        self.assertTrue(released)
        mock_release.assert_called_once_with(self.profile_id, self.redis)
        self.assertNotIn(self.scoped_key, self.redis.strings)
        self.assertIn(self.bare_key, self.redis.strings)
        self.assertIn(self.preview_key, self.redis.strings)
        self.assertIn(self.channel_stream_key, self.redis.strings)

    @patch("apps.proxy.live_proxy.slot_release.release_profile_slot")
    def test_second_call_does_not_release_again(self, mock_release):
        worker_id = "c" * 64
        self._seed_channel_keys()
        self._seed_metadata(worker_id)
        server = _server(self.redis)

        self.assertTrue(server._release_profile_slot_from_redis_metadata(worker_id))
        self.assertFalse(server._release_profile_slot_from_redis_metadata(worker_id))
        mock_release.assert_called_once()
