"""Tests for plugin manifest parsing and validation."""

import os
import tempfile
from unittest import TestCase

import yaml

from apps.plugins.manifest import (
    extract_manifest_metadata,
    load_manifest,
    validate_manifest,
)


class TestLoadManifest(TestCase):
    """Test cases for load_manifest function."""

    def test_load_valid_manifest(self):
        """Test loading a valid plugin.yaml file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_content = {
                "plugin": {
                    "key": "test-plugin",
                    "name": "Test Plugin",
                    "version": "1.0.0",
                }
            }
            manifest_path = os.path.join(tmpdir, "plugin.yaml")
            with open(manifest_path, "w") as f:
                yaml.dump(manifest_content, f)

            result = load_manifest(tmpdir)
            self.assertIsNotNone(result)
            self.assertEqual(result["plugin"]["key"], "test-plugin")
            self.assertEqual(result["plugin"]["name"], "Test Plugin")

    def test_load_missing_manifest(self):
        """Test loading from directory without plugin.yaml returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_manifest(tmpdir)
            self.assertIsNone(result)

    def test_load_malformed_yaml(self):
        """Test loading malformed YAML raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "plugin.yaml")
            with open(manifest_path, "w") as f:
                f.write("invalid: yaml: content: [[[")

            with self.assertRaises(yaml.YAMLError):
                load_manifest(tmpdir)

    def test_load_full_manifest(self):
        """Test loading a manifest with all fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_content = {
                "plugin": {
                    "key": "full-plugin",
                    "name": "Full Plugin",
                    "version": "2.0.0",
                    "description": "A complete plugin",
                    "repository": "https://github.com/example/plugin",
                    "authors": ["Author One", "Author Two"],
                    "icon": "calendar",
                    "requires": {"dispatcharr": ">=0.18.0"},
                }
            }
            manifest_path = os.path.join(tmpdir, "plugin.yaml")
            with open(manifest_path, "w") as f:
                yaml.dump(manifest_content, f)

            result = load_manifest(tmpdir)
            self.assertEqual(result["plugin"]["description"], "A complete plugin")
            self.assertEqual(result["plugin"]["authors"], ["Author One", "Author Two"])
            self.assertEqual(result["plugin"]["requires"]["dispatcharr"], ">=0.18.0")


