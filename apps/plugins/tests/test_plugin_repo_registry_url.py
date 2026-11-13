from django.test import SimpleTestCase

from apps.plugins.models import PluginRepo
from apps.plugins.serializers import PluginRepoSerializer


class PluginRepoRegistryUrlTests(SimpleTestCase):
    def test_registry_url_from_flat_and_wrapped_manifests(self):
        for manifest in (
            {"registry_url": "https://example.com/repo"},
            {"manifest": {"registry_url": "https://example.com/repo"}},
        ):
            with self.subTest(manifest=manifest):
                repo = PluginRepo(cached_manifest=manifest)
                self.assertEqual(repo.registry_url, "https://example.com/repo")
                self.assertEqual(PluginRepoSerializer(repo).data["registry_url"], repo.registry_url)

    def test_missing_registry_url_is_empty(self):
        self.assertEqual(PluginRepo(cached_manifest={}).registry_url, "")
