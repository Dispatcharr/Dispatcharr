from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.plugins.api_views import PluginsListAPIView
from apps.plugins.loader import PluginManager


class PluginListPermissionTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.plugins = [
            {"key": "enabled", "name": "Enabled", "enabled": True,
             "settings": {"token": "secret", "nested": {"password": "secret"}}},
            {"key": "disabled", "name": "Disabled", "enabled": False,
             "settings": {"undeclared": "secret"}},
            {"key": "missing", "name": "Missing", "missing": True,
             "settings": {"password": "secret"}},
        ]

    def get_plugins(self, level):
        user = SimpleNamespace(is_authenticated=True, user_level=level)
        request = self.factory.get("/api/plugins/plugins/")
        force_authenticate(request, user=user)
        with patch("apps.accounts.permissions.network_access_allowed", return_value=True), \
             patch.object(PluginManager, "get") as get_manager:
            get_manager.return_value.list_plugins.return_value = self.plugins
            return PluginsListAPIView.as_view()(request)

    def test_standard_user_cannot_read_settings(self):
        response = self.get_plugins(User.UserLevel.STANDARD)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["key"] for p in response.data["plugins"]],
                         ["enabled", "disabled", "missing"])
        for plugin in response.data["plugins"]:
            self.assertNotIn("settings", plugin)

    def test_admin_can_read_settings(self):
        response = self.get_plugins(User.UserLevel.ADMIN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["plugins"][0]["settings"]["token"], "secret")

    def test_streamer_is_denied(self):
        response = self.get_plugins(User.UserLevel.STREAMER)
        self.assertEqual(response.status_code, 403)
