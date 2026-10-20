from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.channels.tests.test_get_stream_assignment import FakeAssignmentRedis
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

RELEASE_SLOT = "apps.proxy.live_proxy.slot_release.release_profile_slot"


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

    @patch(RELEASE_SLOT)
    @patch("apps.channels.models.RedisClient.get_client")
    def test_repeated_release_frees_the_slot_once(self, mock_get_client, mock_release):
        mock_get_client.return_value = self.redis

        self.assertTrue(self.channel.release_stream())
        self.assertFalse(self.channel.release_stream())

        mock_release.assert_called_once_with(self.profile.id, self.redis)

    @patch(RELEASE_SLOT)
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

    @patch(RELEASE_SLOT)
    @patch("apps.channels.models.RedisClient.get_client")
    def test_channel_release_and_metadata_fallback_free_the_slot_once(
        self, mock_get_client, mock_release
    ):
        mock_get_client.return_value = self.redis
        server = self._server()
        self.redis.after_profile_read = lambda: server._release_profile_slot_from_redis_metadata(
            str(self.channel.uuid)
        )

        self.channel.release_stream()

        mock_release.assert_called_once_with(self.profile.id, self.redis)

    @patch(RELEASE_SLOT)
    def test_overlapping_metadata_fallbacks_free_the_slot_once(self, mock_release):
        first_worker = self._server()
        second_worker = self._server()
        self.redis.after_profile_read = lambda: second_worker._release_profile_slot_from_redis_metadata(
            str(self.channel.uuid)
        )

        first_worker._release_profile_slot_from_redis_metadata(str(self.channel.uuid))

        mock_release.assert_called_once_with(self.profile.id, self.redis)

    @patch(RELEASE_SLOT)
    @patch("apps.channels.models.RedisClient.get_client")
    def test_stale_reclaim_then_teardown_frees_the_slot_once(
        self, mock_get_client, mock_release
    ):
        mock_get_client.return_value = self.redis
        self.redis.hset(
            self.metadata_key,
            {ChannelMetadataField.STATE: ChannelState.STOPPING},
        )

        self.channel._release_stale_stream_assignment(self.redis, self.stream.id)
        self.assertFalse(self.channel.release_stream())

        mock_release.assert_called_once_with(self.profile.id, self.redis)
        self.assertIsNone(
            self.redis.hget(self.metadata_key, ChannelMetadataField.M3U_PROFILE)
        )

    @patch(RELEASE_SLOT)
    @patch("apps.channels.models.RedisClient.get_client")
    def test_release_failure_restores_m3u_profile_token(
        self, mock_get_client, mock_release
    ):
        mock_get_client.return_value = self.redis
        mock_release.side_effect = RuntimeError("counter write failed")

        with self.assertRaises(RuntimeError):
            self.channel.release_stream()

        self.assertEqual(
            self.redis.hget(self.metadata_key, ChannelMetadataField.M3U_PROFILE),
            str(self.profile.id),
        )
        mock_release.side_effect = None
        self.assertTrue(self.channel.release_stream())
        mock_release.assert_called_with(self.profile.id, self.redis)


class OverlappingStreamPreviewReleaseTests(TestCase):
    """Preview stops use :preview / :p{id} keys and share the m3u_profile token."""

    def setUp(self):
        self.redis = InterleavingRedis()
        account = M3UAccount.objects.create(
            name="preview-teardown-race",
            account_type="XC",
            username="user",
            password="pass",
            max_streams=3,
        )
        self.profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        self.stream = Stream.objects.create(
            name="Preview Race Stream",
            url="http://example.com/live/user/pass/2.ts",
            m3u_account=account,
            stream_hash="preview-race",
        )
        self.preview_id = f"{self.stream.stream_hash}.p{self.profile.id}"
        self.scoped_key = f"stream_profile:{self.stream.id}:p{self.profile.id}"
        self.default_preview_key = Stream.preview_profile_key(self.stream.id)
        self.scoped_metadata_key = RedisKeys.channel_metadata(self.preview_id)
        self.default_metadata_key = RedisKeys.channel_metadata(self.stream.stream_hash)

        self.redis.set(self.scoped_key, self.profile.id)
        self.redis.hset(
            self.scoped_metadata_key,
            {
                ChannelMetadataField.STREAM_ID: str(self.stream.id),
                ChannelMetadataField.M3U_PROFILE: str(self.profile.id),
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

    def _seed_default_preview(self):
        self.redis._strings.pop(self.scoped_key, None)
        self.redis._hashes.pop(self.scoped_metadata_key, None)
        self.redis.set(self.default_preview_key, self.profile.id)
        self.redis.hset(
            self.default_metadata_key,
            {
                ChannelMetadataField.STREAM_ID: str(self.stream.id),
                ChannelMetadataField.M3U_PROFILE: str(self.profile.id),
            },
        )

    @patch(RELEASE_SLOT)
    @patch("apps.channels.models.RedisClient.get_client")
    def test_overlapping_scoped_preview_releases_free_the_slot_once(
        self, mock_get_client, mock_release
    ):
        mock_get_client.return_value = self.redis
        other = Stream.objects.get(pk=self.stream.pk)
        self.redis.after_profile_read = lambda: other.release_stream(
            m3u_profile_id=self.profile.id
        )

        self.assertTrue(self.stream.release_stream(m3u_profile_id=self.profile.id))

        mock_release.assert_called_once_with(self.profile.id, self.redis)
        self.assertIsNone(
            self.redis.hget(self.scoped_metadata_key, ChannelMetadataField.M3U_PROFILE)
        )

    @patch(RELEASE_SLOT)
    @patch("apps.channels.models.RedisClient.get_client")
    def test_scoped_preview_and_metadata_fallback_free_the_slot_once(
        self, mock_get_client, mock_release
    ):
        mock_get_client.return_value = self.redis
        server = self._server()
        self.redis.after_profile_read = lambda: server._release_profile_slot_from_redis_metadata(
            self.preview_id
        )

        self.stream.release_stream(m3u_profile_id=self.profile.id)

        mock_release.assert_called_once_with(self.profile.id, self.redis)
        self.assertFalse(self.redis.exists(self.scoped_key))

    @patch(RELEASE_SLOT)
    @patch("apps.channels.models.RedisClient.get_client")
    def test_overlapping_default_preview_releases_free_the_slot_once(
        self, mock_get_client, mock_release
    ):
        self._seed_default_preview()
        mock_get_client.return_value = self.redis
        other = Stream.objects.get(pk=self.stream.pk)
        self.redis.after_profile_read = other.release_stream

        self.assertTrue(self.stream.release_stream())

        mock_release.assert_called_once_with(self.profile.id, self.redis)
        self.assertIsNone(
            self.redis.hget(self.default_metadata_key, ChannelMetadataField.M3U_PROFILE)
        )

    @patch(RELEASE_SLOT)
    @patch("apps.channels.models.RedisClient.get_client")
    def test_default_preview_and_metadata_fallback_free_the_slot_once(
        self, mock_get_client, mock_release
    ):
        self._seed_default_preview()
        mock_get_client.return_value = self.redis
        server = self._server()
        self.redis.after_profile_read = lambda: server._release_profile_slot_from_redis_metadata(
            self.stream.stream_hash
        )

        self.stream.release_stream()

        mock_release.assert_called_once_with(self.profile.id, self.redis)
        self.assertFalse(self.redis.exists(self.default_preview_key))
