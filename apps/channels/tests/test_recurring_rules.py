from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, RecurringRecordingRule, Recording
from apps.channels.tasks import sync_recurring_rule_impl, purge_recurring_rule_impl
from core.models import CoreSettings


class RecurringRecordingRuleTasksTests(TestCase):
    def test_sync_recurring_rule_creates_and_purges_recordings(self):
        # sync_recurring_rule_impl interprets a rule's start_time/end_time as wall-clock
        # time in the system's configured timezone (not necessarily UTC), so build and
        # verify the expected schedule in that same timezone rather than assuming
        # get_current_timezone() is UTC. Deriving the weekday from the same shifted
        # moment used for start_time also avoids flakiness when the offset rolls over a
        # day boundary (e.g. running near midnight).
        tz = ZoneInfo(CoreSettings.get_system_time_zone())
        now_local = timezone.now().astimezone(tz)
        channel = Channel.objects.create(channel_number=1, name='Test Channel')

        future_start = now_local + timedelta(minutes=15)
        future_end = now_local + timedelta(minutes=75)
        start_time = future_start.time().replace(second=0, microsecond=0)
        end_time = future_end.time().replace(second=0, microsecond=0)

        rule = RecurringRecordingRule.objects.create(
            channel=channel,
            days_of_week=[future_start.weekday()],
            start_time=start_time,
            end_time=end_time,
        )

        created = sync_recurring_rule_impl(rule.id, drop_existing=True, horizon_days=1)
        self.assertEqual(created, 1)

        recording = Recording.objects.filter(custom_properties__rule__id=rule.id).first()
        self.assertIsNotNone(recording)
        self.assertEqual(recording.channel, channel)
        self.assertEqual(recording.custom_properties.get('rule', {}).get('id'), rule.id)

        expected_start = timezone.make_aware(
            datetime.combine(recording.start_time.astimezone(tz).date(), start_time),
            tz,
        )
        self.assertLess(abs((recording.start_time - expected_start).total_seconds()), 60)

        removed = purge_recurring_rule_impl(rule.id)
        self.assertEqual(removed, 1)
        self.assertFalse(Recording.objects.filter(custom_properties__rule__id=rule.id).exists())
