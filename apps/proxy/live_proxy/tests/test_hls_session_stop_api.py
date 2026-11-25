"""Tests for DELETE /api/proxy/hls/sessions/<token>/."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.proxy.live_proxy.output.hls import session as hls_session
from apps.proxy.live_proxy.redis_keys import RedisKeys


TOKEN = "opaque-hls-stop-token"
CHANNEL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLIENT_ID = "client_hls_1"


@override_settings(
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
class HlsSessionStopApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create(
            username="hls-stop-owner",
            user_level=User.UserLevel.STANDARD,
        )
        cls.other = User.objects.create(
            username="hls-stop-other",
            user_level=User.UserLevel.STANDARD,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.redis = MagicMock()
        self.url = f"/api/proxy/hls/sessions/{TOKEN}/"

    def _session_hash(self, user_id):
        return {
            "channel_id": CHANNEL_ID,
            "client_id": CLIENT_ID,
            "user_id": str(user_id),
        }

    def test_url_resolves(self):
        match = resolve(self.url)
        self.assertEqual(match.url_name, "hls-session-destroy")
        self.assertEqual(match.namespace, "api:hls")
        self.assertEqual(match.kwargs, {"token": TOKEN})

    @patch("apps.proxy.live_proxy.output.hls.api_views.ChannelService.stop_client")
    @patch("apps.proxy.live_proxy.output.hls.api_views.RedisClient.get_client")
    @patch(
        "apps.proxy.live_proxy.output.hls.api_views.network_access_allowed",
        return_value=True,
    )
    def test_owner_stop_returns_204(self, _net, redis_get, stop_client):
        redis_get.return_value = self.redis
        self.redis.hgetall.return_value = self._session_hash(self.owner.id)

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 204)
        stop_client.assert_called_once_with(CHANNEL_ID, CLIENT_ID)
        self.redis.hgetall.assert_called_with(RedisKeys.hls_session(TOKEN))

    @patch("apps.proxy.live_proxy.output.hls.api_views.ChannelService.stop_client")
    @patch("apps.proxy.live_proxy.output.hls.api_views.RedisClient.get_client")
    @patch(
        "apps.proxy.live_proxy.output.hls.api_views.network_access_allowed",
        return_value=True,
    )
    def test_non_owner_returns_404(self, _net, redis_get, stop_client):
        redis_get.return_value = self.redis
        self.redis.hgetall.return_value = self._session_hash(self.other.id)

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 404)
        stop_client.assert_not_called()

    @patch("apps.proxy.live_proxy.output.hls.api_views.ChannelService.stop_client")
    @patch("apps.proxy.live_proxy.output.hls.api_views.RedisClient.get_client")
    @patch(
        "apps.proxy.live_proxy.output.hls.api_views.network_access_allowed",
        return_value=True,
    )
    def test_anonymous_session_returns_404(self, _net, redis_get, stop_client):
        redis_get.return_value = self.redis
        self.redis.hgetall.return_value = self._session_hash(0)

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 404)
        stop_client.assert_not_called()

    @patch("apps.proxy.live_proxy.output.hls.api_views.ChannelService.stop_client")
    @patch("apps.proxy.live_proxy.output.hls.api_views.RedisClient.get_client")
    @patch(
        "apps.proxy.live_proxy.output.hls.api_views.network_access_allowed",
        return_value=True,
    )
    def test_unknown_token_returns_404(self, _net, redis_get, stop_client):
        redis_get.return_value = self.redis
        self.redis.hgetall.return_value = {}

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 404)
        stop_client.assert_not_called()

    def test_unauthenticated_is_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.delete(self.url)
        self.assertIn(response.status_code, (401, 403))


class HlsSessionOwnedByTests(SimpleTestCase):
    def test_owner_matches(self):
        self.assertTrue(
            hls_session.hls_session_owned_by(
                {"channel_id": CHANNEL_ID, "client_id": CLIENT_ID, "user_id": "7"},
                7,
            )
        )

    def test_anonymous_does_not_match_real_user(self):
        self.assertFalse(
            hls_session.hls_session_owned_by(
                {"channel_id": CHANNEL_ID, "client_id": CLIENT_ID, "user_id": "0"},
                7,
            )
        )

    def test_missing_or_empty_session(self):
        self.assertFalse(hls_session.hls_session_owned_by(None, 7))
        self.assertFalse(hls_session.hls_session_owned_by({}, 7))
