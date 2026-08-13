"""PluginEnabledAPIView.post's acknowledged_capabilities bookkeeping: enabling
a plugin should union its current effective capabilities into
PluginConfig.acknowledged_capabilities, so a later manifest update that adds
a capability shows up as un-acknowledged again (see needsCapabilityAck on the
frontend, frontend/src/store/plugins.jsx)."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.plugins.api_views import PluginEnabledAPIView
from apps.plugins.loader import LoadedPlugin, PluginManager
from apps.plugins.models import PluginConfig


class PluginEnabledAPICapabilityAckTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="plugin_enable_admin", password="x", user_level=User.UserLevel.ADMIN
        )
        self.factory = APIRequestFactory()

        self.cfg = PluginConfig.objects.create(
            key="my-plugin", name="My Plugin", enabled=False, acknowledged_capabilities=[]
        )

        pm = PluginManager()
        self._pm_patcher = patch.object(PluginManager, "get", return_value=pm)
        self._pm_patcher.start()
        self.addCleanup(self._pm_patcher.stop)
        self.pm = pm

    def _post(self, enabled):
        request = self.factory.post(
            "/api/plugins/plugins/my-plugin/enabled/", {"enabled": enabled}, format="json"
        )
        force_authenticate(request, user=self.admin)
        return PluginEnabledAPIView.as_view()(request, key="my-plugin")

    def _lp(self, capabilities):
        return LoadedPlugin(key="my-plugin", name="My Plugin", capabilities=list(capabilities))

    def test_enabling_unions_effective_capabilities_into_acknowledged(self):
        with patch.object(self.pm, "discover_plugins"), patch.object(
            self.pm, "get_plugin", return_value=self._lp(["background_tasks"])
        ), patch.object(self.pm, "list_plugins", return_value=[]):
            response = self._post(True)

        self.assertEqual(response.status_code, 200)
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.acknowledged_capabilities, ["background_tasks"])

    def test_reenabling_adds_newly_declared_capability(self):
        self.cfg.acknowledged_capabilities = ["background_tasks"]
        self.cfg.enabled = False
        self.cfg.save(update_fields=["acknowledged_capabilities", "enabled"])

        with patch.object(self.pm, "discover_plugins"), patch.object(
            self.pm,
            "get_plugin",
            return_value=self._lp(["background_tasks", "persistent_service"]),
        ), patch.object(self.pm, "list_plugins", return_value=[]):
            response = self._post(True)

        self.assertEqual(response.status_code, 200)
        self.cfg.refresh_from_db()
        self.assertEqual(
            sorted(self.cfg.acknowledged_capabilities),
            ["background_tasks", "persistent_service"],
        )

    def test_disabling_does_not_touch_acknowledged_capabilities(self):
        self.cfg.enabled = True
        self.cfg.acknowledged_capabilities = ["background_tasks"]
        self.cfg.save(update_fields=["enabled", "acknowledged_capabilities"])

        with patch.object(self.pm, "stop_plugin", return_value=True), patch.object(
            self.pm, "discover_plugins"
        ), patch.object(self.pm, "list_plugins", return_value=[]):
            response = self._post(False)

        self.assertEqual(response.status_code, 200)
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.acknowledged_capabilities, ["background_tasks"])
