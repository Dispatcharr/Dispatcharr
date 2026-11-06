from unittest.mock import patch

from celery.exceptions import Retry
from django.test import SimpleTestCase

from apps.vod.tasks import refresh_vod_content


class VODRefreshLockTests(SimpleTestCase):
    @patch("apps.vod.tasks._refresh_vod_content_impl", return_value="done")
    @patch("apps.vod.tasks.release_task_lock")
    @patch("apps.vod.tasks.TaskLockRenewer")
    @patch("apps.vod.tasks.acquire_task_lock", return_value=True)
    def test_refresh_holds_live_account_lock(
        self, acquire_lock, renewer, release_lock, refresh_impl
    ):
        self.assertEqual(refresh_vod_content(7), "done")
        acquire_lock.assert_called_once_with("refresh_single_m3u_account", 7)
        renewer.return_value.start.assert_called_once_with()
        refresh_impl.assert_called_once_with(7)
        renewer.return_value.stop.assert_called_once_with()
        release_lock.assert_called_once_with("refresh_single_m3u_account", 7)

    @patch("apps.vod.tasks._refresh_vod_content_impl")
    @patch("apps.vod.tasks.acquire_task_lock", return_value=False)
    def test_busy_account_is_retried(self, acquire_lock, refresh_impl):
        with self.assertRaises(Retry):
            refresh_vod_content(7)
        acquire_lock.assert_called_once_with("refresh_single_m3u_account", 7)
        refresh_impl.assert_not_called()
