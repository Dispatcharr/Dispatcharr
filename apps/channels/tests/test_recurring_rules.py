from datetime import datetime, timedelta
from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, RecurringRecordingRule, Recording
from apps.channels.tasks import sync_recurring_rule_impl, purge_recurring_rule_impl


class RecurringRecordingRuleTasksTests(TestCase):
    def test_sync_recurring_rule_creates_and_purges_recordings(self):
        now = timezone.now()
        channel = Channel.objects.create(channel_number=1, name='Test Channel')

        start_time = (now + timedelta(minutes=15)).time().replace(second=0, microsecond=0)
        end_time = (now + timedelta(minutes=75)).time().replace(second=0, microsecond=0)

        rule = RecurringRecordingRule.objects.create(
            channel=channel,
            days_of_week=[now.weekday()],
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
            datetime.combine(recording.start_time.date(), start_time),
            timezone.get_current_timezone(),
        )
        self.assertLess(abs((recording.start_time - expected_start).total_seconds()), 60)

        removed = purge_recurring_rule_impl(rule.id)
        self.assertEqual(removed, 1)
        self.assertFalse(Recording.objects.filter(custom_properties__rule__id=rule.id).exists())
