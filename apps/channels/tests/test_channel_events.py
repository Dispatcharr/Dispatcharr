"""
Tests for Channel lifecycle events.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelGroup, Stream
from apps.m3u.models import M3UAccount


class ChannelEventTests(TestCase):
    """Tests for channel lifecycle events via signals."""

    def setUp(self):
        self.m3u_account = M3UAccount.objects.filter(name='Custom').first()
        if not self.m3u_account:
            self.m3u_account = M3UAccount.get_custom_account()

    @patch('core.events.emit')
    def test_channel_created_event(self, mock_emit):
        """Test that channel.created is emitted when a channel is created."""
        channel = Channel.objects.create(
            name='Test Channel',
            channel_number=1,
        )

        # Find the created call
        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], channel)

    @patch('core.events.emit')
    def test_channel_deleted_event(self, mock_emit):
        """Test that channel.deleted is emitted when a channel is deleted."""
        channel = Channel.objects.create(
            name='Test Channel',
            channel_number=1,
        )
        mock_emit.reset_mock()

        channel.delete()

        # Find the deleted call
        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)

    @patch('core.events.emit')
    def test_channel_updated_event_on_name_change(self, mock_emit):
        """Test that channel.updated is emitted when channel name changes."""
        channel = Channel.objects.create(
            name='Test Channel',
            channel_number=1,
        )
        mock_emit.reset_mock()

        channel.name = 'Updated Channel'
        channel.save()

        # Find the updated call
        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.updated'
        ]
        self.assertEqual(len(updated_calls), 1)
        self.assertEqual(updated_calls[0][0][1], channel)

    @patch('core.events.emit')
    def test_channel_updated_event_on_number_change(self, mock_emit):
        """Test that channel.updated is emitted when channel number changes."""
        channel = Channel.objects.create(
            name='Test Channel',
            channel_number=1,
        )
        mock_emit.reset_mock()

        channel.channel_number = 2
        channel.save()

        # Find the updated call
        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.updated'
        ]
        self.assertEqual(len(updated_calls), 1)

    @patch('core.events.emit')
    def test_channel_updated_event_on_group_change(self, mock_emit):
        """Test that channel.updated is emitted when channel group changes."""
        group = ChannelGroup.objects.create(name='Test Group')
        channel = Channel.objects.create(
            name='Test Channel',
            channel_number=1,
        )
        mock_emit.reset_mock()

        channel.channel_group = group
        channel.save()

        # Find the updated call
        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.updated'
        ]
        self.assertEqual(len(updated_calls), 1)

    @patch('core.events.emit')
    def test_updated_event_on_any_save(self, mock_emit):
        """Test that channel.updated is emitted on any save to existing channel."""
        channel = Channel.objects.create(
            name='Test Channel',
            channel_number=1,
        )
        mock_emit.reset_mock()

        # Save without explicit changes still emits updated
        channel.save()

        updated_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.updated'
        ]
        self.assertEqual(len(updated_calls), 1)


class ChannelStreamEventTests(TestCase):
    """Tests for channel stream assignment events."""

    def setUp(self):
        self.m3u_account = M3UAccount.objects.filter(name='Custom').first()
        if not self.m3u_account:
            self.m3u_account = M3UAccount.get_custom_account()
        self.channel = Channel.objects.create(
            name='Test Channel',
            channel_number=1,
        )

    @patch('core.events.emit')
    def test_stream_added_event(self, mock_emit):
        """Test that channel.stream_added is emitted when stream is added."""
        stream = Stream.objects.create(
            name='Test Stream',
            url='http://example.com/stream.m3u8',
            m3u_account=self.m3u_account,
        )
        mock_emit.reset_mock()

        self.channel.streams.add(stream)

        # Find the stream_added call
        added_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.stream_added'
        ]
        self.assertEqual(len(added_calls), 1)
        self.assertEqual(added_calls[0][0][1], self.channel)
        self.assertIn(stream.id, added_calls[0][1]['stream_ids'])

    @patch('core.events.emit')
    def test_stream_removed_event(self, mock_emit):
        """Test that channel.stream_removed is emitted when stream is removed."""
        stream = Stream.objects.create(
            name='Test Stream',
            url='http://example.com/stream.m3u8',
            m3u_account=self.m3u_account,
        )
        self.channel.streams.add(stream)
        mock_emit.reset_mock()

        self.channel.streams.remove(stream)

        # Find the stream_removed call
        removed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.stream_removed'
        ]
        self.assertEqual(len(removed_calls), 1)
        self.assertEqual(removed_calls[0][0][1], self.channel)
        self.assertIn(stream.id, removed_calls[0][1]['stream_ids'])

    @patch('core.events.emit')
    def test_multiple_streams_added_event(self, mock_emit):
        """Test that channel.stream_added includes all added stream IDs."""
        stream1 = Stream.objects.create(
            name='Test Stream 1',
            url='http://example.com/stream1.m3u8',
            m3u_account=self.m3u_account,
        )
        stream2 = Stream.objects.create(
            name='Test Stream 2',
            url='http://example.com/stream2.m3u8',
            m3u_account=self.m3u_account,
        )
        mock_emit.reset_mock()

        self.channel.streams.add(stream1, stream2)

        # Find the stream_added call
        added_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'channel.stream_added'
        ]
        self.assertEqual(len(added_calls), 1)
        self.assertIn(stream1.id, added_calls[0][1]['stream_ids'])
        self.assertIn(stream2.id, added_calls[0][1]['stream_ids'])
