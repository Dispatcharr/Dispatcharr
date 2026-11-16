import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.field_versions import FIELD_ATTRIBUTE_VERSIONS, FIELD_TYPE_VERSIONS, feature_supported
from apps.plugins.loader import PluginManager
from apps.plugins.serializers import PluginFieldSerializer


class FieldVersionTests(SimpleTestCase):
    def test_registry_covers_all_serializer_types(self):
        self.assertEqual(set(PluginFieldSerializer().fields["type"].choices), set(FIELD_TYPE_VERSIONS))
        for name in ("string", "number", "boolean", "select", "text", "info"):
            self.assertTrue(feature_supported(FIELD_TYPE_VERSIONS[name], 0))
        for name in ("multiselect", "section", "table", "file"):
            self.assertFalse(feature_supported(FIELD_TYPE_VERSIONS[name], 0))
            self.assertTrue(feature_supported(FIELD_TYPE_VERSIONS[name], 1))

    def test_type_and_attribute_versions(self):
        fields = [
            {"id": "notes", "type": "text", "rows": 8, "section": "advanced"},
            {"id": "advanced", "type": "section", "collapsed": True},
            {"id": "choices", "type": "multiselect"},
            {"id": "table", "type": "table"},
            {"id": "file", "type": "file"},
            {"id": "info", "type": "info"},
        ]
        original = copy.deepcopy(fields)
        pm = PluginManager()
        with self.assertLogs("apps.plugins.loader", level="WARNING"):
            legacy = pm._normalize_fields(fields, 0)
        self.assertEqual([f["id"] for f in legacy], ["notes", "info"])
        self.assertNotIn("rows", legacy[0])
        self.assertNotIn("section", legacy[0])
        self.assertEqual(fields, original)
        for version in (1, 2, 99):
            result = pm._normalize_fields(fields, version)
            self.assertEqual([f["id"] for f in result], [f["id"] for f in fields])
            self.assertEqual(result[0]["rows"], 8)
            self.assertEqual(result[0]["section"], "advanced")

    def test_extensible_bounds_and_unknown_types(self):
        bounds = {"min_manifest_version": 3, "max_manifest_version": 4}
        self.assertFalse(feature_supported(bounds, 2))
        self.assertTrue(feature_supported(bounds, 3))
        self.assertFalse(feature_supported(bounds, 5))
        with patch.dict(FIELD_TYPE_VERSIONS, {"text": bounds}):
            with self.assertLogs("apps.plugins.loader", level="WARNING"):
                self.assertEqual(PluginManager()._normalize_fields([{"id": "x", "type": "text"}], 2), [])
        with patch.dict(FIELD_ATTRIBUTE_VERSIONS, {"rows": {**bounds, "field_types": {"text"}}}):
            field = {"id": "x", "type": "text", "rows": 5}
            with self.assertLogs("apps.plugins.loader", level="WARNING"):
                self.assertNotIn("rows", PluginManager()._normalize_fields([field], 2)[0])
            self.assertEqual(PluginManager()._normalize_fields([field], 3)[0]["rows"], 5)
        with self.assertLogs("apps.plugins.loader", level="WARNING"):
            self.assertEqual(PluginManager()._normalize_fields([{"id": "x", "type": "unknown"}], 99), [])

    def test_attribute_bounds_apply_only_to_matching_types(self):
        fields = [
            {"id": "text", "type": "text", "rows": 5},
            {"id": "string", "type": "string", "rows": 5, "section": "group"},
        ]
        with self.assertLogs("apps.plugins.loader", level="WARNING"):
            result = PluginManager()._normalize_fields(fields, 0)
        self.assertNotIn("rows", result[0])
        self.assertEqual(result[1]["rows"], 5)
        self.assertNotIn("section", result[1])

    def test_manifest_and_python_fields_share_version_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "example")
            path.mkdir()
            manifest = {"fields": [{"id": "manifest_file", "type": "file"}]}
            (path / "plugin.py").write_text(
                "class Plugin:\n"
                "    def get_fields(self, context):\n"
                "        return [{'id': 'python_text', 'type': 'text', 'rows': 6}, "
                "{'id': 'python_file', 'type': 'file'}]\n"
            )
            pm = PluginManager()
            for version in (None, "invalid", 1, 2, 99):
                if version is None:
                    manifest.pop("manifest_version", None)
                else:
                    manifest["manifest_version"] = version
                (path / "plugin.json").write_text(json.dumps(manifest))
                expected = version in (1, 2, 99)
                disabled, _, _ = pm._load_and_merge_plugin_entry(
                    "example", "example", str(path), cfg=None, force_reload=False, previous_package=None,
                )
                self.assertEqual(bool(disabled.fields), expected)
                cfg = SimpleNamespace(enabled=True, ever_enabled=True, slug="", settings={}, version="", description="")
                enabled, _, _ = pm._load_and_merge_plugin_entry(
                    "example", "example", str(path), cfg=cfg, force_reload=True, previous_package=None,
                )
                self.assertTrue(enabled.loaded)
                self.assertEqual(len(enabled.fields), 2 if expected else 1)
                self.assertEqual("rows" in enabled.fields[0], expected)
