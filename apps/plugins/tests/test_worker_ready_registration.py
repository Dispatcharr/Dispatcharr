"""#1460/#1244: plugin @shared_tasks must register on the default queue's
prefork parent, not just in forked children."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from dispatcharr.celery import register_plugin_tasks


class RegisterPluginTasksTests(SimpleTestCase):
    @patch("apps.plugins.loader.PluginManager.get")
    def test_discovers_plugins_and_updates_strategies(self, mock_get):
        pm = MagicMock()
        mock_get.return_value = pm
        sender = MagicMock()
        sender.update_strategies = MagicMock()

        register_plugin_tasks(sender=sender)

        pm.discover_plugins.assert_called_once_with(sync_db=False, use_cache=True)
        sender.update_strategies.assert_called_once()

    @patch("apps.plugins.loader.PluginManager.get")
    def test_swallows_discovery_exception_and_still_updates_strategies(self, mock_get):
        mock_get.side_effect = RuntimeError("boom")
        sender = MagicMock()

        # Must not raise.
        register_plugin_tasks(sender=sender)

        sender.update_strategies.assert_called_once()

    @patch("apps.plugins.loader.PluginManager.get")
    def test_swallows_update_strategies_exception(self, mock_get):
        pm = MagicMock()
        mock_get.return_value = pm
        sender = MagicMock()
        sender.update_strategies.side_effect = RuntimeError("boom")

        # Must not raise.
        register_plugin_tasks(sender=sender)

    @patch("apps.plugins.loader.PluginManager.get")
    def test_no_sender_skips_update_strategies_without_error(self, mock_get):
        pm = MagicMock()
        mock_get.return_value = pm

        # Must not raise even though sender is None.
        register_plugin_tasks(sender=None)

        pm.discover_plugins.assert_called_once_with(sync_db=False, use_cache=True)

    @patch("apps.plugins.loader.PluginManager.get")
    def test_sender_without_update_strategies_is_skipped_safely(self, mock_get):
        pm = MagicMock()
        mock_get.return_value = pm
        sender = object()  # no update_strategies attribute

        # Must not raise.
        register_plugin_tasks(sender=sender)
