"""Tests for Channel.get_stream() assignment reuse and stale cleanup."""

from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.redis_keys import RedisKeys


class FakeAssignmentRedis:
    """In-memory Redis for channel_stream assignment tests."""

    def __init__(self):
        self._strings = {}
        self._hashes = {}

    def _decode(self, value):
        if isinstance(value, bytes):
            return value.decode()
        return value

    def get(self, key):
        value = self._strings.get(key)
        if value is None:
            return None
        if isinstance(value, int):
            return str(value).encode()
        return str(value).encode()

    def set(self, key, value):
        self._strings[key] = value

    def delete(self, key):
        self._strings.pop(key, None)
        self._hashes.pop(key, None)

    def exists(self, key):
        return key in self._strings or key in self._hashes

    def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    def hset(self, key, mapping=None, **kwargs):
        bucket = self._hashes.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        bucket.update(kwargs)

    def incr(self, key):
        current = int(self._decode(self.get(key)) or 0)
        current += 1
        self._strings[key] = current
        return current

    def decr(self, key):
        current = int(self._decode(self.get(key)) or 0)
        current -= 1
        self._strings[key] = current
        return current


class ChannelGetStreamAssignmentTests(TestCase):
    def setUp(self):
        self.redis = FakeAssignmentRedis()
        self.account = M3UAccount.objects.create(
            name="assignment-test",
            account_type="XC",
            username="user",
            password="pass",
            max_streams=5,
        )
        self.profile = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )
        self.profile.max_streams = 2
        self.profile.save()

        self.stream = Stream.objects.create(
            name="Test Stream",
            url="http://example.com/live/user/pass/1.ts",
            m3u_account=self.account,
        )
        self.channel = Channel.objects.create(channel_number=501, name="Assignment Ch")
        ChannelStream.objects.create(channel=self.channel, stream=self.stream, order=0)

        self.metadata_key = RedisKeys.channel_metadata(str(self.channel.uuid))

    def _seed_assignment(self):
        self.redis.set(f"channel_stream:{self.channel.id}", self.stream.id)
        self.redis.set(f"stream_profile:{self.stream.id}", self.profile.id)

    @patch("apps.channels.models.RedisClient.get_client")
    @patch("apps.channels.models.reserve_profile_slot")
    def test_reuses_assignment_when_proxy_active(
        self, mock_reserve, mock_get_client
    ):
        mock_get_client.return_value = self.redis
        self._seed_assignment()
        self.redis.hset(
            self.metadata_key,
            {ChannelMetadataField.STATE: ChannelState.ACTIVE},
        )

        stream_id, profile_id, error, slot_reserved = self.channel.get_stream()

        self.assertEqual(stream_id, self.stream.id)
        self.assertEqual(profile_id, self.profile.id)
        self.assertIsNone(error)
        self.assertFalse(slot_reserved)
        mock_reserve.assert_not_called()

    @patch("apps.channels.models.RedisClient.get_client")
    @patch("apps.channels.models.reserve_profile_slot")
    def test_reuses_assignment_during_init_before_metadata(
        self, mock_reserve, mock_get_client
    ):
        mock_get_client.return_value = self.redis
        self._seed_assignment()

        stream_id, profile_id, error, slot_reserved = self.channel.get_stream()

        self.assertEqual(stream_id, self.stream.id)
        self.assertEqual(profile_id, self.profile.id)
        self.assertIsNone(error)
        self.assertFalse(slot_reserved)
        mock_reserve.assert_not_called()

    @patch("apps.channels.models.RedisClient.get_client")
    @patch("apps.channels.models.release_profile_slot")
    @patch("apps.channels.models.reserve_profile_slot")
    def test_releases_stale_assignment_when_proxy_stopped(
        self, mock_reserve, mock_release, mock_get_client
    ):
        mock_get_client.return_value = self.redis
        mock_reserve.return_value = (True, 1, None)
        self._seed_assignment()
        self.redis.hset(
            self.metadata_key,
            {ChannelMetadataField.STATE: ChannelState.STOPPED},
        )

        stream_id, profile_id, error, slot_reserved = self.channel.get_stream()

        mock_release.assert_called_once_with(self.profile.id, self.redis)
        mock_reserve.assert_called_once()
        self.assertEqual(stream_id, self.stream.id)
        self.assertEqual(profile_id, self.profile.id)
        self.assertTrue(slot_reserved)

    @patch("apps.channels.models.RedisClient.get_client")
    def test_stream_assignment_is_reusable_during_init_pending(self, mock_get_client):
        mock_get_client.return_value = self.redis
        self._seed_assignment()

        self.assertTrue(
            self.channel._stream_assignment_is_reusable(self.redis, self.stream.id)
        )

    @patch("apps.channels.models.RedisClient.get_client")
    def test_stream_assignment_not_reusable_when_stopped(self, mock_get_client):
        mock_get_client.return_value = self.redis
        self._seed_assignment()
        self.redis.hset(
            self.metadata_key,
            {ChannelMetadataField.STATE: ChannelState.STOPPED},
        )

        self.assertFalse(
            self.channel._stream_assignment_is_reusable(self.redis, self.stream.id)
        )