class TestValidateManifest(TestCase):
    """Test cases for validate_manifest function."""

    def test_valid_minimal_manifest(self):
        """Test validation of minimal valid manifest."""
        data = {
            "plugin": {
                "key": "my-plugin",
                "name": "My Plugin",
                "version": "1.0.0",
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_valid_full_manifest(self):
        """Test validation of manifest with all fields."""
        data = {
            "plugin": {
                "key": "full-plugin",
                "name": "Full Plugin",
                "version": "1.0.0",
                "description": "A plugin",
                "repository": "https://github.com/example",
                "authors": ["Author"],
                "icon": "star",
                "requires": {"dispatcharr": ">=0.18.0"},
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_invalid_non_dict(self):
        """Test validation fails for non-dict input."""
        is_valid, errors = validate_manifest("not a dict")
        self.assertFalse(is_valid)
        self.assertIn("Manifest must be a YAML object", errors)

    def test_invalid_missing_plugin_section(self):
        """Test validation fails when plugin section is missing."""
        data = {"other": "data"}
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("Missing or invalid 'plugin' section", errors)

    def test_invalid_missing_key(self):
        """Test validation fails when key is missing."""
        data = {
            "plugin": {
                "name": "My Plugin",
                "version": "1.0.0",
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field: plugin.key", errors)

    def test_invalid_missing_name(self):
        """Test validation fails when name is missing."""
        data = {
            "plugin": {
                "key": "my-plugin",
                "version": "1.0.0",
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field: plugin.name", errors)

    def test_invalid_missing_version(self):
        """Test validation fails when version is missing."""
        data = {
            "plugin": {
                "key": "my-plugin",
                "name": "My Plugin",
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field: plugin.version", errors)

    def test_invalid_key_type(self):
        """Test validation fails when key is not a string."""
        data = {
            "plugin": {
                "key": 123,
                "name": "My Plugin",
                "version": "1.0.0",
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("Field 'plugin.key' must be a string", errors)

    def test_invalid_authors_type(self):
        """Test validation fails when authors is not a list."""
        data = {
            "plugin": {
                "key": "my-plugin",
                "name": "My Plugin",
                "version": "1.0.0",
                "authors": "Single Author",
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("Field 'plugin.authors' must be a list", errors)

    def test_invalid_authors_content(self):
        """Test validation fails when authors contains non-strings."""
        data = {
            "plugin": {
                "key": "my-plugin",
                "name": "My Plugin",
                "version": "1.0.0",
                "authors": ["Author One", 123],
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("All entries in 'plugin.authors' must be strings", errors)

    def test_invalid_requires_type(self):
        """Test validation fails when requires is not a dict."""
        data = {
            "plugin": {
                "key": "my-plugin",
                "name": "My Plugin",
                "version": "1.0.0",
                "requires": ">=0.18.0",
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("Field 'plugin.requires' must be an object", errors)

    def test_invalid_requires_dispatcharr_type(self):
        """Test validation fails when requires.dispatcharr is not a string."""
        data = {
            "plugin": {
                "key": "my-plugin",
                "name": "My Plugin",
                "version": "1.0.0",
                "requires": {"dispatcharr": 18},
            }
        }
        is_valid, errors = validate_manifest(data)
        self.assertFalse(is_valid)
        self.assertIn("Field 'plugin.requires.dispatcharr' must be a string", errors)


class TestExtractManifestMetadata(TestCase):
    """Test cases for extract_manifest_metadata function."""

    def test_extract_minimal(self):
        """Test extracting metadata from minimal manifest."""
        data = {
            "plugin": {
                "key": "my-plugin",
                "name": "My Plugin",
                "version": "1.0.0",
            }
        }
        meta = extract_manifest_metadata(data)
        self.assertEqual(meta["key"], "my-plugin")
        self.assertEqual(meta["name"], "My Plugin")
        self.assertEqual(meta["version"], "1.0.0")
        self.assertEqual(meta["description"], "")
        self.assertEqual(meta["repository"], "")
        self.assertEqual(meta["authors"], [])
        self.assertEqual(meta["icon"], "")
        self.assertEqual(meta["requires_dispatcharr"], "")

    def test_extract_full(self):
        """Test extracting metadata from full manifest."""
        data = {
            "plugin": {
                "key": "full-plugin",
                "name": "Full Plugin",
                "version": "2.0.0",
                "description": "A complete plugin",
                "repository": "https://github.com/example/plugin",
                "authors": ["Author One", "Author Two"],
                "icon": "calendar",
                "requires": {"dispatcharr": ">=0.18.0,<1.0.0"},
            }
        }
        meta = extract_manifest_metadata(data)
        self.assertEqual(meta["key"], "full-plugin")
        self.assertEqual(meta["name"], "Full Plugin")
        self.assertEqual(meta["version"], "2.0.0")
        self.assertEqual(meta["description"], "A complete plugin")
        self.assertEqual(meta["repository"], "https://github.com/example/plugin")
        self.assertEqual(meta["authors"], ["Author One", "Author Two"])
        self.assertEqual(meta["icon"], "calendar")
        self.assertEqual(meta["requires_dispatcharr"], ">=0.18.0,<1.0.0")

    def test_extract_missing_plugin_section(self):
        """Test extraction handles missing plugin section gracefully."""
        data = {}
        meta = extract_manifest_metadata(data)
        self.assertEqual(meta["key"], "")
        self.assertEqual(meta["name"], "")

    def test_version_converted_to_string(self):
        """Test that numeric version is converted to string."""
        data = {
            "plugin": {
                "key": "test",
                "name": "Test",
                "version": 1.0,
            }
        }
        meta = extract_manifest_metadata(data)
        self.assertEqual(meta["version"], "1.0")
        self.assertIsInstance(meta["version"], str)
