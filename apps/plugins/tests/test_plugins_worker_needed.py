"""plugins_worker_needed management command: decides whether the dedicated
`plugins` Celery worker should be started at container boot."""

import json
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.plugins.models import PluginConfig


class PluginsWorkerNeededTests(TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="dispatcharr-plugins-worker-needed-")
        self._env = patch.dict(os.environ, {"DISPATCHARR_PLUGINS_DIR": self._tmpdir})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)

    def _make_plugin(self, key, manifest=None, enabled=True):
        plugin_dir = os.path.join(self._tmpdir, key)
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(plugin_dir, "plugin.py"), "w") as fh:
            fh.write("")
        if manifest is not None:
            with open(os.path.join(plugin_dir, "plugin.json"), "w") as fh:
                json.dump(manifest, fh)
        PluginConfig.objects.create(key=key, name=key, enabled=enabled)

    def _run(self):
        out, err = StringIO(), StringIO()
        try:
            call_command("plugins_worker_needed", stdout=out, stderr=err)
            return 0
        except SystemExit as exc:
            return exc.code

    def test_no_plugins_not_needed(self):
        self.assertEqual(self._run(), 1)

    def test_no_enabled_plugins_not_needed(self):
        self._make_plugin("idle", manifest={"name": "Idle"}, enabled=False)
        self.assertEqual(self._run(), 1)

    def test_enabled_plugin_with_background_tasks_capability_needed(self):
        self._make_plugin(
            "worker-plugin",
            manifest={"name": "Worker Plugin", "capabilities": ["background_tasks"]},
        )
        self.assertEqual(self._run(), 0)

    def test_enabled_plugin_with_async_action_needed_via_backcompat(self):
        self._make_plugin(
            "async-plugin",
            manifest={
                "name": "Async Plugin",
                "actions": [{"id": "go", "label": "Go", "async": True}],
            },
        )
        self.assertEqual(self._run(), 0)

    def test_enabled_plugin_without_capability_not_needed(self):
        self._make_plugin("plain-plugin", manifest={"name": "Plain Plugin"})
        self.assertEqual(self._run(), 1)

    def test_disabled_plugin_with_capability_not_needed(self):
        self._make_plugin(
            "disabled-plugin",
            manifest={"name": "Disabled Plugin", "capabilities": ["background_tasks"]},
            enabled=False,
        )
        self.assertEqual(self._run(), 1)

    def test_missing_manifest_treated_as_no_capability(self):
        self._make_plugin("no-manifest", manifest=None)
        self.assertEqual(self._run(), 1)
