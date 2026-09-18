from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.m3u.tasks import refresh_single_m3u_account


class ConditionalM3URefreshTests(SimpleTestCase):
    @patch("apps.m3u.tasks._mark_xc_client_refresh_complete")
    @patch("apps.m3u.tasks.cache.delete")
    @patch("apps.m3u.tasks._refresh_single_m3u_account_impl")
    @patch("apps.m3u.tasks.release_task_lock")
    @patch("apps.m3u.tasks.acquire_task_lock", return_value=True)
    @patch("apps.m3u.tasks.M3UAccount.objects.filter")
    def test_fresh_account_skips_before_provider_download(
        self,
        account_filter,
        acquire_lock,
        release_lock,
        refresh_impl,
        cache_delete,
        mark_complete,
    ):
        account_filter.return_value.values_list.return_value.first.return_value = (
            timezone.now()
        )

        result = refresh_single_m3u_account.run(
            account_id=11,
            include_vod=False,
            minimum_age_seconds=3300,
            client_triggered=True,
            client_completion_key="xc_live_refresh_complete:test:11",
        )

        refresh_impl.assert_not_called()
        cache_delete.assert_called_once_with("xc_live_refresh_request:11")
        mark_complete.assert_called_once_with(
            "xc_live_refresh_complete:test:11",
            "skipped_fresh",
        )
        release_lock.assert_called_once_with("refresh_single_m3u_account", 11)
        self.assertIn("fresh", result)

    @patch("apps.m3u.tasks.cache.delete")
    @patch("apps.m3u.tasks._refresh_single_m3u_account_impl")
    @patch("apps.m3u.tasks.release_task_lock")
    @patch("apps.m3u.tasks.acquire_task_lock", return_value=True)
    @patch("apps.m3u.tasks.M3UAccount.objects.filter")
    def test_refresh_after_request_was_queued_skips_even_with_zero_minimum_age(
        self,
        account_filter,
        acquire_lock,
        release_lock,
        refresh_impl,
        cache_delete,
    ):
        now = timezone.now()
        account_filter.return_value.values_list.return_value.first.return_value = now

        result = refresh_single_m3u_account.run(
            account_id=12,
            include_vod=False,
            minimum_age_seconds=0,
            skip_if_refreshed_after=(now - timezone.timedelta(minutes=1)).isoformat(),
            client_triggered=True,
        )

        refresh_impl.assert_not_called()
        release_lock.assert_called_once_with("refresh_single_m3u_account", 12)
        self.assertIn("fresh", result)
