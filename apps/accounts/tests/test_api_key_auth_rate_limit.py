"""API-key failed-auth rate limiting (Redis-backed, failures only)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from apps.accounts.throttling import ApiKeyFailedAuthRateThrottle
from core.models import NotificationDismissal, SystemNotification
from core.utils import (
    API_KEY_AUTH_LOCKOUT_COOLDOWN_CACHE_KEY,
    API_KEY_AUTH_LOCKOUT_NOTICE_KEY,
)

User = get_user_model()

API_KEY_AUTH_FAILURE_LIMIT = int(
    api_settings.DEFAULT_THROTTLE_RATES["api_key_auth"].split("/")[0]
)
ME_URL = "/api/accounts/users/me/"


class ApiKeyFailedAuthRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.user = User.objects.create_user(
            username="keyuser",
            password="django-password",
            user_level=10,
            api_key="valid-test-api-key",
        )

    def tearDown(self):
        cache.clear()

    def _get(self, api_key=None, authorization=None, **extra):
        headers = {}
        if api_key is not None:
            headers["HTTP_X_API_KEY"] = api_key
        if authorization is not None:
            headers["HTTP_AUTHORIZATION"] = authorization
        return self.api.get(ME_URL, **headers, **extra)

    def test_failures_trip_rate_limit_success_does_not_count(self):
        for _ in range(API_KEY_AUTH_FAILURE_LIMIT - 1):
            response = self._get(api_key="wrong-key")
            self.assertEqual(response.status_code, 401)

        response = self._get(api_key="valid-test-api-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "keyuser")

        # One more failure reaches the limit (success did not consume a slot).
        response = self._get(api_key="wrong-key")
        self.assertEqual(response.status_code, 401)

        response = self._get(api_key="wrong-key")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

    def test_valid_key_from_locked_ip_is_still_429(self):
        for _ in range(API_KEY_AUTH_FAILURE_LIMIT):
            response = self._get(api_key="wrong-key")
            self.assertEqual(response.status_code, 401)

        response = self._get(api_key="valid-test-api-key")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

    def test_inactive_user_counts_as_failure(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        for _ in range(API_KEY_AUTH_FAILURE_LIMIT):
            response = self._get(api_key="valid-test-api-key")
            self.assertEqual(response.status_code, 401)

        response = self._get(api_key="valid-test-api-key")
        self.assertEqual(response.status_code, 429)

    def test_missing_key_does_not_consume_budget(self):
        for _ in range(API_KEY_AUTH_FAILURE_LIMIT + 2):
            response = self._get()
            self.assertIn(response.status_code, (401, 403))

        for _ in range(API_KEY_AUTH_FAILURE_LIMIT):
            response = self._get(api_key="wrong-key")
            self.assertEqual(response.status_code, 401)

        response = self._get(api_key="wrong-key")
        self.assertEqual(response.status_code, 429)

    def test_bearer_authorization_does_not_consume_api_key_budget(self):
        for _ in range(API_KEY_AUTH_FAILURE_LIMIT + 2):
            response = self._get(authorization="Bearer not-a-real-jwt")
            self.assertEqual(response.status_code, 401)

        for _ in range(API_KEY_AUTH_FAILURE_LIMIT):
            response = self._get(api_key="wrong-key")
            self.assertEqual(response.status_code, 401)

        response = self._get(api_key="wrong-key")
        self.assertEqual(response.status_code, 429)

    def test_authorization_apikey_scheme_is_throttled(self):
        for _ in range(API_KEY_AUTH_FAILURE_LIMIT):
            response = self._get(authorization="ApiKey wrong-key")
            self.assertEqual(response.status_code, 401)

        response = self._get(authorization="ApiKey wrong-key")
        self.assertEqual(response.status_code, 429)

    def test_non_utf8_apikey_authorization_is_401_not_500(self):
        # WSGI stores Authorization as a latin-1 str; non-UTF-8 ApiKey bytes
        # must not escape as UnicodeDecodeError / 500.
        response = self.api.get(
            ME_URL,
            HTTP_AUTHORIZATION="ApiKey " + "caf\xe9",
        )
        self.assertEqual(response.status_code, 401)

    def test_lockout_event_once_per_trip(self):
        with patch("core.utils.log_system_event") as log_event, patch(
            "core.utils.notify_api_key_auth_lockout_inbox"
        ) as inbox:
            for _ in range(API_KEY_AUTH_FAILURE_LIMIT):
                self._get(api_key="wrong-key")
            self.assertEqual(log_event.call_count, 1)
            self.assertEqual(
                log_event.call_args.kwargs["reason"],
                "API key rate limited",
            )
            self.assertEqual(
                log_event.call_args.kwargs["event_type"], "login_failed"
            )
            inbox.assert_called_once()

            self._get(api_key="wrong-key")
            self.assertEqual(log_event.call_count, 1)
            inbox.assert_called_once()

    def test_cache_key_uses_api_key_auth_scope_not_login(self):
        from django.test import RequestFactory

        request = RequestFactory().get(ME_URL)
        throttle = ApiKeyFailedAuthRateThrottle()
        key = throttle.get_cache_key(request, view=None)
        self.assertIn("api_key_auth", key)
        self.assertNotIn("login", key)
        self.assertNotIn("xc_auth", key)

    def test_varying_forwarded_for_prefix_shares_one_budget(self):
        for i in range(API_KEY_AUTH_FAILURE_LIMIT):
            response = self._get(
                api_key="wrong-key",
                HTTP_X_FORWARDED_FOR=f"{i}.{i}.{i}.{i}, 203.0.113.7",
            )
            self.assertEqual(response.status_code, 401)

        response = self._get(
            api_key="wrong-key",
            HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.7",
        )
        self.assertEqual(response.status_code, 429)


class ApiKeyAuthLockoutInboxTests(TestCase):
    def setUp(self):
        cache.clear()
        SystemNotification.objects.filter(
            notification_key=API_KEY_AUTH_LOCKOUT_NOTICE_KEY
        ).delete()
        self.api = APIClient()
        User.objects.create_user(
            username="keyuser",
            password="django-password",
            user_level=10,
            api_key="valid-test-api-key",
        )
        self.admin = User.objects.create_superuser(
            username="notify-admin",
            password="admin-password",
            user_level=10,
        )

    def tearDown(self):
        cache.clear()
        SystemNotification.objects.filter(
            notification_key=API_KEY_AUTH_LOCKOUT_NOTICE_KEY
        ).delete()

    def _trip_lockout(self):
        with patch("core.utils.send_websocket_notification") as ws:
            for _ in range(API_KEY_AUTH_FAILURE_LIMIT):
                self.api.get(ME_URL, HTTP_X_API_KEY="wrong-key")
            response = self.api.get(ME_URL, HTTP_X_API_KEY="wrong-key")
        return ws, response

    def test_inbox_created_once_per_cooldown(self):
        ws, response = self._trip_lockout()
        self.assertEqual(response.status_code, 429)
        notice = SystemNotification.objects.get(
            notification_key=API_KEY_AUTH_LOCKOUT_NOTICE_KEY
        )
        self.assertEqual(
            notice.title, "API key authentication rate limit triggered"
        )
        self.assertTrue(notice.admin_only)
        self.assertEqual(notice.action_data.get("action_url"), "/stats")
        ws.assert_called_once()
        self.assertTrue(cache.get(API_KEY_AUTH_LOCKOUT_COOLDOWN_CACHE_KEY))

        first_id = notice.id
        with patch("core.utils.send_websocket_notification") as ws2:
            self.api.get(ME_URL, HTTP_X_API_KEY="wrong-key")
        self.assertEqual(
            SystemNotification.objects.get(
                notification_key=API_KEY_AUTH_LOCKOUT_NOTICE_KEY
            ).id,
            first_id,
        )
        ws2.assert_not_called()

    def test_dismiss_does_not_block_notice_after_cooldown(self):
        self._trip_lockout()
        notice = SystemNotification.objects.get(
            notification_key=API_KEY_AUTH_LOCKOUT_NOTICE_KEY
        )
        NotificationDismissal.objects.create(user=self.admin, notification=notice)
        old_id = notice.id

        cache.clear()

        with patch("core.utils.send_websocket_notification"):
            for _ in range(API_KEY_AUTH_FAILURE_LIMIT):
                self.api.get(ME_URL, HTTP_X_API_KEY="wrong-key")
            self.api.get(ME_URL, HTTP_X_API_KEY="wrong-key")

        new_notice = SystemNotification.objects.get(
            notification_key=API_KEY_AUTH_LOCKOUT_NOTICE_KEY
        )
        self.assertNotEqual(new_notice.id, old_id)
        self.assertFalse(
            NotificationDismissal.objects.filter(notification=new_notice).exists()
        )
