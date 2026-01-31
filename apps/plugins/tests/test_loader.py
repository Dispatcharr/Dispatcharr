"""Tests for plugin loader with manifest support."""

import os
import shutil
import sys

# Configure Django before importing any Django-dependent modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")

import django

django.setup()

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "plugins"


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
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _copy_fixture(self, fixture_name, dest_name=None):
        """Copy a fixture plugin to the temp directory."""
        src = FIXTURES_DIR / fixture_name
        dest_name = dest_name or fixture_name
        dest = Path(self.temp_dir) / dest_name
        shutil.copytree(src, dest)
        return dest

    def test_load_plugin_with_valid_manifest_compatible(self):
        """Test loading plugin with compatible manifest."""
        self._copy_fixture("compatible_plugin")

        with patch("apps.plugins.version.__version__", "0.18.1"):
            from apps.plugins.loader import PluginManager

            PluginManager._instance = None
            pm = PluginManager.get()
            pm.plugins_dir = self.temp_dir

            pm.discover_plugins(sync_db=False)

            plugin = pm.get_plugin("compatible_plugin")
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
        self._copy_fixture("incompatible_plugin")

        with patch("apps.plugins.version.__version__", "0.18.1"):
            from apps.plugins.loader import PluginManager

            PluginManager._instance = None
            pm = PluginManager.get()
            pm.plugins_dir = self.temp_dir

            pm.discover_plugins(sync_db=False)

            plugin = pm.get_plugin("incompatible_plugin")
            self.assertIsNotNone(plugin)
            self.assertFalse(plugin.compatible)
            self.assertIn("Requires Dispatcharr >=99.0.0", plugin.compatibility_error)
            self.assertIn("0.18.1", plugin.compatibility_error)
            # Python code should NOT be loaded
            self.assertIsNone(plugin.instance)
            self.assertTrue(plugin.has_manifest)

    def test_load_plugin_without_manifest_backwards_compat(self):
        """Test loading plugin without manifest (backwards compatibility)."""
        self._copy_fixture("legacy_plugin")

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
        self._copy_fixture("malformed_manifest_plugin")

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        plugin = pm.get_plugin("malformed_manifest_plugin")
        self.assertIsNotNone(plugin)
        self.assertFalse(plugin.compatible)
        self.assertIn("Malformed plugin.yaml", plugin.compatibility_error)

    def test_load_plugin_with_invalid_manifest_fields(self):
        """Test loading plugin with missing required manifest fields."""
        self._copy_fixture("incomplete_manifest_plugin")

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        plugin = pm.get_plugin("incomplete_manifest_plugin")
        self.assertIsNotNone(plugin)
        self.assertFalse(plugin.compatible)
        self.assertIn("Invalid manifest", plugin.compatibility_error)

    def test_manifest_metadata_overrides_class_attributes(self):
        """Test that manifest metadata takes precedence over Plugin class."""
        self._copy_fixture("override_plugin")

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
        self._copy_fixture("listed_plugin")

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
        self._copy_fixture("range_constraint_plugin")

        # Test compatible version
        with patch("apps.plugins.version.__version__", "0.18.5"):
            from apps.plugins.loader import PluginManager

            PluginManager._instance = None
            pm = PluginManager.get()
            pm.plugins_dir = self.temp_dir

            pm.discover_plugins(sync_db=False)

            plugin = pm.get_plugin("range_constraint_plugin")
            self.assertTrue(plugin.compatible)

    def test_version_range_constraint_above_max(self):
        """Test plugin fails when version is above range maximum."""
        self._copy_fixture("range_constraint_plugin", "range_constraint_plugin2")

        with patch("apps.plugins.version.__version__", "0.19.0"):
            from apps.plugins.loader import PluginManager

            PluginManager._instance = None
            pm = PluginManager.get()
            pm.plugins_dir = self.temp_dir

            pm.discover_plugins(sync_db=False)

            plugin = pm.get_plugin("range_constraint_plugin2")
            self.assertFalse(plugin.compatible)
            self.assertIn(">=0.18.0,<0.19.0", plugin.compatibility_error)

    def test_manifest_key_loaded_from_manifest(self):
        """Test that manifest_key is properly loaded from plugin.yaml."""
        self._copy_fixture("compatible_plugin")

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        plugin = pm.get_plugin("compatible_plugin")
        self.assertIsNotNone(plugin)
        self.assertEqual(plugin.manifest_key, "test-plugin")

    def test_manifest_key_empty_for_legacy_plugin(self):
        """Test that manifest_key is empty for plugins without manifest."""
        self._copy_fixture("legacy_plugin")

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        plugin = pm.get_plugin("legacy_plugin")
        self.assertIsNotNone(plugin)
        self.assertEqual(plugin.manifest_key, "")

    def test_get_plugins_by_manifest_key(self):
        """Test finding plugins with the same manifest_key."""
        self._copy_fixture("duplicate_key_plugin_a")
        self._copy_fixture("duplicate_key_plugin_b")

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        # Both plugins should have the same manifest_key
        plugin_a = pm.get_plugin("duplicate_key_plugin_a")
        plugin_b = pm.get_plugin("duplicate_key_plugin_b")
        self.assertEqual(plugin_a.manifest_key, "shared-plugin-key")
        self.assertEqual(plugin_b.manifest_key, "shared-plugin-key")

        # get_plugins_by_manifest_key should find both
        matches = pm.get_plugins_by_manifest_key("shared-plugin-key")
        self.assertEqual(sorted(matches), ["duplicate_key_plugin_a", "duplicate_key_plugin_b"])

        # With exclude_key, should find only the other one
        matches = pm.get_plugins_by_manifest_key("shared-plugin-key", exclude_key="duplicate_key_plugin_a")
        self.assertEqual(matches, ["duplicate_key_plugin_b"])

    def test_get_plugins_by_manifest_key_empty(self):
        """Test that empty manifest_key returns no matches."""
        self._copy_fixture("legacy_plugin")

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)

        # Empty manifest_key should return empty list
        matches = pm.get_plugins_by_manifest_key("")
        self.assertEqual(matches, [])

    def test_list_plugins_includes_manifest_key(self):
        """Test that list_plugins includes manifest_key field."""
        self._copy_fixture("compatible_plugin")

        from apps.plugins.loader import PluginManager

        PluginManager._instance = None
        pm = PluginManager.get()
        pm.plugins_dir = self.temp_dir

        pm.discover_plugins(sync_db=False)
        plugins = pm.list_plugins()

        plugin = next((p for p in plugins if p["key"] == "compatible_plugin"), None)
        self.assertIsNotNone(plugin)
        self.assertIn("manifest_key", plugin)
        self.assertEqual(plugin["manifest_key"], "test-plugin")
