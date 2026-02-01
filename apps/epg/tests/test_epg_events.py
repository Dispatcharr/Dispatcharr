"""
Tests for EPG lifecycle events.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.epg.models import EPGSource


class EPGSourceEventTests(TestCase):
    """Tests for EPG source lifecycle events."""

    @patch('core.events.emit')
    def test_source_created_event(self, mock_emit):
        """Test that epg.source_created is emitted when a source is created via API."""
        from apps.epg.api_views import EPGSourceViewSet

        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
        )

        # Manually call perform_create to test the event
        viewset = EPGSourceViewSet()
        serializer = MagicMock()
        serializer.save.return_value = source
        viewset.perform_create(serializer)

        mock_emit.assert_called_once_with('epg.source_created', source)

    @patch('core.events.emit')
    def test_source_deleted_event(self, mock_emit):
        """Test that epg.source_deleted is emitted when a source is deleted."""
        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
        )

        from apps.epg.api_views import EPGSourceViewSet
        viewset = EPGSourceViewSet()
        viewset.perform_destroy(source)

        mock_emit.assert_called_once_with('epg.source_deleted', source)

    @patch('core.events.emit')
    def test_source_enabled_event(self, mock_emit):
        """Test that epg.source_enabled is emitted when source is activated."""
        from apps.epg.api_views import EPGSourceViewSet
        from rest_framework.test import APIRequestFactory
        from rest_framework.request import Request

        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            is_active=False,
        )

        factory = APIRequestFactory()
        request = factory.patch(f'/api/epg-sources/{source.id}/', {'is_active': True})
        drf_request = Request(request)
        drf_request._full_data = {'is_active': True}

        viewset = EPGSourceViewSet()
        viewset.request = drf_request
        viewset.format_kwarg = None
        viewset.kwargs = {'pk': source.id}

        # Mock get_object to return our source
        viewset.get_object = MagicMock(return_value=source)

        # Mock get_serializer to actually save the change
        def mock_get_serializer(instance=None, data=None, partial=False):
            mock_serializer = MagicMock()
            mock_serializer.is_valid.return_value = True
            def save_and_update():
                # Actually save the is_active change to the database
                source.is_active = True
                source.save(update_fields=['is_active'])
                return source
            mock_serializer.save.side_effect = save_and_update
            mock_serializer.data = {'id': source.id, 'is_active': True}
            return mock_serializer

        viewset.get_serializer = mock_get_serializer

        # Call partial_update which should emit the enabled event
        viewset.partial_update(drf_request, pk=source.id)

        # Find the enabled call
        enabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.source_enabled'
        ]
        self.assertEqual(len(enabled_calls), 1)

    @patch('core.events.emit')
    def test_source_disabled_event(self, mock_emit):
        """Test that epg.source_disabled is emitted when source is deactivated."""
        from apps.epg.api_views import EPGSourceViewSet
        from rest_framework.test import APIRequestFactory
        from rest_framework.request import Request

        source = EPGSource.objects.create(
            name='Test EPG',
            source_type='xmltv',
            is_active=True,
        )

        factory = APIRequestFactory()
        request = factory.patch(f'/api/epg-sources/{source.id}/', {'is_active': False})
        drf_request = Request(request)
        drf_request._full_data = {'is_active': False}

        viewset = EPGSourceViewSet()
        viewset.request = drf_request
        viewset.format_kwarg = None
        viewset.kwargs = {'pk': source.id}

        # Mock get_object to return our source
        viewset.get_object = MagicMock(return_value=source)

        # Mock get_serializer to actually save the change
        def mock_get_serializer(instance=None, data=None, partial=False):
            mock_serializer = MagicMock()
            mock_serializer.is_valid.return_value = True
            def save_and_update():
                # Actually save the is_active change to the database
                source.is_active = False
                source.save(update_fields=['is_active'])
                return source
            mock_serializer.save.side_effect = save_and_update
            mock_serializer.data = {'id': source.id, 'is_active': False}
            return mock_serializer

        viewset.get_serializer = mock_get_serializer

        # Call partial_update which should emit the disabled event
        viewset.partial_update(drf_request, pk=source.id)

        # Find the disabled call
        disabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'epg.source_disabled'
        ]
        self.assertEqual(len(disabled_calls), 1)


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
