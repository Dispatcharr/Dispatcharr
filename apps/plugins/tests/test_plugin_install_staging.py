import errno
import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.api_views import _create_plugin_import_dir


class PluginInstallStagingTests(SimpleTestCase):
    def test_creates_import_directory_under_plugin_staging(self):
        with tempfile.TemporaryDirectory() as plugins_dir:
            import_dir = _create_plugin_import_dir(plugins_dir)
            staging_dir = os.path.join(plugins_dir, ".staging")
            try:
                self.assertEqual(os.path.dirname(import_dir), staging_dir)
            finally:
                os.rmdir(import_dir)

    def test_falls_back_to_system_temp_for_staging_permission_error(self):
        with (
            patch(
                "apps.plugins.api_views.os.makedirs",
                side_effect=PermissionError(errno.EACCES, "Permission denied"),
            ),
            patch(
                "apps.plugins.api_views.tempfile.mkdtemp",
                return_value="/tmp/plugin_import_fallback",
            ) as mkdtemp,
            self.assertLogs("apps.plugins.api_views", level="WARNING") as logs,
        ):
            import_dir = _create_plugin_import_dir("/plugins")

        self.assertEqual(import_dir, "/tmp/plugin_import_fallback")
        mkdtemp.assert_called_once_with(prefix="plugin_import_")
        self.assertIn("falling back to the system temporary directory", logs.output[0])

    def test_does_not_fall_back_for_other_staging_errors(self):
        with (
            patch(
                "apps.plugins.api_views.os.makedirs",
                side_effect=OSError(errno.ENOSPC, "No space left on device"),
            ),
            patch("apps.plugins.api_views.tempfile.mkdtemp") as mkdtemp,
        ):
            with self.assertRaisesRegex(OSError, "No space left on device"):
                _create_plugin_import_dir("/plugins")

        mkdtemp.assert_not_called()
