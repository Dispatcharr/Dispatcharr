"""PluginManager must release geventpool checkouts after every run/stop."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.plugins.loader import LoadedPlugin, PluginManager


class PluginRunActionDbCleanupTests(SimpleTestCase):
    @contextmanager
    def _manager_with_plugin(self, run_impl):
        instance = MagicMock()
        instance.run = run_impl
        lp = LoadedPlugin(
            key="test_plugin",
            name="Test Plugin",
            instance=instance,
            actions=[{"id": "do_work"}],
        )
        pm = PluginManager()
        cfg = MagicMock(enabled=True, settings={})
        with patch.object(pm, "get_plugin", return_value=lp), patch(
            "apps.plugins.loader.PluginConfig.objects.get", return_value=cfg
        ):
            yield pm

    @patch("apps.plugins.loader.close_old_connections")
    def test_run_action_closes_connections_on_success(self, mock_close):
        with self._manager_with_plugin(lambda *_a, **_k: {"status": "ok"}) as pm:
            result = pm.run_action("test_plugin", "do_work")

        self.assertEqual(result, {"status": "ok"})
        mock_close.assert_called_once()

    @patch("apps.plugins.loader.close_old_connections")
    def test_run_action_closes_connections_on_plugin_error(self, mock_close):
        def _boom(*_a, **_k):
            raise RuntimeError("plugin failed")

        with self._manager_with_plugin(_boom) as pm:
            with self.assertRaises(RuntimeError):
                pm.run_action("test_plugin", "do_work")

        mock_close.assert_called_once()

    @patch("apps.plugins.loader.close_old_connections")
    def test_stop_plugin_closes_connections(self, mock_close):
        instance = MagicMock()
        instance.stop = MagicMock()
        lp = LoadedPlugin(
            key="test_plugin",
            name="Test Plugin",
            instance=instance,
        )
        pm = PluginManager()
        cfg = MagicMock(enabled=True, settings={})
        with patch.object(pm, "get_plugin", return_value=lp), patch(
            "apps.plugins.loader.PluginConfig.objects.get", return_value=cfg
        ):
            self.assertTrue(pm.stop_plugin("test_plugin", reason="shutdown"))

        mock_close.assert_called_once()
