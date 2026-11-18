from io import BytesIO
import json
import os
import tempfile
from unittest.mock import MagicMock, patch
import zipfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.plugins.api_views import PluginInstallFromRepoAPIView
from apps.plugins.models import PluginConfig, PluginRepo


class PluginUpdateCapabilityConfirmationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="plugin_update_admin", password="x", user_level=User.UserLevel.ADMIN
        )
        self.repo = PluginRepo.objects.create(name="Test Repo", url="https://example.com/manifest.json")
        self.cfg = PluginConfig.objects.create(
            key="my_plugin",
            name="My Plugin",
            version="1.0.0",
            slug="my-plugin",
            source_repo=self.repo,
            enabled=True,
            acknowledged_capabilities=["background_tasks"],
        )
        self.factory = APIRequestFactory()

    def _archive(self, manifest):
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("plugin.py", "")
            zf.writestr("plugin.json", json.dumps(manifest))
        return archive.getvalue()

    def _request(self, **data):
        request = self.factory.post(
            "/api/plugins/repos/install/",
            {
                "repo_id": self.repo.id,
                "slug": "my-plugin",
                "version": "2.0.0",
                "download_url": "https://example.com/plugin.zip",
                **data,
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        return request

    def _download(self, content):
        response = MagicMock()
        response.iter_content.return_value = [content]
        response.raise_for_status.return_value = None
        return response

    def test_enabled_update_with_new_capability_requires_confirmation(self):
        content = self._archive({"manifest_version": 2, "capabilities": ["persistent_service"]})
        with patch("apps.plugins.api_views.get_with_validated_redirects", return_value=self._download(content)), patch(
            "apps.plugins.api_views._install_plugin_from_zip"
        ) as install:
            response = PluginInstallFromRepoAPIView.as_view()(self._request())

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error_code"], "capability_confirmation_required")
        self.assertEqual(response.data["capabilities"][0]["id"], "persistent_service")
        install.assert_not_called()
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.enabled)
        self.assertEqual(self.cfg.acknowledged_capabilities, ["background_tasks"])

    def test_denied_capability_update_disables_and_resets_acknowledgements(self):
        content = self._archive({"manifest_version": 2, "capabilities": ["persistent_service"]})
        pm = MagicMock()
        pm.list_plugins.return_value = []
        with patch("apps.plugins.api_views.get_with_validated_redirects", return_value=self._download(content)), patch(
            "apps.plugins.api_views.PluginManager.get", return_value=pm
        ):
            response = PluginInstallFromRepoAPIView.as_view()(
                self._request(deny_capabilities=True)
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["capability_confirmation_denied"])
        pm.stop_plugin.assert_called_once_with("my_plugin", reason="capability_update_denied")
        self.cfg.refresh_from_db()
        self.assertFalse(self.cfg.enabled)
        self.assertEqual(self.cfg.acknowledged_capabilities, [])

    def test_confirmed_update_installs_and_records_new_acknowledgement(self):
        content = self._archive({"manifest_version": 2, "capabilities": ["persistent_service"]})
        pm = MagicMock()
        pm.list_plugins.return_value = [{"key": "my_plugin", "enabled": True}]
        with patch("apps.plugins.api_views.get_with_validated_redirects", return_value=self._download(content)), patch(
            "apps.plugins.api_views.PluginManager.get", return_value=pm
        ), patch(
            "apps.plugins.api_views._install_plugin_from_zip",
            return_value={"success": True, "plugin_key": "my_plugin"},
        ) as install:
            response = PluginInstallFromRepoAPIView.as_view()(
                self._request(acknowledge_capabilities=["persistent_service"])
            )

        self.assertEqual(response.status_code, 200)
        install.assert_called_once()
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.enabled)
        self.assertEqual(
            self.cfg.acknowledged_capabilities,
            ["background_tasks", "persistent_service"],
        )

    def test_async_action_is_a_new_background_task_capability(self):
        self.cfg.acknowledged_capabilities = []
        self.cfg.save(update_fields=["acknowledged_capabilities"])
        content = self._archive({"manifest_version": 2, "actions": [{"id": "sync", "async": True}]})
        with patch("apps.plugins.api_views.get_with_validated_redirects", return_value=self._download(content)):
            response = PluginInstallFromRepoAPIView.as_view()(self._request())

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["capabilities"][0]["id"], "background_tasks")

    def test_update_without_new_capabilities_installs_immediately(self):
        content = self._archive({"manifest_version": 2, "capabilities": ["background_tasks"]})
        pm = MagicMock()
        pm.list_plugins.return_value = [{"key": "my_plugin", "enabled": True}]
        with patch("apps.plugins.api_views.get_with_validated_redirects", return_value=self._download(content)), patch(
            "apps.plugins.api_views.PluginManager.get", return_value=pm
        ), patch(
            "apps.plugins.api_views._install_plugin_from_zip",
            return_value={"success": True, "plugin_key": "my_plugin"},
        ) as install:
            response = PluginInstallFromRepoAPIView.as_view()(self._request())

        self.assertEqual(response.status_code, 200)
        install.assert_called_once()

    def test_adoption_requires_approval_before_install_and_records_it_before_discovery(self):
        other_repo = PluginRepo.objects.create(name="Other Repo", url="https://other.example/manifest.json")
        for source in (None, other_repo):
            for version in (1, 2):
                with self.subTest(source=source, manifest_version=version), tempfile.TemporaryDirectory() as directory:
                    self.cfg.source_repo = source
                    self.cfg.enabled = True
                    self.cfg.acknowledged_capabilities = []
                    self.cfg.save()
                    plugin_dir = os.path.join(directory, "my_plugin")
                    os.mkdir(plugin_dir)
                    with open(os.path.join(plugin_dir, "plugin.py"), "w") as old_file:
                        old_file.write("# legacy")
                    archive = BytesIO()
                    with zipfile.ZipFile(archive, "w") as zf:
                        zf.writestr("my_plugin/plugin.py", "# updated")
                        zf.writestr("my_plugin/plugin.json", json.dumps({
                            "manifest_version": version, "capabilities": ["persistent_service"],
                        }))
                    pm = MagicMock()
                    pm.plugins_dir = directory
                    pm.list_plugins.return_value = []

                    def check_discovery(**kwargs):
                        self.cfg.refresh_from_db()
                        self.assertEqual(self.cfg.acknowledged_capabilities, ["persistent_service"])
                        self.assertEqual(self.cfg.source_repo, self.repo)

                    with patch("apps.plugins.api_views.PluginManager.get", return_value=pm), patch(
                        "apps.plugins.api_views.get_with_validated_redirects",
                        side_effect=lambda *args, **kwargs: self._download(archive.getvalue()),
                    ):
                        response = PluginInstallFromRepoAPIView.as_view()(self._request())
                        self.assertEqual(response.status_code, 409)
                        self.cfg.refresh_from_db()
                        self.assertEqual(self.cfg.source_repo, source)
                        self.assertTrue(self.cfg.enabled)
                        self.assertEqual(self.cfg.acknowledged_capabilities, [])
                        with open(os.path.join(plugin_dir, "plugin.py")) as old_file:
                            self.assertEqual(old_file.read(), "# legacy")
                        pm.discover_plugins.assert_not_called()

                        pm.discover_plugins.side_effect = check_discovery
                        response = PluginInstallFromRepoAPIView.as_view()(
                            self._request(acknowledge_capabilities=["persistent_service"])
                        )
                        self.assertEqual(response.status_code, 200)
                        self.cfg.refresh_from_db()
                        self.assertTrue(self.cfg.enabled)
                        with open(os.path.join(plugin_dir, "plugin.py")) as new_file:
                            self.assertEqual(new_file.read(), "# updated")
                        pm.discover_plugins.assert_called_once()

    def test_archive_key_config_is_checked_even_when_directory_is_missing(self):
        self.cfg.source_repo = None
        self.cfg.save()
        target = PluginConfig.objects.create(key="different", name="Different", enabled=True)
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("different/plugin.py", "")
            zf.writestr("different/plugin.json", json.dumps({
                "manifest_version": 2, "capabilities": ["persistent_service"],
            }))
        with tempfile.TemporaryDirectory() as directory:
            pm = MagicMock(plugins_dir=directory)
            with patch("apps.plugins.api_views.PluginManager.get", return_value=pm), patch(
                "apps.plugins.api_views.get_with_validated_redirects", return_value=self._download(archive.getvalue())
            ):
                response = PluginInstallFromRepoAPIView.as_view()(self._request())
            self.assertEqual(response.status_code, 409)
            self.assertFalse(os.path.exists(os.path.join(directory, "different")))
            target.refresh_from_db()
            self.assertIsNone(target.source_repo)
            pm.discover_plugins.assert_not_called()

    def test_denied_adoption_disables_original_without_replacing_files(self):
        self.cfg.source_repo = None
        self.cfg.acknowledged_capabilities = []
        self.cfg.save()
        content = self._archive({"manifest_version": 1, "capabilities": ["persistent_service"]})
        # A flat archive uses the slug, so make the existing key match it.
        self.cfg.key = "my-plugin"
        self.cfg.save()
        with tempfile.TemporaryDirectory() as directory:
            plugin_dir = os.path.join(directory, "my-plugin")
            os.mkdir(plugin_dir)
            with open(os.path.join(plugin_dir, "plugin.py"), "w") as old_file:
                old_file.write("# legacy")
            pm = MagicMock(plugins_dir=directory)
            pm.list_plugins.return_value = []
            with patch("apps.plugins.api_views.PluginManager.get", return_value=pm), patch(
                "apps.plugins.api_views.get_with_validated_redirects", return_value=self._download(content)
            ):
                response = PluginInstallFromRepoAPIView.as_view()(self._request(deny_capabilities=True))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data["capability_confirmation_denied"])
            self.cfg.refresh_from_db()
            self.assertFalse(self.cfg.enabled)
            self.assertIsNone(self.cfg.source_repo)
            with open(os.path.join(plugin_dir, "plugin.py")) as old_file:
                self.assertEqual(old_file.read(), "# legacy")
            pm.stop_plugin.assert_called_once_with("my-plugin", reason="capability_update_denied")

    def test_failed_adoption_does_not_record_approval(self):
        self.cfg.source_repo = None
        self.cfg.acknowledged_capabilities = []
        self.cfg.save()
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("my_plugin/plugin.py", "")
            zf.writestr("my_plugin/plugin.json", json.dumps({
                "manifest_version": 2, "capabilities": ["persistent_service"],
            }))
        with tempfile.TemporaryDirectory() as directory:
            pm = MagicMock(plugins_dir=directory)
            with patch("apps.plugins.api_views.PluginManager.get", return_value=pm), patch(
                "apps.plugins.api_views.get_with_validated_redirects", return_value=self._download(archive.getvalue())
            ), patch("apps.plugins.api_views._install_plugin_from_zip", return_value={"success": False, "error": "failed"}):
                response = PluginInstallFromRepoAPIView.as_view()(
                    self._request(acknowledge_capabilities=["persistent_service"])
                )
            self.assertEqual(response.status_code, 400)
            self.cfg.refresh_from_db()
            self.assertEqual(self.cfg.acknowledged_capabilities, [])
            self.assertIsNone(self.cfg.source_repo)
            pm.discover_plugins.assert_not_called()
