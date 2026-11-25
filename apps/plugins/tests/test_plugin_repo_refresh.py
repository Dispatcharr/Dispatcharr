from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.plugins.models import PluginConfig, PluginRepo


class PluginRepoRefreshAPIViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="plugin-refresh-admin", password="testpass123", user_level=10
        )
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.repo = PluginRepo.objects.create(
            name="Old registry", url="https://plugins.example.test/manifest.json"
        )

    def test_refreshes_root_manifest_and_unmanages_removed_plugins(self):
        config = PluginConfig.objects.create(
            key="local-plugin",
            name="Removed Plugin",
            slug="removed-plugin",
            source_repo=self.repo,
        )
        manifest = {
            "manifest": {
                "registry_name": "Updated registry",
                "plugins": [
                    {
                        "slug": "current-plugin",
                        "manifest_url": "https://plugins.example.test/current.json",
                    }
                ],
            }
        }

        with (
            patch("apps.plugins.api_views._fetch_manifest", return_value=(manifest, True)),
            patch("apps.plugins.api_views.cache.delete_many") as delete_many,
        ):
            response = self.client.post(f"/api/plugins/repos/{self.repo.id}/refresh/")

        self.assertEqual(response.status_code, 200)
        self.repo.refresh_from_db()
        config.refresh_from_db()
        self.assertEqual(self.repo.name, "Updated registry")
        self.assertEqual(self.repo.cached_manifest, manifest)
        self.assertTrue(self.repo.signature_verified)
        self.assertIsNone(config.source_repo)
        self.assertEqual(config.slug, "removed-plugin")
        delete_many.assert_called_once()

    def test_returns_bad_gateway_when_root_manifest_fetch_fails(self):
        with patch(
            "apps.plugins.api_views._fetch_manifest", side_effect=RuntimeError("offline")
        ):
            response = self.client.post(f"/api/plugins/repos/{self.repo.id}/refresh/")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["error"], "Failed to fetch manifest. Check the URL and try again.")

    def test_retained_slug_is_listed_as_unmanaged(self):
        self.repo.cached_manifest = {"manifest": {"plugins": [{"slug": "canonical-plugin"}]}}
        self.repo.save(update_fields=["cached_manifest"])
        PluginConfig.objects.create(
            key="different-local-key", name="Plugin", slug="canonical-plugin", version="1.0"
        )
        response = self.client.get("/api/plugins/repos/available/")
        self.assertEqual(response.status_code, 200)
        plugin = next(p for p in response.data["plugins"] if p["slug"] == "canonical-plugin")
        self.assertTrue(plugin["installed"])
        self.assertEqual(plugin["install_status"], "unmanaged")

    def test_rejects_an_invalid_root_manifest(self):
        with patch(
            "apps.plugins.api_views._fetch_manifest", return_value=({"manifest": {}}, True)
        ):
            response = self.client.post(f"/api/plugins/repos/{self.repo.id}/refresh/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("registry_name", response.data["error"])
