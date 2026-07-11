"""Tests for catch-up playback session API and Redis helpers."""

import time
import uuid
from unittest.mock import MagicMock, patch

from django.http import HttpResponse
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import M3UAccount
from apps.timeshift import sessions, views
from apps.timeshift.redis_keys import TimeshiftRedisKeys
from apps.timeshift.tests.test_views import _proxy_url
from rest_framework.test import APIRequestFactory, force_authenticate


class FakeRedisSessionStore:
    """Minimal Redis stand-in for session module tests."""

    def __init__(self):
        self.store = {}
        self.ttl = {}

    def hset(self, key, mapping=None, **kwargs):
        if mapping is None:
            mapping = kwargs
        else:
            mapping = {**mapping, **kwargs}
        bucket = self.store.setdefault(key, {})
        bucket.update({k: str(v) for k, v in mapping.items()})

    def hgetall(self, key):
        return dict(self.store.get(key, {}))

    def expire(self, key, seconds):
        self.ttl[key] = seconds

    def exists(self, key):
        return key in self.store and bool(self.store[key])

    def delete(self, key):
        self.store.pop(key, None)
        self.ttl.pop(key, None)
        return 1


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "catchup-session-tests",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
            "apps.accounts.authentication.ApiKeyAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "apps.accounts.permissions.IsAdmin",
        ],
    },
)
class CatchupSessionApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            username="catchup-session-user",
            user_level=User.UserLevel.STANDARD,
        )
        cls.other = User.objects.create(
            username="catchup-session-other",
            user_level=User.UserLevel.STANDARD,
        )
        cls.account = M3UAccount.objects.create(
            name="catchup-session-acct",
            server_url="http://example.test",
            account_type="XC",
            is_active=True,
        )
        cls.channel = Channel.objects.create(
            name="Catchup Session Channel",
            is_catchup=True,
            catchup_days=7,
        )
        cls.stream = Stream.objects.create(
            name="catchup-session-stream",
            url="http://example.test/live",
            m3u_account=cls.account,
            is_catchup=True,
            catchup_days=7,
            custom_properties={"stream_id": "111"},
        )
        ChannelStream.objects.create(
            channel=cls.channel, stream=cls.stream, order=0,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.redis = FakeRedisSessionStore()

    def _create_url(self):
        return "/api/catchup/sessions/"

    @patch.object(sessions.RedisClient, "get_client")
    @patch("apps.timeshift.api_views.network_access_allowed", return_value=True)
    def test_post_creates_session_without_start_in_playback_url(self, _net, redis_mock):
        redis_mock.return_value = self.redis
        response = self.client.post(
            self._create_url(),
            {
                "channel_uuid": str(self.channel.uuid),
                "start": "2026-06-08T17:00:00Z",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertGreater(len(data["session_id"]), 8)
        self.assertIn(f"session_id={data['session_id']}", data["playback_url"])
        self.assertNotIn("start=", data["playback_url"])
        self.assertEqual(data["channel_uuid"], str(self.channel.uuid))
        self.assertEqual(data["start"], "2026-06-08T17:00:00Z")
        self.assertGreater(data["expires_at"], int(time.time()))

    @patch.object(sessions.RedisClient, "get_client")
    @patch("apps.timeshift.api_views.network_access_allowed", return_value=True)
    def test_post_rejects_non_catchup_channel(self, _net, redis_mock):
        redis_mock.return_value = self.redis
        plain = Channel.objects.create(name="no-catchup")
        response = self.client.post(
            self._create_url(),
            {"channel_uuid": str(plain.uuid), "start": "2026-06-08T17:00:00Z"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch.object(sessions.RedisClient, "get_client")
    @patch("apps.timeshift.api_views.network_access_allowed", return_value=True)
    def test_delete_revokes_own_session(self, _net, redis_mock):
        redis_mock.return_value = self.redis
        created = self.client.post(
            self._create_url(),
            {
                "channel_uuid": str(self.channel.uuid),
                "start": "2026-06-08T17:00:00Z",
            },
            format="json",
        )
        session_id = created.json()["session_id"]
        deleted = self.client.delete(f"/api/catchup/sessions/{session_id}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(sessions.get_catchup_session(session_id))

    @patch.object(sessions.RedisClient, "get_client")
    @patch("apps.timeshift.api_views.network_access_allowed", return_value=True)
    def test_delete_rejects_other_users_session(self, _net, redis_mock):
        redis_mock.return_value = self.redis
        created = self.client.post(
            self._create_url(),
            {
                "channel_uuid": str(self.channel.uuid),
                "start": "2026-06-08T17:00:00Z",
            },
            format="json",
        )
        session_id = created.json()["session_id"]
        self.client.force_authenticate(user=self.other)
        deleted = self.client.delete(f"/api/catchup/sessions/{session_id}/")
        self.assertEqual(deleted.status_code, 404)


class CatchupSessionResolveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            username="catchup-resolve-user",
            user_level=User.UserLevel.STANDARD,
        )
        cls.channel = Channel.objects.create(
            name="resolve-channel",
            is_catchup=True,
        )

    def setUp(self):
        self.redis = FakeRedisSessionStore()

    @patch.object(sessions.RedisClient, "get_client")
    def test_resolve_prefers_pool_user_id(self, redis_mock):
        redis_mock.return_value = self.redis
        session_id = sessions.mint_catchup_session_id()
        self.redis.hset(
            TimeshiftRedisKeys.api_session(session_id),
            mapping={
                "user_id": "999",
                "channel_uuid": str(self.channel.uuid),
                "channel_id": str(self.channel.id),
                "start": "2026-06-08T17:00:00Z",
                "created_at": "1",
            },
        )
        self.redis.hset(
            TimeshiftRedisKeys.pool(session_id),
            mapping={"user_id": str(self.user.id)},
        )
        resolved = sessions.resolve_catchup_playback(session_id, self.channel.uuid)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[0].id, self.user.id)
        self.assertEqual(resolved[1], "2026-06-08T17:00:00Z")
        self.assertEqual(
            self.redis.ttl[TimeshiftRedisKeys.api_session(session_id)],
            sessions.SESSION_IDLE_TTL_SECONDS,
        )

    @patch.object(sessions.RedisClient, "get_client")
    def test_resolve_rejects_wrong_channel(self, redis_mock):
        redis_mock.return_value = self.redis
        session_id = sessions.mint_catchup_session_id()
        self.redis.hset(
            TimeshiftRedisKeys.api_session(session_id),
            mapping={
                "user_id": str(self.user.id),
                "channel_uuid": str(self.channel.uuid),
                "channel_id": str(self.channel.id),
                "start": "2026-06-08T17:00:00Z",
                "created_at": "1",
            },
        )
        other_uuid = uuid.uuid4()
        self.assertIsNone(
            sessions.resolve_catchup_playback(session_id, other_uuid),
        )


class CatchupProxySessionAuthTests(TestCase):
    """Playback via API session without JWT."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.channel_uuid = uuid.uuid4()

    @patch.object(views, "resolve_catchup_playback")
    @patch.object(views, "network_access_allowed", return_value=True)
    @patch.object(views, "_serve_catchup", return_value=HttpResponse("ok"))
    @patch.object(views, "_user_can_access_channel", return_value=True)
    @patch.object(views, "Channel")
    def test_session_auth_without_jwt(
        self, channel_cls, _access, serve, _net, resolve_mock,
    ):
        user = MagicMock(id=42, is_authenticated=False)
        resolve_mock.return_value = (user, "2026-06-08T17:00:00Z")
        channel_cls.objects.get.return_value = MagicMock(
            id=8, uuid=self.channel_uuid,
        )
        request = self.factory.get(
            f"/proxy/catchup/{self.channel_uuid}?session_id=test",
        )
        response = views.catchup_proxy(request, self.channel_uuid)
        self.assertEqual(response.status_code, 200)
        serve.assert_called_once()
        _args, kwargs = serve.call_args
        self.assertEqual(_args[3], "2026-06-08T17:00:00Z")

    @patch.object(views, "resolve_catchup_playback", return_value=None)
    @patch.object(views, "network_access_allowed", return_value=True)
    def test_expired_session_without_jwt_returns_401(self, _net, _resolve):
        request = self.factory.get(
            f"/proxy/catchup/{self.channel_uuid}?session_id=gone",
        )
        response = views.catchup_proxy(request, self.channel_uuid)
        self.assertEqual(response.status_code, 401)

    @patch.object(views, "resolve_catchup_playback")
    @patch.object(views, "network_access_allowed", return_value=True)
    def test_mismatched_jwt_and_session_returns_403(self, _net, resolve_mock):
        resolve_mock.return_value = (MagicMock(id=1), "2026-06-08T17:00:00Z")
        request = self.factory.get(
            f"/proxy/catchup/{self.channel_uuid}?session_id=test",
        )
        other = MagicMock(id=2, is_authenticated=True)
        force_authenticate(request, user=other)
        response = views.catchup_proxy(request, self.channel_uuid)
        self.assertEqual(response.status_code, 403)

    @patch.object(views, "network_access_allowed", return_value=True)
    @patch.object(views, "_serve_catchup", return_value=HttpResponse("ok"))
    @patch.object(views, "_user_can_access_channel", return_value=True)
    @patch.object(views, "Channel")
    def test_legacy_jwt_start_still_works(self, channel_cls, _access, serve, _net):
        user = MagicMock(id=1, is_authenticated=True)
        channel_cls.objects.get.return_value = MagicMock(
            id=8, uuid=self.channel_uuid,
        )
        request = self.factory.get(
            f"/proxy/catchup/{self.channel_uuid}?start=2026-06-08T17:00:00Z",
        )
        force_authenticate(request, user=user)
        response = views.catchup_proxy(request, self.channel_uuid)
        self.assertEqual(response.status_code, 200)
        serve.assert_called_once()

    def test_xc_path_unchanged(self):
        request = self.factory.get(_proxy_url())
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=1)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "_serve_catchup", return_value=HttpResponse("ok")) as serve:
            channel_cls.objects.get.return_value = MagicMock(id=8)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 200)
        serve.assert_called_once()
