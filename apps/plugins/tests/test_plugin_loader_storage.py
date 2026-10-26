import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from apps.plugins.context import running_as_plugin
from apps.plugins.loader import PluginManager
from apps.plugins.models import PluginConfig


class PluginLoaderStorageTests(TestCase):
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
            self.assertTrue(os.path.isdir(lp.data_dir))
            with running_as_plugin("example"):
                lp.instance.run("run", {}, pm._build_context(lp, cfg))
            self.assertEqual(Path(lp.data_dir, "cache.json").read_text(encoding="utf-8"), "{}")
