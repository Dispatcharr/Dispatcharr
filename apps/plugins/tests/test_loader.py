"""Tests for plugin loader with manifest support."""

import os
import sys

# Configure Django before importing any Django-dependent modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")

import django
django.setup()

import tempfile
from unittest import TestCase
from unittest.mock import patch

import yaml


class TestLoaderWithManifest(TestCase):
    """Test cases for plugin loading with manifest support."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_plugins_dir = os.environ.get("DISPATCHARR_PLUGINS_DIR")
        os.environ["DISPATCHARR_PLUGINS_DIR"] = self.temp_dir

        # Add temp dir to sys.path for imports
        if self.temp_dir not in sys.path:
            sys.path.insert(0, self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        if self.original_plugins_dir:
            os.environ["DISPATCHARR_PLUGINS_DIR"] = self.original_plugins_dir
        else:
            os.environ.pop("DISPATCHARR_PLUGINS_DIR", None)

        # Remove temp dir from sys.path
        if self.temp_dir in sys.path:
            sys.path.remove(self.temp_dir)

        # Clean up temp directory
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_plugin(self, key, manifest=None, plugin_code=None):
        """Helper to create a test plugin."""
        plugin_dir = os.path.join(self.temp_dir, key)
        os.makedirs(plugin_dir, exist_ok=True)

        if manifest:
            manifest_path = os.path.join(plugin_dir, "plugin.yaml")
            with open(manifest_path, "w") as f:
                yaml.dump(manifest, f)

        if plugin_code:
            plugin_path = os.path.join(plugin_dir, "plugin.py")
            with open(plugin_path, "w") as f:
                f.write(plugin_code)

        return plugin_dir

    def test_load_plugin_with_valid_manifest_compatible(self):
        """Test loading plugin with compatible manifest."""
        manifest = {
            "plugin": {
                "key": "test-plugin",
                "name": "Test Plugin",
                "version": "1.0.0",
                "description": "A test plugin",
                "repository": "https://github.com/test/plugin",
                "authors": ["Test Author"],
                "icon": "star",
                "requires": {"dispatcharr": ">=0.1.0"},
            }
        }
        plugin_code = '''
class Plugin:
    name = "Test Plugin"
    version = "1.0.0"
    fields = []
    actions = [{"id": "test", "label": "Test"}]

    def run(self, action_id, params, context):
        return {"status": "ok"}
'''
        self._create_plugin("test_plugin", manifest, plugin_code)

        # Import fresh PluginManager
        with patch("apps.plugins.version.__version__", "0.18.1"):
            from apps.plugins.loader import PluginManager

            # Reset singleton
            PluginManager._instance = None
            pm = PluginManager.get()
            pm.plugins_dir = self.temp_dir

            pm.discover_plugins(sync_db=False)

            plugin = pm.get_plugin("test_plugin")
            self.assertIsNotNone(plugin)
            self.assertTrue(plugin.compatible)
            self.assertEqual(plugin.compatibility_error, "")
            self.assertEqual(plugin.name, "Test Plugin")
            self.assertEqual(plugin.version, "1.0.0")
            self.assertEqual(plugin.repository, "https://github.com/test/plugin")
            self.assertEqual(plugin.authors, ["Test Author"])
            self.assertEqual(plugin.icon, "star")
            self.assertTrue(plugin.has_manifest)

    def test_load_plugin_with_incompatible_manifest(self):
        """Test loading plugin with incompatible version requirement."""
        manifest = {
            "plugin": {
                "key": "future-plugin",
                "name": "Future Plugin",
                "version": "1.0.0",
                "requires": {"dispatcharr": ">=99.0.0"},
            }
        }
        plugin_code = '''
class Plugin:
    name = "Future Plugin"
    version = "1.0.0"
    fields = []
    actions = []

    def run(self, action_id, params, context):
        return {"status": "ok"}
'''
        self._create_plugin("future_plugin", manifest, plugin_code)

        with patch("apps.plugins.version.__version__", "0.18.1"):
            from apps.plugins.loader import PluginManager

            PluginManager._instance = None
            pm = PluginManager.get()
            pm.plugins_dir = self.temp_dir

            pm.discover_plugins(sync_db=False)

            plugin = pm.get_plugin("future_plugin")
            self.assertIsNotNone(plugin)
            self.assertFalse(plugin.compatible)
            self.assertIn("Requires Dispatcharr >=99.0.0", plugin.compatibility_error)
            self.assertIn("0.18.1", plugin.compatibility_error)
            # Python code should NOT be loaded
            self.assertIsNone(plugin.instance)
            self.assertTrue(plugin.has_manifest)

    def test_load_plugin_without_manifest_backwards_compat(self):
        """Test loading plugin without manifest (backwards compatibility)."""
        plugin_code = '''
class Plugin:
    name = "Legacy Plugin"
    version = "2.0.0"
    description = "A legacy plugin without manifest"
    fields = []
    actions = []

    def run(self, action_id, params, context):
        return {"status": "ok"}
'''
        self._create_plugin("legacy_plugin", manifest=None, plugin_code=plugin_code)

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        plugin = pm.get_plugin("legacy_plugin")
        self.assertIsNotNone(plugin)
        self.assertTrue(plugin.compatible)  # No manifest = compatible by default
        self.assertEqual(plugin.compatibility_error, "")
        self.assertEqual(plugin.name, "Legacy Plugin")
        self.assertEqual(plugin.version, "2.0.0")
        self.assertEqual(plugin.repository, "")
        self.assertEqual(plugin.authors, [])
        self.assertFalse(plugin.has_manifest)

    def test_load_plugin_with_malformed_manifest(self):
        """Test loading plugin with malformed YAML manifest."""
        plugin_dir = os.path.join(self.temp_dir, "broken_plugin")
        os.makedirs(plugin_dir, exist_ok=True)

        manifest_path = os.path.join(plugin_dir, "plugin.yaml")
        with open(manifest_path, "w") as f:
            f.write("invalid: yaml: [[[")

        plugin_path = os.path.join(plugin_dir, "plugin.py")
        with open(plugin_path, "w") as f:
            f.write('''
class Plugin:
    name = "Broken"
    def run(self, a, p, c): pass
''')

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        plugin = pm.get_plugin("broken_plugin")
        self.assertIsNotNone(plugin)
        self.assertFalse(plugin.compatible)
        self.assertIn("Malformed plugin.yaml", plugin.compatibility_error)

    def test_load_plugin_with_invalid_manifest_fields(self):
        """Test loading plugin with missing required manifest fields."""
        manifest = {
            "plugin": {
                "key": "incomplete-plugin",
                # Missing 'name' and 'version'
            }
        }
        self._create_plugin("incomplete_plugin", manifest, plugin_code='''
class Plugin:
    name = "Incomplete"
    def run(self, a, p, c): pass
''')

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        plugin = pm.get_plugin("incomplete_plugin")
        self.assertIsNotNone(plugin)
        self.assertFalse(plugin.compatible)
        self.assertIn("Invalid manifest", plugin.compatibility_error)

    def test_manifest_metadata_overrides_class_attributes(self):
        """Test that manifest metadata takes precedence over Plugin class."""
        manifest = {
            "plugin": {
                "key": "override-plugin",
                "name": "Manifest Name",
                "version": "3.0.0",
                "description": "From manifest",
            }
        }
        plugin_code = '''
class Plugin:
    name = "Class Name"
    version = "1.0.0"
    description = "From class"
    fields = []
    actions = []

    def run(self, action_id, params, context):
        return {"status": "ok"}
'''
        self._create_plugin("override_plugin", manifest, plugin_code)

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        plugin = pm.get_plugin("override_plugin")
        self.assertIsNotNone(plugin)
        # Manifest values should take precedence
        self.assertEqual(plugin.name, "Manifest Name")
        self.assertEqual(plugin.version, "3.0.0")
        self.assertEqual(plugin.description, "From manifest")

    def test_list_plugins_includes_compatibility_info(self):
        """Test that list_plugins includes compatibility fields."""
        manifest = {
            "plugin": {
                "key": "listed-plugin",
                "name": "Listed Plugin",
                "version": "1.0.0",
                "repository": "https://example.com",
                "authors": ["Author"],
                "icon": "box",
            }
        }
        plugin_code = '''
class Plugin:
    fields = []
    actions = []
    def run(self, a, p, c): pass
'''
        self._create_plugin("listed_plugin", manifest, plugin_code)

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)
        plugins = pm.list_plugins()

        listed = next((p for p in plugins if p["key"] == "listed_plugin"), None)
        self.assertIsNotNone(listed)
        self.assertIn("compatible", listed)
        self.assertIn("compatibility_error", listed)
        self.assertIn("repository", listed)
        self.assertIn("authors", listed)
        self.assertIn("icon", listed)
        self.assertIn("has_manifest", listed)
        self.assertTrue(listed["compatible"])
        self.assertEqual(listed["repository"], "https://example.com")
        self.assertEqual(listed["authors"], ["Author"])
        self.assertEqual(listed["icon"], "box")
        self.assertTrue(listed["has_manifest"])

    def test_version_range_constraint(self):
        """Test plugin with version range constraint."""
        manifest = {
            "plugin": {
                "key": "range-plugin",
                "name": "Range Plugin",
                "version": "1.0.0",
                "requires": {"dispatcharr": ">=0.18.0,<0.19.0"},
            }
        }
        plugin_code = '''
class Plugin:
    fields = []
    actions = []
    def run(self, a, p, c): pass
'''
        self._create_plugin("range_plugin", manifest, plugin_code)

        # Test compatible version
        with patch("apps.plugins.version.__version__", "0.18.5"):
            from apps.plugins.loader import PluginManager

            PluginManager._instance = None
            pm = PluginManager.get()
            pm.plugins_dir = self.temp_dir

            pm.discover_plugins(sync_db=False)

            plugin = pm.get_plugin("range_plugin")
            self.assertTrue(plugin.compatible)

    def test_version_range_constraint_above_max(self):
        """Test plugin fails when version is above range maximum."""
        manifest = {
            "plugin": {
                "key": "range_plugin2",
                "name": "Range Plugin 2",
                "version": "1.0.0",
                "requires": {"dispatcharr": ">=0.18.0,<0.19.0"},
            }
        }
        plugin_code = '''
class Plugin:
    fields = []
    actions = []
    def run(self, a, p, c): pass
'''
        self._create_plugin("range_plugin2", manifest, plugin_code)

        with patch("apps.plugins.version.__version__", "0.19.0"):
            from apps.plugins.loader import PluginManager

            PluginManager._instance = None
            pm = PluginManager.get()
            pm.plugins_dir = self.temp_dir

            pm.discover_plugins(sync_db=False)

            plugin = pm.get_plugin("range_plugin2")
            self.assertFalse(plugin.compatible)
            self.assertIn(">=0.18.0,<0.19.0", plugin.compatibility_error)
