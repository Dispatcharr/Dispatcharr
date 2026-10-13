import io
import os
import tempfile
import zipfile
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.plugins.models import PluginConfig, PluginRepo


class ManagedPluginRepoInstallTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="plugin-admin", password="testpass123", user_level=10
        )
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.repo = PluginRepo.objects.create(
            name="Test plugins", url="https://plugins.example.test/manifest.json"
        )

    def _zip_response(self, directory):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"{directory}/plugin.py", "UPDATED = True\n")

        response = Mock()
        response.iter_content.return_value = [archive.getvalue()]
        return response

    def test_update_uses_managed_install_key_when_zip_key_differs_from_slug(self):
        config = PluginConfig.objects.create(
            key="zip_plugin",
            name="ZIP plugin",
            version="1.0.0",
            slug="registry-plugin",
            source_repo=self.repo,
            enabled=True,
            settings={"keep": "this"},
        )

        with tempfile.TemporaryDirectory() as plugins_dir:
            existing_dir = os.path.join(plugins_dir, config.key)
            os.makedirs(existing_dir)
            with open(os.path.join(existing_dir, "plugin.py"), "w") as plugin_file:
                plugin_file.write("UPDATED = False\n")

            plugin_manager = Mock(plugins_dir=plugins_dir)
            plugin_manager.list_plugins.return_value = []
            response = self._zip_response("archive_plugin")

            with (
                patch(
                    "apps.plugins.api_views.get_with_validated_redirects",
                    return_value=response,
                ),
                patch(
                    "apps.plugins.api_views.PluginManager.get",
                    return_value=plugin_manager,
                ),
            ):
                result = self.client.post(
                    "/api/plugins/repos/install/",
                    {
                        "repo_id": self.repo.id,
                        "slug": "registry-plugin",
                        "version": "2.0.0",
                        "download_url": "https://plugins.example.test/registry-plugin.zip",
                    },
                    format="json",
                )

            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.data["success"])
            self.assertEqual(PluginConfig.objects.count(), 1)

            config.refresh_from_db()
            self.assertEqual(config.key, "zip_plugin")
            self.assertEqual(config.version, "2.0.0")
            self.assertEqual(config.source_repo, self.repo)
            self.assertTrue(config.enabled)
            self.assertEqual(config.settings, {"keep": "this"})
            self.assertFalse(os.path.exists(os.path.join(plugins_dir, "archive_plugin")))

            with open(os.path.join(existing_dir, "plugin.py")) as plugin_file:
                self.assertEqual(plugin_file.read(), "UPDATED = True\n")
            plugin_manager.discover_plugins.assert_called_once_with(force_reload=True)
            response.close.assert_called_once()

    def test_legacy_normalized_key_lookup_remains_available(self):
        PluginConfig.objects.create(
            key="legacy_plugin",
            name="Legacy plugin",
            version="1.0.0",
        )
        response = self._zip_response("legacy_plugin")
        plugin_manager = Mock(plugins_dir="/unused")
        plugin_manager.list_plugins.return_value = []

        with (
            patch(
                "apps.plugins.api_views.get_with_validated_redirects",
                return_value=response,
            ),
            patch(
                "apps.plugins.api_views.PluginManager.get",
                return_value=plugin_manager,
            ),
            patch(
                "apps.plugins.api_views._install_plugin_from_zip",
                return_value={"success": True, "plugin_key": "legacy_plugin"},
            ) as install,
        ):
            result = self.client.post(
                "/api/plugins/repos/install/",
                {
                    "repo_id": self.repo.id,
                    "slug": "legacy-plugin",
                    "version": "2.0.0",
                    "download_url": "https://plugins.example.test/legacy-plugin.zip",
                },
                format="json",
            )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(install.call_args.kwargs["allow_overwrite_key"], "legacy_plugin")
        self.assertIsNone(install.call_args.kwargs["install_key"])

    def test_failed_managed_update_preserves_existing_configuration(self):
        config = PluginConfig.objects.create(
            key="zip_plugin",
            name="ZIP plugin",
            version="1.0.0",
            slug="registry-plugin",
            source_repo=self.repo,
            enabled=True,
            settings={"keep": "this"},
        )
        response = self._zip_response(config.key)
        plugin_manager = Mock(plugins_dir="/unused")

        with (
            patch(
                "apps.plugins.api_views.get_with_validated_redirects",
                return_value=response,
            ),
            patch(
                "apps.plugins.api_views.PluginManager.get",
                return_value=plugin_manager,
            ),
            patch(
                "apps.plugins.api_views._install_plugin_from_zip",
                return_value={"success": False, "error": "Update rejected"},
            ),
        ):
            result = self.client.post(
                "/api/plugins/repos/install/",
                {
                    "repo_id": self.repo.id,
                    "slug": "registry-plugin",
                    "version": "2.0.0",
                    "download_url": "https://plugins.example.test/registry-plugin.zip",
                },
                format="json",
            )

        self.assertEqual(result.status_code, 400)
        config.refresh_from_db()
        self.assertEqual(config.version, "1.0.0")
        self.assertEqual(config.slug, "registry-plugin")
        self.assertEqual(config.source_repo, self.repo)
        self.assertTrue(config.enabled)
        self.assertEqual(config.settings, {"keep": "this"})
        response.close.assert_called_once()

    def test_update_consolidates_duplicate_managed_slug_records(self):
        config = PluginConfig.objects.create(
            key="stable_plugin",
            name="Stable plugin",
            version="1.0.0",
            slug="registry-plugin",
            source_repo=self.repo,
            enabled=True,
            settings={"keep": "this"},
        )
        stale_config = PluginConfig.objects.create(
            key="archive_plugin",
            name="Archive plugin",
            version="1.0.0",
            slug="registry-plugin",
            source_repo=self.repo,
        )

        with tempfile.TemporaryDirectory() as plugins_dir:
            stable_dir = os.path.join(plugins_dir, config.key)
            stale_dir = os.path.join(plugins_dir, stale_config.key)
            os.makedirs(stable_dir)
            os.makedirs(stale_dir)
            with open(os.path.join(stable_dir, "plugin.py"), "w") as plugin_file:
                plugin_file.write("UPDATED = False\n")
            with open(os.path.join(stale_dir, "plugin.py"), "w") as plugin_file:
                plugin_file.write("STALE = True\n")

            plugin_manager = Mock(plugins_dir=plugins_dir)
            plugin_manager.list_plugins.return_value = []
            response = self._zip_response(stale_config.key)

            with (
                patch(
                    "apps.plugins.api_views.get_with_validated_redirects",
                    return_value=response,
                ),
                patch(
                    "apps.plugins.api_views.PluginManager.get",
                    return_value=plugin_manager,
                ),
            ):
                result = self.client.post(
                    "/api/plugins/repos/install/",
                    {
                        "repo_id": self.repo.id,
                        "slug": "registry-plugin",
                        "version": "2.0.0",
                        "download_url": "https://plugins.example.test/registry-plugin.zip",
                    },
                    format="json",
                )

            self.assertEqual(result.status_code, 200)
            self.assertEqual(PluginConfig.objects.count(), 1)
            config.refresh_from_db()
            self.assertEqual(config.key, "stable_plugin")
            self.assertEqual(config.version, "2.0.0")
            self.assertTrue(config.enabled)
            self.assertEqual(config.settings, {"keep": "this"})
            self.assertFalse(os.path.exists(stale_dir))

            with open(os.path.join(stable_dir, "plugin.py")) as plugin_file:
                self.assertEqual(plugin_file.read(), "UPDATED = True\n")
