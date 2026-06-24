from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.epg.tasks import (
    _db_query_with_retry,
    _ensure_epg_refresh_terminal_status,
    _get_epg_source,
    _release_task_db_connection,
    refresh_epg_data,
)


class DbQueryWithRetryTests(SimpleTestCase):
    def test_retries_after_index_error_from_poisoned_connection(self):
        fn = MagicMock(side_effect=[IndexError("list index out of range"), "ok"])

        with patch(
            "apps.epg.tasks._release_task_db_connection"
        ) as mock_release:
            result = _db_query_with_retry(fn, label="test query")

        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        mock_release.assert_called_once()

    def test_raises_after_exhausting_retries(self):
        fn = MagicMock(side_effect=IndexError("list index out of range"))

        with patch("apps.epg.tasks._release_task_db_connection"):
            with self.assertRaises(IndexError):
                _db_query_with_retry(fn, label="test query", max_retries=2)

        self.assertEqual(fn.call_count, 2)


class RefreshTaskDbStartupTests(SimpleTestCase):
    @patch("apps.epg.tasks._ensure_epg_refresh_terminal_status")
    @patch("apps.epg.tasks._refresh_epg_data_impl")
    @patch("apps.epg.tasks.release_task_lock")
    @patch("apps.epg.tasks.acquire_task_lock", return_value=True)
    @patch("apps.epg.tasks.TaskLockRenewer")
    @patch("apps.epg.tasks._release_task_db_connection")
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

        result = refresh_epg_data(42)

        self.assertEqual(result, "done")
        self.assertEqual(call_order[:2], ["release", "impl"])

    @patch("apps.epg.tasks.EPGSource")
    def test_get_epg_source_uses_retry_helper(self, mock_model):
        mock_source = MagicMock(id=42)
        mock_model.objects.get.return_value = mock_source

        with patch("apps.epg.tasks._db_query_with_retry") as mock_retry:
            mock_retry.side_effect = lambda fn, **_: fn()
            source = _get_epg_source(42)

        mock_retry.assert_called_once()
        mock_model.objects.get.assert_called_once_with(id=42)
        self.assertIs(source, mock_source)


class EnsureEpgTerminalStatusTests(SimpleTestCase):
    @patch("apps.epg.tasks.send_epg_update")
    @patch("apps.epg.tasks._release_task_db_connection")
    def test_marks_stuck_fetching_as_error(self, _mock_release, mock_ws):
        with patch("apps.epg.tasks.EPGSource") as mock_model:
            mock_model.STATUS_ERROR = "error"
            qs = MagicMock()
            mock_model.objects.filter.return_value = qs
            qs.values_list.return_value.first.return_value = "fetching"

            _ensure_epg_refresh_terminal_status(7)

            qs.update.assert_called_once()
            mock_ws.assert_called_once()

    @patch("apps.epg.tasks.send_epg_update")
    @patch("apps.epg.tasks._release_task_db_connection")
    def test_leaves_success_unchanged(self, _mock_release, mock_ws):
        with patch("apps.epg.tasks.EPGSource") as mock_model:
            qs = MagicMock()
            mock_model.objects.filter.return_value = qs
            qs.values_list.return_value.first.return_value = "success"

            _ensure_epg_refresh_terminal_status(7)

            qs.update.assert_not_called()
            mock_ws.assert_not_called()
