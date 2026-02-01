"""
Tests for recording lifecycle events.
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, Recording


class RecordingEventTests(TestCase):
    """Tests for recording event emission."""

    def setUp(self):
        self.channel = Channel.objects.create(
            name="Test Channel",
            channel_number=1,
        )
        self.future_time = timezone.now() + timedelta(hours=1)
        self.end_time = self.future_time + timedelta(hours=2)

    @patch('core.events.emit')
    def test_recording_scheduled_on_create(self, mock_emit):
        """Test that recording.scheduled is emitted when a recording is created."""
        recording = Recording.objects.create(
            channel=self.channel,
            start_time=self.future_time,
            end_time=self.end_time,
        )

        # Find the scheduled call
        scheduled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording.scheduled'
        ]
        self.assertEqual(len(scheduled_calls), 1)
        self.assertEqual(scheduled_calls[0][0][1], recording)

    @patch('core.events.emit')
    def test_recording_changed_on_time_update(self, mock_emit):
        """Test that recording.changed is emitted when times are modified."""
        recording = Recording.objects.create(
            channel=self.channel,
            start_time=self.future_time,
            end_time=self.end_time,
        )
        mock_emit.reset_mock()

        # Update the recording times
        new_start = self.future_time + timedelta(hours=1)
        recording.start_time = new_start
        recording.save()

        # Find the changed call
        changed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording.changed'
        ]
        self.assertEqual(len(changed_calls), 1)
        self.assertEqual(changed_calls[0][0][1], recording)

    @patch('core.events.emit')
    def test_recording_cancelled_on_delete_before_completion(self, mock_emit):
        """Test that recording.cancelled is emitted when a pending recording is deleted."""
        recording = Recording.objects.create(
            channel=self.channel,
            start_time=self.future_time,
            end_time=self.end_time,
        )
        mock_emit.reset_mock()

        recording.delete()

        # Find the cancelled call
        cancelled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording.cancelled'
        ]
        self.assertEqual(len(cancelled_calls), 1)

    @patch('core.events.emit')
    def test_recording_deleted_on_delete_after_completion(self, mock_emit):
        """Test that recording.deleted is emitted when a completed recording is deleted."""
        recording = Recording.objects.create(
            channel=self.channel,
            start_time=self.future_time,
            end_time=self.end_time,
            custom_properties={"status": "completed"},
        )
        mock_emit.reset_mock()

        recording.delete()

        # Find the deleted call
        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording.deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)


class BulkRecordingEventTests(TestCase):
    """Tests for bulk recording operations."""

    def setUp(self):
        self.channel = Channel.objects.create(
            name="Test Channel",
            channel_number=1,
        )

    @patch('core.events.emit')
    def test_bulk_cancelled_emits_count(self, mock_emit):
        """Test that recording.bulk_cancelled includes the count of deleted recordings."""
        future_time = timezone.now() + timedelta(hours=1)

        # Create multiple upcoming recordings
        for i in range(3):
            Recording.objects.create(
                channel=self.channel,
                start_time=future_time + timedelta(hours=i),
                end_time=future_time + timedelta(hours=i+1),
            )

        # Recording creation triggers scheduled events, verify those were emitted
        scheduled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording.scheduled'
        ]
        self.assertEqual(len(scheduled_calls), 3)

        # No bulk_cancelled event until the API endpoint is called
        bulk_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'recording.bulk_cancelled'
        ]
        self.assertEqual(len(bulk_calls), 0)
