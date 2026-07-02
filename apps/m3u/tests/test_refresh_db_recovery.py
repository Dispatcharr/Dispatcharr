from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.m3u.tasks import (
    _db_query_with_retry,
    _get_active_m3u_account,
    _release_task_db_connection,
    refresh_single_m3u_account,
)


class DbQueryWithRetryTests(SimpleTestCase):
    def test_retries_after_index_error_from_poisoned_connection(self):
        fn = MagicMock(side_effect=[IndexError("list index out of range"), "ok"])

        with patch(
            "apps.m3u.tasks._release_task_db_connection"
        ) as mock_release:
            result = _db_query_with_retry(fn, label="test query")

        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        mock_release.assert_called_once()

    def test_raises_after_exhausting_retries(self):
        fn = MagicMock(side_effect=IndexError("list index out of range"))

        with patch("apps.m3u.tasks._release_task_db_connection"):
            with self.assertRaises(IndexError):
                _db_query_with_retry(fn, label="test query", max_retries=2)

        self.assertEqual(fn.call_count, 2)


class RefreshTaskDbStartupTests(SimpleTestCase):
    @patch("apps.m3u.tasks._ensure_m3u_refresh_terminal_status")
    @patch("apps.m3u.tasks._refresh_single_m3u_account_impl")
    @patch("apps.m3u.tasks.release_task_lock")
    @patch("apps.m3u.tasks.acquire_task_lock", return_value=True)
    @patch("apps.m3u.tasks.TaskLockRenewer")
    @patch("apps.m3u.tasks._release_task_db_connection")
    def test_refresh_releases_db_connection_before_impl(
        self,
        mock_release,
        _mock_renewer,
        _mock_acquire,
        _mock_release_lock,
        mock_impl,
        _mock_ensure_terminal,
    ):
        call_order = []

        def track_release():
            call_order.append("release")

        mock_release.side_effect = track_release
        mock_impl.side_effect = lambda *_a, **_k: call_order.append("impl") or "done"

        result = refresh_single_m3u_account(140)

        self.assertEqual(result, "done")
        self.assertEqual(call_order[:2], ["release", "impl"])

    @patch("apps.m3u.tasks.M3UAccount")
    def test_get_active_m3u_account_uses_retry_helper(self, mock_model):
        mock_model.objects.get.return_value = MagicMock(is_active=True)

        with patch("apps.m3u.tasks._db_query_with_retry") as mock_retry:
            mock_retry.side_effect = lambda fn, **_: fn()
            account = _get_active_m3u_account(140)

        mock_retry.assert_called_once()
        self.assertTrue(account.is_active)
