from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django_celery_beat.models import PeriodicTask
from rest_framework import status

from apps.m3u.api_views import RefreshSingleM3UAPIView
from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountSerializer
from apps.m3u.tasks import should_refresh_vod_after_live


class SeparateVODScheduleTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="scheduled-xc",
            account_type=M3UAccount.Types.XC,
            server_url="https://provider.example",
            username="user",
            password="password",
            custom_properties={"enable_vod": True},
        )

    def update_account(self, **values):
        serializer = M3UAccountSerializer(self.account, data=values, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.account.refresh_from_db()

    def test_existing_accounts_keep_vod_after_live_by_default(self):
        self.assertTrue(self.account.vod_refresh_after_live)
        self.assertFalse(self.account.vod_refresh_task.enabled)

    def test_separate_vod_cron_does_not_change_live_schedule(self):
        live_task_id = self.account.refresh_task_id
        self.update_account(
            vod_refresh_after_live=False,
            vod_cron_expression="0 2 * * *",
        )

        self.assertEqual(self.account.refresh_task_id, live_task_id)
        self.assertTrue(self.account.vod_refresh_task.enabled)
        self.assertEqual(
            self.account.vod_refresh_task.task, "apps.vod.tasks.refresh_vod_content"
        )
        self.assertEqual(str(self.account.vod_refresh_task.crontab.hour), "2")
        self.assertEqual(
            M3UAccountSerializer(self.account).data["vod_cron_expression"],
            "0 2 * * *",
        )

    def test_separate_interval_can_be_disabled_for_manual_only_vod(self):
        self.update_account(vod_refresh_after_live=False, vod_refresh_interval=24)
        self.assertTrue(self.account.vod_refresh_task.enabled)

        self.update_account(vod_refresh_interval=0)
        self.assertFalse(self.account.vod_refresh_task.enabled)
        self.assertFalse(self.account.vod_refresh_after_live)

    def test_disabling_vod_or_account_disables_vod_schedule(self):
        self.update_account(vod_refresh_after_live=False, vod_refresh_interval=24)
        self.update_account(enable_vod=False)
        self.assertFalse(self.account.vod_refresh_task.enabled)

        self.update_account(enable_vod=True, is_active=False)
        self.assertFalse(self.account.vod_refresh_task.enabled)

    def test_deleting_account_removes_both_periodic_tasks(self):
        account_id = self.account.id
        self.account.delete()
        self.assertFalse(
            PeriodicTask.objects.filter(name=f"m3u_account-refresh-{account_id}").exists()
        )
        self.assertFalse(
            PeriodicTask.objects.filter(name=f"m3u_account-vod-refresh-{account_id}").exists()
        )


class VODAfterLiveDecisionTests(SimpleTestCase):
    def test_default_uses_account_setting(self):
        self.assertFalse(
            should_refresh_vod_after_live(SimpleNamespace(vod_refresh_after_live=False))
        )

    def test_manual_live_only_override_wins(self):
        self.assertFalse(
            should_refresh_vod_after_live(
                SimpleNamespace(vod_refresh_after_live=True), include_vod=False
            )
        )

    def test_explicit_combined_override_wins(self):
        self.assertTrue(
            should_refresh_vod_after_live(
                SimpleNamespace(vod_refresh_after_live=False), include_vod=True
            )
        )


class ManualLiveRefreshEndpointTests(SimpleTestCase):
    @patch("apps.m3u.api_views.refresh_single_m3u_account.delay")
    def test_initial_combined_refresh_queues_vod_even_with_separate_schedule(self, delay):
        request = SimpleNamespace(query_params={"include_vod": "true"})
        response = RefreshSingleM3UAPIView().post(request, account_id=7)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        delay.assert_called_once_with(7, include_vod=True)

    @patch("apps.m3u.api_views.refresh_single_m3u_account.delay")
    def test_live_only_request_does_not_queue_vod(self, delay):
        request = SimpleNamespace(query_params={"include_vod": "false"})
        response = RefreshSingleM3UAPIView().post(request, account_id=7)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        delay.assert_called_once_with(7, include_vod=False)

    @patch("apps.m3u.api_views.refresh_single_m3u_account.delay")
    def test_legacy_request_preserves_account_setting(self, delay):
        request = SimpleNamespace(query_params={})
        response = RefreshSingleM3UAPIView().post(request, account_id=7)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        delay.assert_called_once_with(7)

    @patch("apps.m3u.api_views.refresh_single_m3u_account.delay")
    def test_invalid_override_is_rejected(self, delay):
        request = SimpleNamespace(query_params={"include_vod": "not-a-boolean"})
        response = RefreshSingleM3UAPIView().post(request, account_id=7)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        delay.assert_not_called()
