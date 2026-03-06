"""
Tests for memory cleanup behavior in M3U refresh tasks.

Verifies that database connections are properly closed, task locks are
released on all exit paths, and garbage collection runs where expected.

"""
from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase

from apps.m3u.models import M3UAccount


class ProcessM3UBatchCleanupTests(SimpleTestCase):
    """Verify process_m3u_batch_direct cleans up after processing."""

    @patch("apps.m3u.tasks.Stream")
    @patch("apps.m3u.tasks.M3UAccount")
    def test_connections_closed_after_batch(self, mock_account_cls, mock_stream_cls):
        """Database connections must be closed after batch processing (thread safety)."""
        from apps.m3u.tasks import process_m3u_batch_direct

        mock_account = MagicMock()
        mock_account.filters.order_by.return_value = []
        mock_account_cls.objects.get.return_value = mock_account
        mock_stream_cls.objects.filter.return_value.select_related.return_value.only.return_value = (
            []
        )
        mock_stream_cls.generate_hash_key = MagicMock(return_value="hash123")

        with patch("django.db.connections") as mock_connections:
            process_m3u_batch_direct(1, [], {}, ["name", "url"])
            mock_connections.close_all.assert_called()


class LockReleaseTests(SimpleTestCase):
    """Verify task lock is released on all exit paths."""

    @patch("apps.m3u.tasks.delete_m3u_refresh_task_by_id", return_value=False)
    def test_lock_released_on_account_not_found(self, mock_delete):
        """release_task_lock must be called when account does not exist."""
        with patch(
            "apps.m3u.tasks.acquire_task_lock", return_value=True
        ), patch("apps.m3u.tasks.release_task_lock") as mock_release, patch(
            "apps.m3u.tasks.TaskLockRenewer"
        ):
            with patch(
                "apps.m3u.tasks.M3UAccount.objects.get",
                side_effect=M3UAccount.DoesNotExist,
            ):
                from apps.m3u.tasks import refresh_single_m3u_account

                refresh_single_m3u_account(99999)

            mock_release.assert_called_once_with(
                "refresh_single_m3u_account", 99999
            )

    def test_lock_released_on_exception(self):
        """release_task_lock must be called when an exception is raised."""
        mock_account = MagicMock()
        mock_account.is_active = True
        mock_account.account_type = "STD"
        mock_account.custom_properties = {}
        mock_account.filters.all.return_value = []
        mock_account.status = MagicMock()

        with patch(
            "apps.m3u.tasks.acquire_task_lock", return_value=True
        ), patch("apps.m3u.tasks.release_task_lock") as mock_release, patch(
            "apps.m3u.tasks.TaskLockRenewer"
        ):
            with patch(
                "apps.m3u.tasks.M3UAccount.objects.get", return_value=mock_account
            ):
                with patch("os.path.exists", return_value=False):
                    with patch(
                        "apps.m3u.tasks.refresh_m3u_groups",
                        side_effect=RuntimeError("test"),
                    ):
                        from apps.m3u.tasks import refresh_single_m3u_account

                        try:
                            refresh_single_m3u_account(1)
                        except RuntimeError:
                            pass

            mock_release.assert_called_once_with("refresh_single_m3u_account", 1)


class XCCategoryCleanupTests(SimpleTestCase):
    """Regression guard: process_xc_category_direct must continue to clean up."""

    @patch("apps.m3u.tasks.XCClient")
    @patch("apps.m3u.tasks.M3UAccount")
    def test_xc_category_calls_gc_collect(self, mock_account_cls, mock_xc_client):
        """gc.collect() must be called after XC category processing."""
        from apps.m3u.tasks import process_xc_category_direct

        mock_account = MagicMock()
        mock_account_cls.objects.get.return_value = mock_account

        with patch("gc.collect") as mock_gc, patch("django.db.connections"):
            process_xc_category_direct(1, {}, {}, ["name", "url"])
            mock_gc.assert_called()
