from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.context import running_as_plugin
from apps.plugins.sandbox import _plugin_open


class PluginSandboxTests(SimpleTestCase):
    def test_plugin_storage_writes_are_allowed(self):
        open_for_plugin = _plugin_open("example", "/data/plugins/example")
        with patch("apps.plugins.sandbox.builtins.open") as open_mock:
            with running_as_plugin("example"):
                open_for_plugin("/data/plugins/example/output.txt", "w")
        open_mock.assert_called_once()

    def test_external_writes_require_capability(self):
        open_for_plugin = _plugin_open("example", "/data/plugins/example")
        with patch("apps.plugins.sandbox.require_plugin_capability") as require:
            with patch("apps.plugins.sandbox.builtins.open") as open_mock:
                with running_as_plugin("example"):
                    open_for_plugin("/tmp/output.txt", "w")
        require.assert_called_once_with("filesystem_write")
        open_mock.assert_called_once()
