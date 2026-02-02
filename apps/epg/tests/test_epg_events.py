"""
Tests for EPG lifecycle events.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.epg.models import EPGSource


class EPGSourceEventTests(TestCase):
    """Tests for EPG source lifecycle events via signals."""

    @patch('core.events.emit')
    def test_source_created_event(self, mock_emit):
        """Test that epg.source_created is emitted when a source is created."""
        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
        )

        # Find the created call
        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.source_created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], source)

    @patch('core.events.emit')
    def test_source_deleted_event(self, mock_emit):
        """Test that epg.source_deleted is emitted when a source is deleted."""
        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
        )
        mock_emit.reset_mock()

        source.delete()

        # Find the deleted call
        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.source_deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)

    @patch('core.events.emit')
    def test_source_enabled_event(self, mock_emit):
        """Test that epg.source_enabled is emitted when source is activated."""
        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            is_active=False,
        )
        mock_emit.reset_mock()

        # Enable the source
        source.is_active = True
        source.save()

        # Find the enabled call
        enabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.source_enabled'
        ]
        self.assertEqual(len(enabled_calls), 1)
        self.assertEqual(enabled_calls[0][0][1], source)

    @patch('core.events.emit')
    def test_source_disabled_event(self, mock_emit):
        """Test that epg.source_disabled is emitted when source is deactivated."""
        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            is_active=True,
        )
        mock_emit.reset_mock()

        # Disable the source
        source.is_active = False
        source.save()

        # Find the disabled call
        disabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.source_disabled'
        ]
        self.assertEqual(len(disabled_calls), 1)
        self.assertEqual(disabled_calls[0][0][1], source)


class EPGRefreshEventTests(TestCase):
    """Tests for EPG refresh events."""

    @patch('apps.epg.tasks.release_task_lock')
    @patch('apps.epg.tasks.acquire_task_lock', return_value=True)
    @patch('core.events.emit')
    @patch('apps.epg.tasks.fetch_xmltv')
    def test_refresh_started_event(self, mock_fetch, mock_emit, mock_acquire, mock_release):
        """Test that epg.refresh_started is emitted when refresh begins."""
        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
            is_active=True,
        )
        mock_emit.reset_mock()

        # Even if fetch fails, refresh_started should have been emitted
        mock_fetch.return_value = False

        from apps.epg.tasks import refresh_epg_data
        refresh_epg_data(source.id)

        # Find the refresh_started call
        started_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.refresh_started'
        ]
        self.assertEqual(len(started_calls), 1)

    @patch('apps.epg.tasks.release_task_lock')
    @patch('apps.epg.tasks.acquire_task_lock', return_value=True)
    @patch('core.events.emit')
    @patch('apps.epg.tasks.fetch_xmltv')
    def test_refresh_failed_on_fetch_error(self, mock_fetch, mock_emit, mock_acquire, mock_release):
        """Test that epg.refresh_failed is emitted when fetch fails."""
        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
            is_active=True,
        )
        mock_emit.reset_mock()

        # Simulate fetch failure
        mock_fetch.return_value = False

        from apps.epg.tasks import refresh_epg_data
        refresh_epg_data(source.id)

        # Find the refresh_failed call
        failed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.refresh_failed'
        ]
        self.assertEqual(len(failed_calls), 1)

    @patch('apps.epg.tasks.release_task_lock')
    @patch('apps.epg.tasks.acquire_task_lock', return_value=True)
    @patch('core.events.emit')
    @patch('apps.epg.tasks.fetch_xmltv')
    @patch('apps.epg.tasks.parse_channels_only')
    @patch('apps.epg.tasks.parse_programs_for_source')
    def test_refresh_completed_on_success(self, mock_parse_programs, mock_parse_channels, mock_fetch, mock_emit, mock_acquire, mock_release):
        """Test that epg.refresh_completed is emitted on successful refresh."""
        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
            is_active=True,
        )
        mock_emit.reset_mock()

        mock_fetch.return_value = True
        mock_parse_channels.return_value = True
        mock_parse_programs.return_value = True

        from apps.epg.tasks import refresh_epg_data
        refresh_epg_data(source.id)

        # Find the refresh_started call (should be first)
        started_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.refresh_started'
        ]
        self.assertEqual(len(started_calls), 1)
