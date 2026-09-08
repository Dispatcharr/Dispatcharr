import importlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from apps.plugins.models import PluginConfig


class PluginCapabilityMigrationTests(TestCase):
    def setUp(self):
        self.migration_0004 = importlib.import_module(
            "apps.plugins.migrations.0004_plugin_acknowledged_capabilities"
        )
        self.migration_0005 = importlib.import_module(
            "apps.plugins.migrations.0005_repair_acknowledged_capabilities"
        )

    def _write_manifest(self, plugins_dir, key, manifest):
        plugin_dir = Path(plugins_dir, key)
        plugin_dir.mkdir()
        Path(plugin_dir, "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_initial_seed_uses_the_plugin_effective_capabilities(self):
        PluginConfig.objects.create(key="declared", name="Declared", ever_enabled=True)
        PluginConfig.objects.create(key="async", name="Async", ever_enabled=True)
        PluginConfig.objects.create(key="legacy", name="Legacy", ever_enabled=True)

        with tempfile.TemporaryDirectory() as plugins_dir, patch.dict(
            os.environ, {"DISPATCHARR_PLUGINS_DIR": plugins_dir}
        ):
            self._write_manifest(
                plugins_dir, "declared", {"manifest_version": 2, "capabilities": ["subprocess"]}
            )
            self._write_manifest(
                plugins_dir, "async", {"manifest_version": 2, "actions": [{"id": "run", "async": True}]}
            )
            self.migration_0004.seed_acknowledged_capabilities(apps, None)

        self.assertEqual(
            PluginConfig.objects.get(key="declared").acknowledged_capabilities, ["subprocess"]
        )
        self.assertEqual(
            PluginConfig.objects.get(key="async").acknowledged_capabilities, ["background_tasks"]
        )
        self.assertEqual(PluginConfig.objects.get(key="legacy").acknowledged_capabilities, [])

    def test_repair_only_replaces_the_old_global_seed(self):
        old_seed = sorted(self.migration_0005.SEEDED_CAPABILITIES)
        PluginConfig.objects.create(
            key="seeded", name="Seeded", ever_enabled=True, acknowledged_capabilities=old_seed
        )
        PluginConfig.objects.create(
            key="later-consent",
            name="Later consent",
            ever_enabled=True,
            acknowledged_capabilities=["background_tasks", "subprocess"],
        )

        with tempfile.TemporaryDirectory() as plugins_dir, patch.dict(
            os.environ, {"DISPATCHARR_PLUGINS_DIR": plugins_dir}
        ):
            self._write_manifest(
                plugins_dir, "seeded", {"manifest_version": 2, "capabilities": ["background_tasks"]}
            )
            self._write_manifest(
                plugins_dir,
                "later-consent",
                {"manifest_version": 2, "capabilities": ["background_tasks"]},
            )
            self.migration_0005.repair_acknowledged_capabilities(apps, None)

        self.assertEqual(
            PluginConfig.objects.get(key="seeded").acknowledged_capabilities, ["background_tasks"]
        )
        self.assertEqual(
            PluginConfig.objects.get(key="later-consent").acknowledged_capabilities,
            ["background_tasks", "subprocess"],
        )
