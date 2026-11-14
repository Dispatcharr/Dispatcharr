import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.plugins.models import PluginConfig


class PluginDataUninstallTests(TestCase):
    def test_uninstall_data_choices(self):
        user = get_user_model().objects.create_user(username="data-admin", password="x", user_level=10)
        client = APIClient()
        client.force_authenticate(user=user)
        for choice in ("keep", "delete", "empty"):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as root:
                config = PluginConfig.objects.create(key="example", name="Example")
                code = Path(root, "example")
                code.mkdir()
                data = Path(root, "_data", "example")
                data.mkdir(parents=True)
                if choice != "empty":
                    (data / "saved.txt").write_text("saved")
                manager = Mock(plugins_dir=root)
                manager.get_plugin.return_value = None
                manager.get_plugin_path.return_value = str(code)
                with patch("apps.plugins.api_views.PluginManager.get", return_value=manager):
                    response = client.delete("/api/plugins/plugins/example/delete/", format="json")
                    if choice != "empty":
                        self.assertEqual(response.status_code, 409)
                        self.assertTrue(code.exists())
                        self.assertTrue(PluginConfig.objects.filter(pk=config.pk).exists())
                        response = client.delete(
                            "/api/plugins/plugins/example/delete/", {"data_action": choice}, format="json"
                        )
                    self.assertEqual(response.status_code, 200)
                self.assertFalse(code.exists())
                self.assertEqual(data.exists(), choice == "keep")
