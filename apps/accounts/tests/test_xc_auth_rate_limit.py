"""XC failed-credential rate limiting (Redis-backed, failures only)."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase
from rest_framework.settings import api_settings

from apps.accounts.models import User
from apps.accounts.throttling import XcFailedAuthRateThrottle
from apps.accounts.xc_auth import authorize_xc_client
from core.models import NotificationDismissal, SystemNotification
from core.utils import (
    XC_AUTH_LOCKOUT_COOLDOWN_CACHE_KEY,
    XC_AUTH_LOCKOUT_NOTICE_KEY,
)

# DRF copies DEFAULT_THROTTLE_RATES onto the throttle class at import, so
# override_settings does not change the live rate. Read the configured limit.
XC_AUTH_FAILURE_LIMIT = int(
    api_settings.DEFAULT_THROTTLE_RATES["xc_auth"].split("/")[0]
)


class XcFailedAuthRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="alice",
            password="django-password",
            custom_properties={"xc_password": "secret"},
        )

    def tearDown(self):
        cache.clear()

    def _request(self, forwarded_for=None):
        kwargs = {}
        if forwarded_for is not None:
            kwargs["HTTP_X_FORWARDED_FOR"] = forwarded_for
        return self.factory.get("/live/alice/secret/1.ts", **kwargs)

    def _authorize(self, request, password="wrong"):
        with patch(
            "apps.accounts.xc_auth.network_access_allowed", return_value=True
        ):
            return authorize_xc_client(request, "alice", password, "XC_API")

    def test_failures_trip_rate_limit_success_does_not_count(self):
        request = self._request()
        for _ in range(XC_AUTH_FAILURE_LIMIT - 1):
            user, error = self._authorize(request, password="wrong")
            self.assertIsNone(user)
            self.assertEqual(error.status_code, 401)

        user, error = self._authorize(request, password="secret")
        self.assertEqual(user.id, self.user.id)
        self.assertIsNone(error)

        # One more failure reaches the limit (success did not consume a slot).
        user, error = self._authorize(request, password="wrong")
        self.assertIsNone(user)
        self.assertEqual(error.status_code, 401)

        user, error = self._authorize(request, password="wrong")
        self.assertIsNone(user)
        self.assertEqual(error.status_code, 429)
        self.assertIn(b"Too many attempts", error.content)

    def test_network_deny_does_not_consume_budget(self):
        request = self._request()

        def deny_user(req, key, user=None):
            return user is None

        with patch(
            "apps.accounts.xc_auth.network_access_allowed", side_effect=deny_user
        ):
            for _ in range(XC_AUTH_FAILURE_LIMIT + 2):
                user, error = authorize_xc_client(
                    request, "alice", "wrong", "XC_API"
                )
                self.assertIsNone(user)
                self.assertEqual(error.status_code, 403)

        for _ in range(XC_AUTH_FAILURE_LIMIT):
            user, error = self._authorize(request, password="wrong")
            self.assertEqual(error.status_code, 401)

        user, error = self._authorize(request, password="wrong")
        self.assertEqual(error.status_code, 429)

    def test_lockout_event_once_per_trip(self):
        request = self._request()
        with patch("core.utils.log_system_event") as log_event, patch(
            "core.utils.notify_xc_auth_lockout_inbox"
        ) as inbox:
            for _ in range(XC_AUTH_FAILURE_LIMIT):
                self._authorize(request, password="wrong")
            self.assertEqual(log_event.call_count, 1)
            self.assertEqual(
                log_event.call_args.kwargs["reason"],
                "XC auth rate limited",
            )
            self.assertEqual(
                log_event.call_args.kwargs["event_type"], "login_failed"
            )
            inbox.assert_called_once()

            self._authorize(request, password="wrong")
            self.assertEqual(log_event.call_count, 1)
            inbox.assert_called_once()

    def test_cache_key_uses_xc_auth_scope_not_login(self):
        request = self._request()
        throttle = XcFailedAuthRateThrottle()
        key = throttle.get_cache_key(request, view=None)
        self.assertIn("xc_auth", key)
        self.assertNotIn("login", key)

    def test_varying_forwarded_for_prefix_shares_one_budget(self):
        for i in range(XC_AUTH_FAILURE_LIMIT):
            request = self._request(
                forwarded_for=f"{i}.{i}.{i}.{i}, 203.0.113.7"
            )
            _user, error = self._authorize(request, password="wrong")
            self.assertEqual(error.status_code, 401)

        request = self._request(forwarded_for="9.9.9.9, 203.0.113.7")
        _user, error = self._authorize(request, password="wrong")
        self.assertEqual(error.status_code, 429)

    def test_different_real_peers_get_independent_budgets(self):
        for i in range(XC_AUTH_FAILURE_LIMIT):
            request = self._request(forwarded_for=f"noise, 203.0.113.{i}")
            _user, error = self._authorize(request, password="wrong")
            self.assertEqual(error.status_code, 401)

        request = self._request(forwarded_for="noise, 203.0.113.42")
        _user, error = self._authorize(request, password="wrong")
        self.assertEqual(error.status_code, 401)


class XcAuthLockoutInboxTests(TestCase):
    def setUp(self):
        cache.clear()
        SystemNotification.objects.filter(
            notification_key=XC_AUTH_LOCKOUT_NOTICE_KEY
        ).delete()
        self.factory = RequestFactory()
        User.objects.create_user(
            username="bob",
            password="django-password",
            custom_properties={"xc_password": "secret"},
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            password="admin-password",
            user_level=10,
        )

    def tearDown(self):
        cache.clear()
        SystemNotification.objects.filter(
            notification_key=XC_AUTH_LOCKOUT_NOTICE_KEY
        ).delete()

    def _trip_lockout(self):
        request = self.factory.get("/player_api.php")
        with patch(
            "apps.accounts.xc_auth.network_access_allowed", return_value=True
        ), patch("core.utils.send_websocket_notification") as ws:
            for _ in range(XC_AUTH_FAILURE_LIMIT):
                authorize_xc_client(request, "bob", "wrong", "XC_API")
        return ws

    def test_inbox_created_once_per_cooldown(self):
        ws = self._trip_lockout()
        notice = SystemNotification.objects.get(
            notification_key=XC_AUTH_LOCKOUT_NOTICE_KEY
        )
        self.assertTrue(notice.admin_only)
        self.assertEqual(notice.action_data.get("action_url"), "/stats")
        ws.assert_called_once()
        self.assertTrue(cache.get(XC_AUTH_LOCKOUT_COOLDOWN_CACHE_KEY))

        first_id = notice.id
        with patch(
            "apps.accounts.xc_auth.network_access_allowed", return_value=True
        ), patch("core.utils.send_websocket_notification") as ws2:
            authorize_xc_client(
                self.factory.get("/player_api.php"), "bob", "wrong", "XC_API"
            )
        self.assertEqual(
            SystemNotification.objects.get(
                notification_key=XC_AUTH_LOCKOUT_NOTICE_KEY
            ).id,
            first_id,
        )
        ws2.assert_not_called()

    def test_dismiss_does_not_block_notice_after_cooldown(self):
        self._trip_lockout()
        notice = SystemNotification.objects.get(
            notification_key=XC_AUTH_LOCKOUT_NOTICE_KEY
        )
        NotificationDismissal.objects.create(user=self.admin, notification=notice)
        old_id = notice.id

        cache.clear()

        with patch(
            "apps.accounts.xc_auth.network_access_allowed", return_value=True
        ), patch("core.utils.send_websocket_notification"):
            for _ in range(XC_AUTH_FAILURE_LIMIT):
                authorize_xc_client(
                    self.factory.get("/player_api.php"), "bob", "wrong", "XC_API"
                )

        new_notice = SystemNotification.objects.get(
            notification_key=XC_AUTH_LOCKOUT_NOTICE_KEY
        )
        self.assertNotEqual(new_notice.id, old_id)
        self.assertFalse(
            NotificationDismissal.objects.filter(notification=new_notice).exists()
        )
