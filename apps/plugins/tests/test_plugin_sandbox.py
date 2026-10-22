from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.context import running_as_plugin
from apps.plugins.loader import LoadedPlugin
from apps.plugins.sandbox import _plugin_open, plugin_builtins, stable_plugin_data_path


class PluginSandboxTests(SimpleTestCase):
    def test_plugin_storage_writes_are_allowed(self):
        open_for_plugin = _plugin_open("example", "/data/plugins/example")
        with patch("apps.plugins.sandbox.builtins.open") as open_mock:
            with running_as_plugin("example"):
                open_for_plugin("/data/plugins/example/output.txt", "w")
        open_mock.assert_called_once()

    def test_version_stable_sibling_storage_writes_are_allowed(self):
        open_for_plugin = _plugin_open(
            "example_plugin_1_2_3",
            "/data/plugins/example_plugin_1_2_3",
            "example_plugin",
        )
        with patch("apps.plugins.sandbox.require_plugin_capability") as require:
            with patch("apps.plugins.sandbox.builtins.open") as open_mock:
                with running_as_plugin("example_plugin_1_2_3"):
                    open_for_plugin("/data/plugins/example_plugin_data/cache.json", "w")
        require.assert_not_called()
        open_mock.assert_called_once()

    def test_undeclared_sibling_storage_requires_capability(self):
        open_for_plugin = _plugin_open(
            "example_plugin_1_2_3",
            "/data/plugins/example_plugin_1_2_3",
            "example_plugin",
        )
        with patch("apps.plugins.sandbox.require_plugin_capability") as require:
            with patch("apps.plugins.sandbox.builtins.open") as open_mock:
                with running_as_plugin("example_plugin_1_2_3"):
                    open_for_plugin("/data/plugins/other_data/output.txt", "w")
        require.assert_called_once_with("filesystem_write")
        open_mock.assert_called_once()

    def test_stable_storage_uses_the_plugin_install_parent(self):
        open_for_plugin = _plugin_open("example", "/custom/plugins/example", "example")
        with patch("apps.plugins.sandbox.require_plugin_capability") as require:
            with patch("apps.plugins.sandbox.builtins.open") as open_mock:
                with running_as_plugin("example"):
                    open_for_plugin("/custom/plugins/example_data/output.txt", "w")
        require.assert_not_called()
        open_mock.assert_called_once()

    def test_default_plugins_directory_is_not_allowed_for_custom_installs(self):
        open_for_plugin = _plugin_open("example", "/custom/plugins/example", "example")
        with patch("apps.plugins.sandbox.require_plugin_capability") as require:
            with patch("apps.plugins.sandbox.builtins.open") as open_mock:
                with running_as_plugin("example"):
                    open_for_plugin("/data/plugins/example/output.txt", "w")
        require.assert_called_once_with("filesystem_write")
        open_mock.assert_called_once()

    def test_unsafe_storage_key_does_not_expand_the_allowlist(self):
        open_for_plugin = _plugin_open("example", "/data/plugins/example", "../outside")
        with patch("apps.plugins.sandbox.require_plugin_capability") as require:
            with patch("apps.plugins.sandbox.builtins.open") as open_mock:
                with running_as_plugin("example"):
                    open_for_plugin("/data/outside_data/output.txt", "w")
        require.assert_called_once_with("filesystem_write")
        open_mock.assert_called_once()

    def test_stable_storage_path_uses_the_canonical_key(self):
        self.assertEqual(
            stable_plugin_data_path(
                "example_1_2_3",
                "/data/plugins/example_1_2_3",
                "example",
            ),
            "/data/plugins/example_data",
        )

    def test_external_writes_require_capability(self):
        open_for_plugin = _plugin_open("example", "/data/plugins/example")
        with patch("apps.plugins.sandbox.require_plugin_capability") as require:
            with patch("apps.plugins.sandbox.builtins.open") as open_mock:
                with running_as_plugin("example"):
                    open_for_plugin("/tmp/output.txt", "w")
        require.assert_called_once_with("filesystem_write")
        open_mock.assert_called_once()

    def test_selected_top_level_imports_remain_guarded(self):
        values = plugin_builtins("example", "/data/plugins/example")
        with patch("apps.plugins.sandbox.require_plugin_capability") as require, patch(
            "subprocess.run"
        ), patch("requests.get"):
            with running_as_plugin("example"):
                values["__import__"]("subprocess").run(["true"])
                values["__import__"]("requests").get("https://example.com")

        require.assert_any_call("subprocess")
        require.assert_any_call("outbound_network")

    def test_urllib_request_import_forms_remain_guarded(self):
        values = plugin_builtins("example", "/data/plugins/example")
        with patch("apps.plugins.sandbox.require_plugin_capability") as require, patch(
            "urllib.request.urlopen"
        ):
            with running_as_plugin("example"):
                values["__import__"]("urllib.request", fromlist=("urlopen",)).urlopen("https://example.com")
                values["__import__"]("urllib.request").request.urlopen("https://example.com")

        self.assertEqual(require.call_count, 2)
        require.assert_called_with("outbound_network")

    def test_socket_and_http_client_helpers_remain_guarded(self):
        values = plugin_builtins("example", "/data/plugins/example")
        with patch("apps.plugins.sandbox.require_plugin_capability") as require, patch(
            "socket.create_connection"
        ), patch("http.client.HTTPConnection"):
            with running_as_plugin("example"):
                values["__import__"]("socket").create_connection(("example.com", 443))
                values["__import__"]("http.client", fromlist=("HTTPConnection",)).HTTPConnection("example.com")

        self.assertEqual(require.call_count, 2)
        require.assert_called_with("outbound_network")

    def test_thread_inherits_plugin_context(self):
        values = plugin_builtins("example", "/data/plugins/example")
        plugin = LoadedPlugin(key="example", name="Example", manifest_schema_version=2)
        errors = []

        def target():
            try:
                values["__import__"]("subprocess").run(["true"])
            except Exception as exc:
                errors.append(exc)

        with patch("apps.plugins.loader.PluginManager.get") as get_manager, patch("subprocess.run"):
            get_manager.return_value.get_plugin.return_value = plugin
            with running_as_plugin("example"):
                thread = values["__import__"]("threading").Thread(target=target)
                thread.start()
                thread.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PermissionError)
