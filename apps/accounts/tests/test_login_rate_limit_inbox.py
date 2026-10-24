"""JWT/admin login rate-limit lockout events and admin inbox notice."""

import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from core.models import (
    CoreSettings,
    NotificationDismissal,
    REVERSE_PROXY_AUTH_KEY,
    SystemNotification,
)
from core.utils import (
    LOGIN_RATE_LIMIT_COOLDOWN_CACHE_KEY,
    LOGIN_RATE_LIMIT_NOTICE_KEY,
    notify_login_rate_limit_inbox,
)

User = get_user_model()

LOGIN_ATTEMPT_LIMIT = int(
    api_settings.DEFAULT_THROTTLE_RATES["login"].split("/")[0]
)


class LoginRateLimitInboxTests(TestCase):
    def setUp(self):
        cache.clear()
        SystemNotification.objects.filter(
            notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
        ).delete()
        self.client = Client()
        self.api = APIClient()
        self.token_url = "/api/accounts/token/"
        self.admin_login_url = "/admin/login/"
        User.objects.create_superuser(
            username="adminuser",
            password="correct-password",
            user_level=10,
        )
        self.admin = User.objects.create_superuser(
            username="notify-admin",
            password="admin-password",
            user_level=10,
        )

    def tearDown(self):
        cache.clear()
        SystemNotification.objects.filter(
            notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
        ).delete()

    def _jwt_login(self, password="wrong-password"):
        return self.api.post(
            self.token_url,
            {"username": "adminuser", "password": password},
            format="json",
        )

    def _admin_login(self, password="wrong-password"):
        return self.client.post(
            self.admin_login_url,
            {
                "username": "adminuser",
                "password": password,
                "next": "/admin/",
            },
        )

    def _trip_via_jwt(self):
        with patch("core.utils.send_websocket_notification") as ws:
            for _ in range(LOGIN_ATTEMPT_LIMIT):
                response = self._jwt_login()
                self.assertNotEqual(response.status_code, 429)
            response = self._jwt_login()
            self.assertEqual(response.status_code, 429)
        return ws, response

    def test_jwt_trip_creates_event_and_inbox_once(self):
        with patch("core.utils.log_system_event") as log_event:
            ws, response = self._trip_via_jwt()

        self.assertIn("Retry-After", response)
        notice = SystemNotification.objects.get(
            notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
        )
        self.assertEqual(notice.title, "Login rate limit triggered")
        self.assertIn(
            "JWT, reverse-proxy headers, or Django admin", notice.message
        )
        self.assertNotIn("session login", notice.message)
        self.assertTrue(notice.admin_only)
        self.assertEqual(notice.action_data.get("action_url"), "/stats")
        ws.assert_called_once()
        self.assertTrue(cache.get(LOGIN_RATE_LIMIT_COOLDOWN_CACHE_KEY))

        lockout_calls = [
            call
            for call in log_event.call_args_list
            if call.kwargs.get("reason") == "Login rate limited"
        ]
        self.assertEqual(len(lockout_calls), 1)
        self.assertEqual(lockout_calls[0].kwargs["event_type"], "login_failed")
        self.assertEqual(lockout_calls[0].kwargs["user"], "adminuser")

        first_id = notice.id
        with patch("core.utils.send_websocket_notification") as ws2, patch(
            "core.utils.log_system_event"
        ) as log_event2:
            response = self._jwt_login()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            SystemNotification.objects.get(
                notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
            ).id,
            first_id,
        )
        ws2.assert_not_called()
        self.assertFalse(
            any(
                call.kwargs.get("reason") == "Login rate limited"
                for call in log_event2.call_args_list
            )
        )

    def test_admin_login_trip_shares_inbox(self):
        with patch("core.utils.send_websocket_notification") as ws:
            for _ in range(LOGIN_ATTEMPT_LIMIT):
                self.assertNotEqual(self._admin_login().status_code, 429)
            response = self._admin_login()
        self.assertEqual(response.status_code, 429)
        notice = SystemNotification.objects.get(
            notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
        )
        self.assertTrue(notice.admin_only)
        ws.assert_called_once()

    def test_dismiss_does_not_block_notice_after_cooldown(self):
        self._trip_via_jwt()
        notice = SystemNotification.objects.get(
            notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
        )
        NotificationDismissal.objects.create(user=self.admin, notification=notice)
        old_id = notice.id

        cache.clear()

        with patch("core.utils.send_websocket_notification"):
            for _ in range(LOGIN_ATTEMPT_LIMIT):
                self.assertNotEqual(self._jwt_login().status_code, 429)
            self.assertEqual(self._jwt_login().status_code, 429)

        new_notice = SystemNotification.objects.get(
            notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
        )
        self.assertNotEqual(new_notice.id, old_id)
        self.assertFalse(
            NotificationDismissal.objects.filter(notification=new_notice).exists()
        )

    def test_inbox_create_failure_releases_cooldown(self):
        with patch("core.utils.send_websocket_notification"), patch(
            "core.models.SystemNotification.objects.create",
            side_effect=RuntimeError("db down"),
        ):
            with self.assertRaises(RuntimeError):
                notify_login_rate_limit_inbox()
        self.assertFalse(cache.get(LOGIN_RATE_LIMIT_COOLDOWN_CACHE_KEY))

        with patch("core.utils.send_websocket_notification"):
            notice = notify_login_rate_limit_inbox()
        self.assertIsNotNone(notice)
        self.assertTrue(cache.get(LOGIN_RATE_LIMIT_COOLDOWN_CACHE_KEY))

    def test_inbox_cooldown_claim_blocks_second_create(self):
        with patch("core.utils.send_websocket_notification"):
            first = notify_login_rate_limit_inbox()
            second = notify_login_rate_limit_inbox()
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            SystemNotification.objects.filter(
                notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
            ).count(),
            1,
        )

    def test_repeat_429_does_not_parse_username(self):
        self._trip_via_jwt()
        with patch(
            "apps.accounts.throttling._login_username_from_request"
        ) as read_username:
            response = self._jwt_login()
        self.assertEqual(response.status_code, 429)
        read_username.assert_not_called()

    def test_recorder_error_still_returns_429(self):
        for _ in range(LOGIN_ATTEMPT_LIMIT):
            self.assertNotEqual(self._jwt_login().status_code, 429)
        with patch(
            "django.core.cache.cache.add", side_effect=RuntimeError("cache down")
        ):
            response = self._jwt_login()
        self.assertEqual(response.status_code, 429)

    def test_proxy_login_trip_records_identity(self):
        CoreSettings.objects.update_or_create(
            key=REVERSE_PROXY_AUTH_KEY,
            defaults={
                "name": "Reverse Proxy Auth",
                "value": {"enabled": True, "header": "X-Forwarded-User"},
            },
        )
        cache.clear()
        with patch.dict(
            os.environ, {"DISPATCHARR_TRUSTED_PROXIES": "127.0.0.0/8"}, clear=False
        ), patch("core.utils.send_websocket_notification") as ws, patch(
            "core.utils.log_system_event"
        ) as log_event:
            for _ in range(LOGIN_ATTEMPT_LIMIT):
                response = self.api.post(
                    "/api/accounts/auth/proxy-login/",
                    HTTP_X_FORWARDED_USER="adminuser",
                )
                self.assertEqual(response.status_code, 200)
            response = self.api.post(
                "/api/accounts/auth/proxy-login/",
                HTTP_X_FORWARDED_USER="adminuser",
            )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        ws.assert_called_once()
        lockout_calls = [
            call
            for call in log_event.call_args_list
            if call.kwargs.get("reason") == "Login rate limited"
        ]
        self.assertEqual(len(lockout_calls), 1)
        self.assertEqual(lockout_calls[0].kwargs["user"], "adminuser")
        self.assertTrue(
            SystemNotification.objects.filter(
                notification_key=LOGIN_RATE_LIMIT_NOTICE_KEY
            ).exists()
        )
