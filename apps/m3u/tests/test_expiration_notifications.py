"""
Tests for evaluate_profile_expiration_notification.

Covers all four branches:
  - no exp_date         → returns None, touches nothing
  - already expired     → creates/updates expired notification, removes warning
  - expiring within 7d  → creates/updates warning notification, removes expired
  - not expiring soon   → removes any stale notifications, returns None
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase
from django.utils import timezone


def _make_profile(exp_date, profile_id=1, profile_name="Test Profile",
                  account_id=10, account_name="Test Account"):
    """Return a minimal mock M3UAccountProfile."""
    profile = MagicMock()
    profile.id = profile_id
    profile.name = profile_name
    profile.exp_date = exp_date
    profile.m3u_account.id = account_id
    profile.m3u_account.name = account_name
    return profile


class EvaluateProfileExpirationNotificationTests(SimpleTestCase):

    def setUp(self):
        # These three names are local imports inside evaluate_profile_expiration_notification,
        # so we must patch them at their source modules rather than on apps.m3u.tasks.
        self.mock_sn = MagicMock()
        self.mock_send_ws = patch("core.utils.send_websocket_notification").start()
        self.mock_dismissed = patch("core.utils.send_notification_dismissed").start()
        patch("core.models.SystemNotification", self.mock_sn).start()

    def tearDown(self):
        patch.stopall()

    def _run(self, profile):
        from apps.m3u.tasks import evaluate_profile_expiration_notification
        return evaluate_profile_expiration_notification(profile)

    # ------------------------------------------------------------------ #
    # No expiration date
    # ------------------------------------------------------------------ #

    def test_no_exp_date_returns_none(self):
        profile = _make_profile(exp_date=None)
        result = self._run(profile)
        self.assertIsNone(result)
        self.mock_sn.objects.update_or_create.assert_not_called()
        self.mock_send_ws.assert_not_called()

    # ------------------------------------------------------------------ #
    # Already expired
    # ------------------------------------------------------------------ #

    @patch("apps.m3u.tasks.timezone")
    def test_expired_creates_expired_notification(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        profile = _make_profile(exp_date=now - timedelta(days=1))
        # No existing warning notification to delete
        self.mock_sn.objects.filter.return_value.values_list.return_value = []
        notification = MagicMock()
        self.mock_sn.objects.update_or_create.return_value = (notification, True)

        result = self._run(profile)

        self.assertEqual(result, f"xc-exp-expired-{profile.id}")
        self.mock_sn.objects.update_or_create.assert_called_once()
        call_kwargs = self.mock_sn.objects.update_or_create.call_args
        self.assertEqual(call_kwargs.kwargs["notification_key"], f"xc-exp-expired-{profile.id}")
        self.assertTrue(call_kwargs.kwargs["defaults"]["admin_only"])
        self.mock_send_ws.assert_called_once_with(notification)

    @patch("apps.m3u.tasks.timezone")
    def test_expired_removes_stale_warning_notification(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        profile = _make_profile(exp_date=now - timedelta(hours=1))
        warning_key = f"xc-exp-warning-{profile.id}"
        # Simulate an existing warning notification
        self.mock_sn.objects.filter.return_value.values_list.return_value = [warning_key]
        self.mock_sn.objects.update_or_create.return_value = (MagicMock(), False)

        self._run(profile)

        self.mock_dismissed.assert_any_call(warning_key)

    # ------------------------------------------------------------------ #
    # Expiring within 7 days
    # ------------------------------------------------------------------ #

    @patch("apps.m3u.tasks.timezone")
    def test_warning_window_creates_warning_notification(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        profile = _make_profile(exp_date=now + timedelta(days=3))
        self.mock_sn.objects.filter.return_value.values_list.return_value = []
        notification = MagicMock()
        self.mock_sn.objects.update_or_create.return_value = (notification, True)

        result = self._run(profile)

        self.assertEqual(result, f"xc-exp-warning-{profile.id}")
        call_kwargs = self.mock_sn.objects.update_or_create.call_args
        self.assertEqual(call_kwargs.kwargs["notification_key"], f"xc-exp-warning-{profile.id}")
        self.assertTrue(call_kwargs.kwargs["defaults"]["admin_only"])
        self.mock_send_ws.assert_called_once_with(notification)

    @patch("apps.m3u.tasks.timezone")
    def test_warning_message_says_today_when_same_day(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        profile = _make_profile(exp_date=now + timedelta(hours=2))
        self.mock_sn.objects.filter.return_value.values_list.return_value = []
        self.mock_sn.objects.update_or_create.return_value = (MagicMock(), True)

        self._run(profile)

        defaults = self.mock_sn.objects.update_or_create.call_args.kwargs["defaults"]
        self.assertIn("today", defaults["message"])

    @patch("apps.m3u.tasks.timezone")
    def test_warning_message_says_1_day(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        profile = _make_profile(exp_date=now + timedelta(hours=30))
        self.mock_sn.objects.filter.return_value.values_list.return_value = []
        self.mock_sn.objects.update_or_create.return_value = (MagicMock(), True)

        self._run(profile)

        defaults = self.mock_sn.objects.update_or_create.call_args.kwargs["defaults"]
        self.assertIn("in 1 day", defaults["message"])

    @patch("apps.m3u.tasks.timezone")
    def test_warning_removes_stale_expired_notification(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        profile = _make_profile(exp_date=now + timedelta(days=5))
        expired_key = f"xc-exp-expired-{profile.id}"
        self.mock_sn.objects.filter.return_value.values_list.return_value = [expired_key]
        self.mock_sn.objects.update_or_create.return_value = (MagicMock(), False)

        self._run(profile)

        self.mock_dismissed.assert_any_call(expired_key)

    # ------------------------------------------------------------------ #
    # Not expiring soon (> 7 days away)
    # ------------------------------------------------------------------ #

    @patch("apps.m3u.tasks.timezone")
    def test_not_expiring_soon_returns_none(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        profile = _make_profile(exp_date=now + timedelta(days=30))
        self.mock_sn.objects.filter.return_value.values_list.return_value = []

        result = self._run(profile)

        self.assertIsNone(result)
        self.mock_sn.objects.update_or_create.assert_not_called()
        self.mock_send_ws.assert_not_called()

    @patch("apps.m3u.tasks.timezone")
    def test_not_expiring_soon_removes_stale_notifications(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        profile = _make_profile(exp_date=now + timedelta(days=30))
        warning_key = f"xc-exp-warning-{profile.id}"
        self.mock_sn.objects.filter.return_value.values_list.return_value = [warning_key]

        self._run(profile)

        self.mock_dismissed.assert_called_once_with(warning_key)

    # ------------------------------------------------------------------ #
    # Boundary: exactly at the 7-day warning threshold
    # ------------------------------------------------------------------ #

    @patch("apps.m3u.tasks.timezone")
    def test_exactly_7_days_away_triggers_warning(self, mock_tz):
        now = timezone.now()
        mock_tz.now.return_value = now
        mock_tz.timedelta = timedelta

        # exp_date == now + 7 days  →  exp <= warning_threshold  →  warning
        profile = _make_profile(exp_date=now + timedelta(days=7))
        self.mock_sn.objects.filter.return_value.values_list.return_value = []
        self.mock_sn.objects.update_or_create.return_value = (MagicMock(), True)

        result = self._run(profile)

        self.assertEqual(result, f"xc-exp-warning-{profile.id}")
