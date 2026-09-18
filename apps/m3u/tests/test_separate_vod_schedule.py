from types import SimpleNamespace

from django.test import TestCase, SimpleTestCase
from django_celery_beat.models import PeriodicTask

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
            refresh_interval=0,
            custom_properties={"enable_vod": True},
        )

    def test_existing_after_live_mode_keeps_separate_task_disabled(self):
        self.account.refresh_from_db()
        task = PeriodicTask.objects.get(
            name=f"m3u_account-vod-refresh-{self.account.id}"
        )

        self.assertTrue(self.account.vod_refresh_after_live)
        self.assertFalse(task.enabled)
        self.assertEqual(task.task, "apps.vod.tasks.refresh_vod_content")

    def test_separate_vod_cron_creates_enabled_vod_task(self):
        serializer = M3UAccountSerializer(
            self.account,
            data={
                "vod_refresh_after_live": False,
                "vod_cron_expression": "0 2 * * *",
            },
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        self.account.refresh_from_db()
        task = self.account.vod_refresh_task
        self.assertIsNotNone(task)
        self.assertTrue(task.enabled)
        self.assertEqual(task.task, "apps.vod.tasks.refresh_vod_content")
        self.assertEqual(str(task.crontab.minute), "0")
        self.assertEqual(str(task.crontab.hour), "2")

        data = M3UAccountSerializer(self.account).data
        self.assertEqual(data["vod_cron_expression"], "0 2 * * *")

    def test_disabling_vod_disables_its_periodic_task(self):
        serializer = M3UAccountSerializer(
            self.account,
            data={
                "enable_vod": True,
                "vod_refresh_after_live": False,
                "vod_refresh_interval": 24,
            },
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        serializer = M3UAccountSerializer(
            self.account,
            data={"enable_vod": False},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        self.account.refresh_from_db()
        self.assertFalse(self.account.vod_refresh_task.enabled)


class VODAfterLiveDecisionTests(SimpleTestCase):
    def test_account_setting_is_used_without_override(self):
        self.assertFalse(
            should_refresh_vod_after_live(
                SimpleNamespace(vod_refresh_after_live=False)
            )
        )

    def test_explicit_live_only_override_wins(self):
        self.assertFalse(
            should_refresh_vod_after_live(
                SimpleNamespace(vod_refresh_after_live=True),
                include_vod=False,
            )
        )

    def test_explicit_combined_override_wins(self):
        self.assertTrue(
            should_refresh_vod_after_live(
                SimpleNamespace(vod_refresh_after_live=False),
                include_vod=True,
            )
        )
