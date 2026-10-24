from datetime import timedelta
from unittest.mock import PropertyMock, patch

from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountSerializer


class RefreshScheduleStatusTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="schedule-status",
            account_type=M3UAccount.Types.XC,
            refresh_interval=6,
            vod_refresh_interval=24,
            vod_refresh_after_live=False,
            custom_properties={"enable_vod": True},
        )
        self.account.refresh_from_db()

    def test_live_and_vod_have_independent_read_only_status(self):
        now = timezone.now()
        live = self.account.refresh_task
        vod = self.account.vod_refresh_task
        live.last_run_at = now - timedelta(hours=1)
        vod.last_run_at = now - timedelta(hours=2)
        live.save(update_fields=["last_run_at"])
        vod.save(update_fields=["last_run_at"])
        before = [
            (task.last_run_at, task.total_run_count, task.date_changed)
            for task in (live, vod)
        ]

        with patch("apps.m3u.models.django_timezone.now", return_value=now):
            data = M3UAccountSerializer(self.account).data

        self.assertTrue(data["live_refresh_schedule"]["enabled"])
        self.assertTrue(data["vod_refresh_schedule"]["enabled"])
        self.assertEqual(
            parse_datetime(data["live_refresh_schedule"]["last_run_at"]),
            live.last_run_at,
        )
        self.assertEqual(
            parse_datetime(data["vod_refresh_schedule"]["last_run_at"]), vod.last_run_at
        )
        self.assertAlmostEqual(
            (
                parse_datetime(data["live_refresh_schedule"]["next_run_at"]) - now
            ).total_seconds(),
            5 * 3600,
            delta=2,
        )
        self.assertAlmostEqual(
            (
                parse_datetime(data["vod_refresh_schedule"]["next_run_at"]) - now
            ).total_seconds(),
            22 * 3600,
            delta=2,
        )
        for task, expected in zip((live, vod), before):
            task.refresh_from_db()
            self.assertEqual(
                (task.last_run_at, task.total_run_count, task.date_changed), expected
            )

    def test_disabled_schedule_keeps_last_run_but_has_no_next_run(self):
        task = self.account.refresh_task
        task.enabled = False
        task.last_run_at = timezone.now() - timedelta(days=1)
        task.save(update_fields=["enabled", "last_run_at"])
        status = self.account.get_refresh_schedule()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["last_run_at"], task.last_run_at)
        self.assertIsNone(status["next_run_at"])

    def test_cron_schedule_reports_its_next_due_time(self):
        serializer = M3UAccountSerializer(
            self.account, data={"cron_expression": "*/15 * * * *"}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.account.refresh_from_db()
        now = timezone.now()
        self.account.refresh_task.last_run_at = now
        status = self.account.get_refresh_schedule()
        self.assertTrue(status["enabled"])
        seconds = (status["next_run_at"] - now).total_seconds()
        self.assertGreaterEqual(seconds, 0)
        self.assertLessEqual(seconds, 15 * 60 + 1)

    def test_missing_schedule_is_explicitly_unscheduled(self):
        self.account.refresh_task = None
        self.assertEqual(
            self.account.get_refresh_schedule(),
            {"enabled": False, "last_run_at": None, "next_run_at": None},
        )

    def test_overdue_schedule_is_due_now_not_another_interval_later(self):
        now = timezone.now()
        self.account.refresh_task.last_run_at = now - timedelta(hours=7)
        with patch("apps.m3u.models.django_timezone.now", return_value=now):
            self.assertEqual(self.account.get_refresh_schedule()["next_run_at"], now)

    def test_invalid_legacy_schedule_does_not_break_account_listing(self):
        with patch.object(
            type(self.account.refresh_task),
            "schedule",
            new_callable=PropertyMock,
            side_effect=ValueError("invalid schedule"),
        ):
            with self.assertLogs("apps.m3u.models", level="WARNING"):
                self.assertIsNone(self.account.get_refresh_schedule()["next_run_at"])

    def test_schedule_status_fields_cannot_change_tasks_on_save(self):
        serializer = M3UAccountSerializer(
            self.account,
            data={
                "live_refresh_schedule": {"enabled": False},
                "vod_refresh_schedule": {"enabled": False},
            },
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.account.refresh_from_db()
        self.assertTrue(self.account.refresh_task.enabled)
        self.assertTrue(self.account.vod_refresh_task.enabled)
