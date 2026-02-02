"""
Tests for Plugin lifecycle events.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.plugins.models import PluginConfig


class PluginLifecycleEventTests(TestCase):
    """Tests for plugin lifecycle events via signals."""

    @patch('core.events.emit')
    def test_plugin_installed_event(self, mock_emit):
        """Test that plugin.installed is emitted when a plugin is discovered."""
        plugin = PluginConfig.objects.create(
            key='test-plugin',
            name='Test Plugin',
            version='1.0.0',
            enabled=False,
        )

        # Find the installed call
        installed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.installed'
        ]
        self.assertEqual(len(installed_calls), 1)
        self.assertEqual(installed_calls[0][0][1], plugin)

    @patch('core.events.emit')
    def test_plugin_uninstalled_event(self, mock_emit):
        """Test that plugin.uninstalled is emitted when a plugin is removed."""
        plugin = PluginConfig.objects.create(
            key='test-plugin',
            name='Test Plugin',
            version='1.0.0',
            enabled=False,
        )
        mock_emit.reset_mock()

        plugin.delete()

        # Find the uninstalled call
        uninstalled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.uninstalled'
        ]
        self.assertEqual(len(uninstalled_calls), 1)

    @patch('core.events.emit')
    def test_plugin_enabled_event(self, mock_emit):
        """Test that plugin.enabled is emitted when a plugin is enabled."""
        plugin = PluginConfig.objects.create(
            key='test-plugin',
            name='Test Plugin',
            version='1.0.0',
            enabled=False,
        )
        mock_emit.reset_mock()

        plugin.enabled = True
        plugin.save()

        # Find the enabled call
        enabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.enabled'
        ]
        self.assertEqual(len(enabled_calls), 1)
        self.assertEqual(enabled_calls[0][0][1], plugin)

    @patch('core.events.emit')
    def test_plugin_disabled_event(self, mock_emit):
        """Test that plugin.disabled is emitted when a plugin is disabled."""
        plugin = PluginConfig.objects.create(
            key='test-plugin',
            name='Test Plugin',
            version='1.0.0',
            enabled=True,
        )
        mock_emit.reset_mock()

        plugin.enabled = False
        plugin.save()

        # Find the disabled call
        disabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.disabled'
        ]
        self.assertEqual(len(disabled_calls), 1)
        self.assertEqual(disabled_calls[0][0][1], plugin)

    @patch('core.events.emit')
    def test_plugin_configured_event(self, mock_emit):
        """Test that plugin.configured is emitted when plugin settings change."""
        plugin = PluginConfig.objects.create(
            key='test-plugin',
            name='Test Plugin',
            version='1.0.0',
            enabled=False,
            settings={'old_key': 'old_value'},
        )
        mock_emit.reset_mock()

        plugin.settings = {'new_key': 'new_value'}
        plugin.save()

        # Find the configured call
        configured_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.configured'
        ]
        self.assertEqual(len(configured_calls), 1)
        self.assertEqual(configured_calls[0][0][1], plugin)

    @patch('core.events.emit')
    def test_no_enabled_event_on_create(self, mock_emit):
        """Test that plugin.enabled is NOT emitted on initial create (only installed)."""
        PluginConfig.objects.create(
            key='test-plugin',
            name='Test Plugin',
            version='1.0.0',
            enabled=True,  # Created as enabled
        )

        # Should only have installed, not enabled
        installed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.installed'
        ]
        enabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.enabled'
        ]
        self.assertEqual(len(installed_calls), 1)
        self.assertEqual(len(enabled_calls), 0)

    @patch('core.events.emit')
    def test_no_event_when_no_changes(self, mock_emit):
        """Test that no events are emitted when saving without changes."""
        plugin = PluginConfig.objects.create(
            key='test-plugin',
            name='Test Plugin',
            version='1.0.0',
            enabled=False,
        )
        mock_emit.reset_mock()

        # Save without changing anything
        plugin.save()

        # Should not have any enabled/disabled/configured calls
        state_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] in ('plugin.enabled', 'plugin.disabled', 'plugin.configured')
        ]
        self.assertEqual(len(state_calls), 0)

    @patch('core.events.emit')
    def test_enabled_and_configured_together(self, mock_emit):
        """Test that both enabled and configured can fire in same save."""
        plugin = PluginConfig.objects.create(
            key='test-plugin',
            name='Test Plugin',
            version='1.0.0',
            enabled=False,
            settings={'key': 'old'},
        )
        mock_emit.reset_mock()

        plugin.enabled = True
        plugin.settings = {'key': 'new'}
        plugin.save()

        # Should have both enabled and configured
        enabled_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.enabled'
        ]
        configured_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'plugin.configured'
        ]
        self.assertEqual(len(enabled_calls), 1)
        self.assertEqual(len(configured_calls), 1)
