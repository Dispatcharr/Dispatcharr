import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from apps.plugins.context import running_as_plugin
from apps.plugins.loader import LoadedPlugin, PluginManager
from apps.plugins.models import PluginConfig


class PluginLoaderStorageTests(TestCase):
    def test_retained_filesystem_helper_expires_with_plugin_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = PluginManager()
            lp = LoadedPlugin(key="example", name="Example", data_dir=tmp, instance=object(),
                              capabilities=["filesystem_write"], manifest_schema_version=2)
            pm._registry[lp.key] = lp
            api = pm._plugin_filesystem_context(lp)
            snapshot = Path(tmp, "snapshot")
            snapshot.mkdir()
            pm._registry.pop(lp.key)
            with self.assertRaises(PermissionError):
                api["remove_directory"](snapshot)
            self.assertTrue(snapshot.exists())

    def test_filesystem_helper_uses_current_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = PluginManager()
            lp = LoadedPlugin(key="example", name="Example", data_dir=tmp, instance=object(),
                              capabilities=[], manifest_schema_version=2)
            pm._registry[lp.key] = lp
            api = pm._plugin_filesystem_context(lp)
            with self.assertRaises(PermissionError):
                api["ensure_directory"]("logos")

    def test_dynamic_fields_receive_saved_settings_without_creating_data_dir(self):
        with tempfile.TemporaryDirectory() as plugins_dir:
            plugin_dir = Path(plugins_dir, "example")
            plugin_dir.mkdir()
            (plugin_dir / "plugin.py").write_text(
                "import os\n"
                "class Plugin:\n"
                "    def get_fields(self, context):\n"
                "        assert not os.path.exists(context['data_dir'])\n"
                "        return [{'id': 'choice', 'type': 'text', 'label': context['settings']['choice']}]\n",
                encoding="utf-8",
            )
            cfg = PluginConfig.objects.create(key="example", name="Example", enabled=True, settings={"choice": "saved"})
            pm = PluginManager()
            lp, _, _ = pm._load_and_merge_plugin_entry(
                "example", "example", str(plugin_dir), cfg=cfg, force_reload=False, previous_package=None,
            )
            self.assertEqual(lp.fields[0]["label"], "saved")
            self.assertFalse(os.path.exists(lp.data_dir))

    def test_existing_fields_property_remains_supported(self):
        with tempfile.TemporaryDirectory() as plugins_dir:
            plugin_dir = Path(plugins_dir, "example")
            plugin_dir.mkdir()
            (plugin_dir / "plugin.py").write_text(
                "class Plugin:\n"
                "    @property\n"
                "    def fields(self):\n"
                "        return [{'id': 'old', 'type': 'text'}]\n",
                encoding="utf-8",
            )
            pm = PluginManager()
            lp, _ = pm._load_plugin(
                "example", str(plugin_dir), folder_name="example", force_reload=False,
                previous_package=None, storage_key="example",
            )
            self.assertEqual(lp.fields[0]["id"], "old")
            self.assertFalse(os.path.exists(lp.data_dir))

    def test_data_directory_exists_before_plugin_writes_to_context(self):
        with tempfile.TemporaryDirectory() as plugins_dir, patch.dict(
            os.environ, {"DISPATCHARR_PLUGINS_DIR": plugins_dir}
        ):
            plugin_dir = Path(plugins_dir, "example")
            plugin_dir.mkdir()
            Path(plugin_dir, "plugin.py").write_text(
                "import os\n"
                "class Plugin:\n"
                "    def run(self, action, params, context):\n"
                "        with open(os.path.join(context['data_dir'], 'cache.json'), 'w', encoding='utf-8') as cache:\n"
                "            cache.write('{}')\n",
                encoding="utf-8",
            )
            cfg = PluginConfig.objects.create(key="example", name="Example", enabled=True)
            pm = PluginManager()

            lp, _package_name = pm._load_plugin(
                "example", str(plugin_dir), folder_name="example", force_reload=False,
                previous_package=None, storage_key="example",
            )

            self.assertIsNotNone(lp)
            self.assertFalse(os.path.exists(lp.data_dir))
            with running_as_plugin("example"):
                lp.instance.run("run", {}, pm._build_context(lp, cfg))
            self.assertEqual(Path(lp.data_dir, "cache.json").read_text(encoding="utf-8"), "{}")
