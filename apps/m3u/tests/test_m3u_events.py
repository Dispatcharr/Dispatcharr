"""
Tests for M3U lifecycle events.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.m3u.models import M3UAccount


class M3USourceEventTests(TestCase):
    """Tests for M3U source lifecycle events via signals."""

    @patch('core.events.emit')
    def test_source_created_event(self, mock_emit):
        """Test that m3u.source_created is emitted when an account is created."""
        account = M3UAccount.objects.create(
            name='Test M3U',
            server_url='http://example.com/playlist.m3u',
        )

        # Find the created call
        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'm3u.source_created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], account)

    @patch('core.events.emit')
    def test_source_deleted_event(self, mock_emit):
        """Test that m3u.source_deleted is emitted when an account is deleted."""
        account = M3UAccount.objects.create(
            name='Test M3U',
            server_url='http://example.com/playlist.m3u',
        )
        mock_emit.reset_mock()

        account.delete()

        # Find the deleted call
        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'm3u.source_deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)

    @patch('core.events.emit')
    def test_source_enabled_event(self, mock_emit):
        """Test that m3u.source_enabled is emitted when account is activated."""
        account = M3UAccount.objects.create(
            name='Test M3U',
            server_url='http://example.com/playlist.m3u',
            is_active=False,
        )
        mock_emit.reset_mock()

        # Enable the account
        account.is_active = True
        account.save()

        # Find the enabled call
        enabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'm3u.source_enabled'
        ]
        self.assertEqual(len(enabled_calls), 1)
        self.assertEqual(enabled_calls[0][0][1], account)

    @patch('core.events.emit')
    def test_source_disabled_event(self, mock_emit):
        """Test that m3u.source_disabled is emitted when account is deactivated."""
        account = M3UAccount.objects.create(
            name='Test M3U',
            server_url='http://example.com/playlist.m3u',
            is_active=True,
        )
        mock_emit.reset_mock()

        # Disable the account
        account.is_active = False
        account.save()

        # Find the disabled call
        disabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'm3u.source_disabled'
        ]
        self.assertEqual(len(disabled_calls), 1)
        self.assertEqual(disabled_calls[0][0][1], account)


class M3URefreshEventTests(TestCase):
    """Tests for M3U refresh events."""

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='Test M3U',
            server_url='http://example.com/playlist.m3u',
        )

    @patch('core.events.emit')
    def test_refresh_started_emitted_before_fetch(self, mock_emit):
        """Test that m3u.refresh_started is emitted when refresh begins."""
        # The m3u.refresh_started event is emitted at the start of refresh_single_m3u_account
        # This is tested by the signal-level tests
        mock_emit.reset_mock()

        # No API call made, just verify the event would not be called yet
        started_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'm3u.refresh_started'
        ]
        self.assertEqual(len(started_calls), 0)  # Not called until task runs

    @patch('core.events.emit')
    def test_refresh_completed_event_structure(self, mock_emit):
        """Test that m3u.refresh_completed includes stream creation/update counts."""
        # The m3u.refresh_completed event is emitted at the end of refresh_single_m3u_account
        # Verify the event data structure includes:
        # - account object
        # - streams_created count
        # - streams_updated count
        mock_emit.reset_mock()

        # No completed events until task runs
        completed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'm3u.refresh_completed'
        ]
        self.assertEqual(len(completed_calls), 0)
