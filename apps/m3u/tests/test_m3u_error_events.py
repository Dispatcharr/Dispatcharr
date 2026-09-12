from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.m3u.models import M3UAccount
from apps.m3u.tasks import (
    _ensure_m3u_refresh_terminal_status,
    _set_m3u_account_status,
)


class SetM3UAccountStatusTests(SimpleTestCase):
    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.tasks.M3UAccount")
    @patch("apps.m3u.tasks._release_task_db_connection")
    def test_set_status_notify_error_emits_m3u_error_event(
        self, _mock_release, mock_model, mock_ws, mock_log_event
    ):
        qs = MagicMock()
        mock_model.objects.filter.return_value = qs

        _set_m3u_account_status(
            account_id=10,
            status=M3UAccount.Status.ERROR,
            last_message="Connection timed out",
            account_name="My M3U Provider",
            notify_error=True,
            ws_action="parsing",
            ws_error="Connection timed out",
        )

        qs.update.assert_called_once_with(
            status=M3UAccount.Status.ERROR,
            last_message="Connection timed out",
        )
        mock_ws.assert_called_once_with(
            10,
            "parsing",
            100,
            status="error",
            error="Connection timed out",
        )
        mock_log_event.assert_called_once_with(
            event_type="m3u_error",
            account_name="My M3U Provider",
            message="Connection timed out",
        )

    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.tasks.M3UAccount")
    @patch("apps.m3u.tasks._release_task_db_connection")
    def test_set_status_notify_error_falls_back_to_str_id(
        self, _mock_release, mock_model, mock_ws, mock_log_event
    ):
        qs = MagicMock()
        mock_model.objects.filter.return_value = qs

        _set_m3u_account_status(
            account_id=10,
            status=M3UAccount.Status.ERROR,
            last_message="Failed to fetch",
            notify_error=True,
        )

        mock_log_event.assert_called_once_with(
            event_type="m3u_error",
            account_name="10",
            message="Failed to fetch",
        )

    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.tasks.M3UAccount")
    @patch("apps.m3u.tasks._release_task_db_connection")
    def test_set_status_without_notify_error_does_not_emit_event(
        self, _mock_release, mock_model, mock_ws, mock_log_event
    ):
        qs = MagicMock()
        mock_model.objects.filter.return_value = qs

        _set_m3u_account_status(
            account_id=10,
            status=M3UAccount.Status.FETCHING,
            last_message="Refresh in progress...",
            account_name="My M3U Provider",
            notify_error=False,
        )

        qs.update.assert_called_once_with(
            status=M3UAccount.Status.FETCHING,
            last_message="Refresh in progress...",
        )
        mock_ws.assert_not_called()
        mock_log_event.assert_not_called()


class EnsureM3UTerminalStatusTests(SimpleTestCase):
    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.tasks._release_task_db_connection")
    def test_marks_non_terminal_as_error_and_emits_event(
        self, _mock_release, mock_ws, mock_log_event
    ):
        with patch("apps.m3u.tasks.M3UAccount") as mock_model:
            mock_model.Status = M3UAccount.Status
            qs = MagicMock()
            mock_model.objects.filter.return_value = qs
            qs.values.return_value.first.return_value = {
                "status": M3UAccount.Status.FETCHING,
                "name": "Live TV Account",
            }

            _ensure_m3u_refresh_terminal_status(42)

            qs.update.assert_called_once_with(
                status=M3UAccount.Status.ERROR,
                last_message="Refresh did not complete successfully",
            )
            mock_ws.assert_called_once_with(
                42, "parsing", 100, status="error", error="Refresh did not complete successfully"
            )
            mock_log_event.assert_called_once_with(
                event_type="m3u_error",
                account_name="Live TV Account",
                message="Refresh did not complete successfully",
            )

    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.tasks._release_task_db_connection")
    def test_marks_non_terminal_falls_back_to_str_id_when_no_name(
        self, _mock_release, mock_ws, mock_log_event
    ):
        with patch("apps.m3u.tasks.M3UAccount") as mock_model:
            mock_model.Status = M3UAccount.Status
            qs = MagicMock()
            mock_model.objects.filter.return_value = qs
            qs.values.return_value.first.return_value = {
                "status": M3UAccount.Status.PARSING,
                "name": "",
            }

            _ensure_m3u_refresh_terminal_status(42)

            mock_log_event.assert_called_once_with(
                event_type="m3u_error",
                account_name="42",
                message="Refresh did not complete successfully",
            )

    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.tasks._release_task_db_connection")
    def test_leaves_terminal_status_unchanged(
        self, _mock_release, mock_ws, mock_log_event
    ):
        with patch("apps.m3u.tasks.M3UAccount") as mock_model:
            mock_model.Status = M3UAccount.Status
            qs = MagicMock()
            mock_model.objects.filter.return_value = qs
            qs.values.return_value.first.return_value = {
                "status": M3UAccount.Status.SUCCESS,
                "name": "Live TV Account",
            }

            _ensure_m3u_refresh_terminal_status(42)

            qs.update.assert_not_called()
            mock_ws.assert_not_called()
            mock_log_event.assert_not_called()


class FullRefreshErrorMessagePropagationTests(SimpleTestCase):
    @patch("apps.m3u.tasks._set_m3u_account_status")
    @patch("apps.m3u.tasks.refresh_m3u_groups")
    @patch("apps.m3u.tasks._get_active_m3u_account")
    @patch("apps.m3u.tasks.os.path.exists", return_value=False)
    @patch("apps.m3u.tasks._release_task_db_connection")
    def test_does_not_overwrite_when_already_in_error(
        self, _mock_release, _mock_exists, mock_get_account, mock_refresh_groups, mock_set_status
    ):
        from apps.m3u.tasks import _refresh_single_m3u_account_impl

        account = MagicMock(id=5, is_active=True, filters=MagicMock(), custom_properties={})
        account.name = "My Account"
        mock_get_account.return_value = account
        account.filters.order_by.return_value = []

        # Simulate refresh_m3u_groups returning None, None (failure)
        mock_refresh_groups.return_value = (None, None)

        with patch("apps.m3u.tasks.M3UAccount") as mock_model:
            mock_model.Status = M3UAccount.Status
            qs = MagicMock()
            mock_model.objects.filter.return_value = qs
            # Account is already in ERROR because fetch_m3u_lines failed earlier
            qs.values_list.return_value.first.return_value = M3UAccount.Status.ERROR

            result = _refresh_single_m3u_account_impl(5)

            self.assertEqual(result, "Failed to update m3u account - download failed or other error")
            # _set_m3u_account_status should only have been called for initial FETCHING,
            # not called to overwrite with generic message
            for call in mock_set_status.call_args_list:
                status_arg = call[0][1] if len(call[0]) > 1 else call[1].get("status")
                self.assertNotEqual(
                    status_arg,
                    M3UAccount.Status.ERROR,
                    "Should not overwrite status or emit duplicate error when already in ERROR",
                )
