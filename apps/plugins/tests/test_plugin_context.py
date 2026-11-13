from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.context import (
    current_plugin_key,
    plugin_has_capability,
    require_plugin_capability,
    running_as_plugin,
)
from apps.plugins.loader import LoadedPlugin


class PluginContextTests(SimpleTestCase):
    def test_context_is_reset_after_execution(self):
        self.assertIsNone(current_plugin_key())
        with running_as_plugin("example"):
            self.assertEqual(current_plugin_key(), "example")
        self.assertIsNone(current_plugin_key())

    def test_core_code_is_not_gated(self):
        self.assertTrue(plugin_has_capability("subprocess"))

    def test_transition_plugin_is_advisory(self):
        plugin = LoadedPlugin(key="example", name="Example", manifest_schema_version=1)
        with patch("apps.plugins.loader.PluginManager.get") as get_manager:
            get_manager.return_value.get_plugin.return_value = plugin
            with running_as_plugin("example"):
                self.assertTrue(plugin_has_capability("subprocess"))

    def test_sandboxed_plugin_requires_declared_capability(self):
        plugin = LoadedPlugin(key="example", name="Example", manifest_schema_version=2)
        with patch("apps.plugins.loader.PluginManager.get") as get_manager:
            get_manager.return_value.get_plugin.return_value = plugin
            with running_as_plugin("example"):
                self.assertFalse(plugin_has_capability("subprocess"))
                with self.assertRaises(PermissionError):
                    require_plugin_capability("subprocess")

    def test_sandboxed_plugin_accepts_declared_capability(self):
        plugin = LoadedPlugin(
            key="example",
            name="Example",
            manifest_schema_version=2,
            capabilities=["subprocess"],
        )
        with patch("apps.plugins.loader.PluginManager.get") as get_manager:
            get_manager.return_value.get_plugin.return_value = plugin
            with running_as_plugin("example"):
                self.assertTrue(plugin_has_capability("subprocess"))
