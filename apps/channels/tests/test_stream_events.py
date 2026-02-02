"""
Tests for Stream, ChannelGroup, ChannelProfile, and RecurringRecordingRule lifecycle events.
"""
from unittest.mock import patch
from datetime import time

from django.test import TestCase

from apps.channels.models import Stream, Channel, ChannelGroup, ChannelProfile, RecurringRecordingRule
from apps.m3u.models import M3UAccount


class StreamLifecycleEventTests(TestCase):
    """Tests for stream lifecycle events via signals."""

    def setUp(self):
        self.m3u_account = M3UAccount.get_custom_account()

    @patch('core.events.emit')
    def test_stream_created_event(self, mock_emit):
        """Test that stream.created is emitted when a stream is created."""
        stream = Stream.objects.create(
            name='Test Stream',
            url='http://example.com/stream.m3u8',
            m3u_account=self.m3u_account,
        )

        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'stream.created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], stream)

    @patch('core.events.emit')
    def test_stream_deleted_event(self, mock_emit):
        """Test that stream.deleted is emitted when a stream is deleted."""
        stream = Stream.objects.create(
            name='Test Stream',
            url='http://example.com/stream.m3u8',
            m3u_account=self.m3u_account,
        )
        mock_emit.reset_mock()

        stream.delete()

        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'stream.deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)

    @patch('core.events.emit')
    def test_stream_updated_event(self, mock_emit):
        """Test that stream.updated is emitted when a stream is modified."""
        stream = Stream.objects.create(
            name='Test Stream',
            url='http://example.com/stream.m3u8',
            m3u_account=self.m3u_account,
        )
        mock_emit.reset_mock()

        stream.name = 'Updated Stream'
        stream.save()

        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'stream.updated'
        ]
        self.assertEqual(len(updated_calls), 1)


class ChannelGroupLifecycleEventTests(TestCase):
    """Tests for channel group lifecycle events via signals."""

    @patch('core.events.emit')
    def test_channel_group_created_event(self, mock_emit):
        """Test that channel_group.created is emitted when a group is created."""
        group = ChannelGroup.objects.create(name='Test Group')

        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel_group.created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], group)

    @patch('core.events.emit')
    def test_channel_group_deleted_event(self, mock_emit):
        """Test that channel_group.deleted is emitted when a group is deleted."""
        group = ChannelGroup.objects.create(name='Test Group')
        mock_emit.reset_mock()

        group.delete()

        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel_group.deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)

    @patch('core.events.emit')
    def test_channel_group_updated_event(self, mock_emit):
        """Test that channel_group.updated is emitted when a group is renamed."""
        group = ChannelGroup.objects.create(name='Test Group')
        mock_emit.reset_mock()

        group.name = 'Renamed Group'
        group.save()

        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel_group.updated'
        ]
        self.assertEqual(len(updated_calls), 1)


class ChannelProfileLifecycleEventTests(TestCase):
    """Tests for channel profile lifecycle events via signals."""

    @patch('core.events.emit')
    def test_channel_profile_created_event(self, mock_emit):
        """Test that channel_profile.created is emitted when a profile is created."""
        profile = ChannelProfile.objects.create(name='Test Profile')

        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel_profile.created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], profile)

    @patch('core.events.emit')
    def test_channel_profile_deleted_event(self, mock_emit):
        """Test that channel_profile.deleted is emitted when a profile is deleted."""
        profile = ChannelProfile.objects.create(name='Test Profile')
        mock_emit.reset_mock()

        profile.delete()

        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel_profile.deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)

    @patch('core.events.emit')
    def test_channel_profile_updated_event(self, mock_emit):
        """Test that channel_profile.updated is emitted when a profile is renamed."""
        profile = ChannelProfile.objects.create(name='Test Profile')
        mock_emit.reset_mock()

        profile.name = 'Renamed Profile'
        profile.save()

        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel_profile.updated'
        ]
        self.assertEqual(len(updated_calls), 1)


class RecurringRecordingRuleLifecycleEventTests(TestCase):
    """Tests for recurring recording rule lifecycle events via signals."""

    def setUp(self):
        self.channel = Channel.objects.create(
            name='Test Channel',
            channel_number=1,
        )

    @patch('core.events.emit')
    def test_recording_rule_created_event(self, mock_emit):
        """Test that recording_rule.created is emitted when a rule is created."""
        rule = RecurringRecordingRule.objects.create(
            channel=self.channel,
            days_of_week=[0, 1, 2],
            start_time=time(20, 0),
            end_time=time(21, 0),
            name='Test Rule',
        )

        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording_rule.created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], rule)

    @patch('core.events.emit')
    def test_recording_rule_deleted_event(self, mock_emit):
        """Test that recording_rule.deleted is emitted when a rule is deleted."""
        rule = RecurringRecordingRule.objects.create(
            channel=self.channel,
            days_of_week=[0, 1, 2],
            start_time=time(20, 0),
            end_time=time(21, 0),
            name='Test Rule',
        )
        mock_emit.reset_mock()

        rule.delete()

        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording_rule.deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)

    @patch('core.events.emit')
    def test_recording_rule_updated_event(self, mock_emit):
        """Test that recording_rule.updated is emitted when a rule is modified."""
        rule = RecurringRecordingRule.objects.create(
            channel=self.channel,
            days_of_week=[0, 1, 2],
            start_time=time(20, 0),
            end_time=time(21, 0),
            name='Test Rule',
        )
        mock_emit.reset_mock()

        rule.name = 'Updated Rule'
        rule.save()

        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording_rule.updated'
        ]
        self.assertEqual(len(updated_calls), 1)

    @patch('core.events.emit')
    def test_recording_rule_enabled_change_event(self, mock_emit):
        """Test that recording_rule.updated is emitted when enabled status changes."""
        rule = RecurringRecordingRule.objects.create(
            channel=self.channel,
            days_of_week=[0, 1, 2],
            start_time=time(20, 0),
            end_time=time(21, 0),
            name='Test Rule',
            enabled=True,
        )
        mock_emit.reset_mock()

        rule.enabled = False
        rule.save()

        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording_rule.updated'
        ]
        self.assertEqual(len(updated_calls), 1)
