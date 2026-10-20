from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.channels.tests.test_get_stream_assignment import FakeAssignmentRedis
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer


class InterleavingRedis(FakeAssignmentRedis):
    def __init__(self):
        super().__init__()
        self.after_profile_read = None

    def _profile_touched(self, key):
        if key.startswith("stream_profile:") and self.after_profile_read:
            hook, self.after_profile_read = self.after_profile_read, None
            hook()

    def get(self, key):
        value = super().get(key)
        self._profile_touched(key)
        return value

    def getdel(self, key):
        value = super().get(key)
        self._strings.pop(key, None)
        self._profile_touched(key)
        return value

    def delete(self, key):
        deleted = super().delete(key)
        self._profile_touched(key)
        return deleted


class OverlappingTeardownReleaseTests(TestCase):
    def setUp(self):
        self.redis = InterleavingRedis()
        account = M3UAccount.objects.create(
            name="teardown-race",
            account_type="XC",
            username="user",
            password="pass",
            max_streams=3,
        )
        self.profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        self.stream = Stream.objects.create(
            name="Race Stream",
            url="http://example.com/live/user/pass/1.ts",
            m3u_account=account,
        )
        self.channel = Channel.objects.create(channel_number=601, name="Race Channel")
        ChannelStream.objects.create(channel=self.channel, stream=self.stream, order=0)
        self.metadata_key = RedisKeys.channel_metadata(str(self.channel.uuid))

        self.redis.set(f"channel_stream:{self.channel.id}", self.stream.id)
        self.redis.set(f"stream_profile:{self.stream.id}", self.profile.id)
        self.redis.hset(
            self.metadata_key,
            {
                ChannelMetadataField.STREAM_ID: str(self.stream.id),
                ChannelMetadataField.M3U_PROFILE: str(self.profile.id),
                ChannelMetadataField.CHANNEL_ID: str(self.channel.id),
            },
        )

    def _server(self):
        with patch(
            "apps.proxy.live_proxy.server.RedisClient.get_client",
            return_value=MagicMock(),
        ):
            server = ProxyServer()
        server.redis_client = self.redis
        return server

    @patch("apps.channels.models.release_profile_slot")
    @patch("apps.channels.models.RedisClient.get_client")
    def test_repeated_release_frees_the_slot_once(self, mock_get_client, mock_release):
        mock_get_client.return_value = self.redis

        self.assertTrue(self.channel.release_stream())
        self.assertFalse(self.channel.release_stream())

        mock_release.assert_called_once_with(self.profile.id, self.redis)

    @patch("apps.channels.models.release_profile_slot")
    @patch("apps.channels.models.RedisClient.get_client")
    def test_overlapping_channel_releases_free_the_slot_once(
        self, mock_get_client, mock_release
    ):
        mock_get_client.return_value = self.redis
        other_worker = Channel.objects.get(pk=self.channel.pk)
        self.redis.after_profile_read = other_worker.release_stream

        self.channel.release_stream()

        mock_release.assert_called_once_with(self.profile.id, self.redis)
        self.assertIsNone(self.redis.hget(self.metadata_key, ChannelMetadataField.M3U_PROFILE))
        self.assertIsNone(self.redis.hget(self.metadata_key, ChannelMetadataField.STREAM_ID))

    @patch("apps.m3u.connection_pool.release_profile_slot")
    @patch("apps.channels.models.release_profile_slot")
    @patch("apps.channels.models.RedisClient.get_client")
    def test_channel_release_and_metadata_fallback_free_the_slot_once(
        self, mock_get_client, mock_channel_release, mock_fallback_release
    ):
        mock_get_client.return_value = self.redis
        server = self._server()
        self.redis.after_profile_read = lambda: server._release_profile_slot_from_redis_metadata(
            str(self.channel.uuid)
        )

        self.channel.release_stream()

        self.assertEqual(
            mock_channel_release.call_count + mock_fallback_release.call_count, 1
        )

    @patch("apps.m3u.connection_pool.release_profile_slot")
    def test_overlapping_metadata_fallbacks_free_the_slot_once(self, mock_release):
        first_worker = self._server()
        second_worker = self._server()
        self.redis.after_profile_read = lambda: second_worker._release_profile_slot_from_redis_metadata(
            str(self.channel.uuid)
        )

        first_worker._release_profile_slot_from_redis_metadata(str(self.channel.uuid))

        mock_release.assert_called_once_with(self.profile.id, self.redis)
