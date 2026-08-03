from unittest.mock import patch

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.m3u.tasks import (
    _ensure_m3u_refresh_terminal_status,
    _set_m3u_account_status,
)


class M3UErrorEventTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Test Provider",
            server_url="http://example.com/playlist.m3u",
            status=M3UAccount.Status.FETCHING,
        )

    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    def test_set_m3u_account_status_logs_m3u_error_event(
        self, mock_send_m3u_update, mock_log_system_event
    ):
        _set_m3u_account_status(
            self.account.id,
            M3UAccount.Status.ERROR,
            "Download timeout",
            notify_error=True,
            ws_error="Download timeout",
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.status, M3UAccount.Status.ERROR)

        mock_log_system_event.assert_called_once_with(
            event_type="m3u_error",
            account_name="Test Provider",
            error="Download timeout",
        )

    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    def test_ensure_m3u_refresh_terminal_status_logs_m3u_error_event(
        self, mock_send_m3u_update, mock_log_system_event
    ):
        _ensure_m3u_refresh_terminal_status(self.account.id)

        self.account.refresh_from_db()
        self.assertEqual(self.account.status, M3UAccount.Status.ERROR)

        mock_log_system_event.assert_called_once_with(
            event_type="m3u_error",
            account_name="Test Provider",
            error="Refresh did not complete successfully",
        )
