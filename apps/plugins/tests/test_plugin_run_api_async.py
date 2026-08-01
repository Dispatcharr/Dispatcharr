"""PluginRunAPIView's three dispatch paths: legacy inline, per-action async
manifest flag, and the toggle-on synchronous-but-dedicated-worker path."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.plugins.api_views import PluginRunAPIView
from apps.plugins.loader import LoadedPlugin, PluginManager
from apps.plugins.models import PluginConfig


class PluginRunAPIViewAsyncTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="plugin_run_admin", password="x", user_level=User.UserLevel.ADMIN
        )
        self.factory = APIRequestFactory()

        self.cfg = PluginConfig.objects.create(key="my-plugin", name="My Plugin", enabled=True)

        self.plugin = LoadedPlugin(
            key="my-plugin",
            name="My Plugin",
            instance=MagicMock(),
            actions=[
                {"id": "quick", "label": "Quick"},
                {"id": "slow", "label": "Slow", "async": True},
            ],
        )
        pm = PluginManager()
        self._pm_patcher = patch.object(PluginManager, "get", return_value=pm)
        self._pm_patcher.start()
        self.addCleanup(self._pm_patcher.stop)
        self.pm = pm
        self._get_plugin_patcher = patch.object(pm, "get_plugin", return_value=self.plugin)
        self._get_plugin_patcher.start()
        self.addCleanup(self._get_plugin_patcher.stop)

    def _post(self, action, params=None):
        request = self.factory.post(
            f"/api/plugins/plugins/{self.plugin.key}/run/",
            {"action": action, "params": params or {}},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        return PluginRunAPIView.as_view()(request, key=self.plugin.key)

    @patch("core.models.CoreSettings.get_plugin_dedicated_worker_enabled", return_value=False)
    def test_legacy_action_runs_inline_when_toggle_off(self, _mock_toggle):
        with patch.object(self.pm, "run_action", return_value={"status": "ok"}) as mock_run:
            response = self._post("quick")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"success": True, "result": {"status": "ok"}})
        mock_run.assert_called_once_with("my-plugin", "quick", {})

    def test_async_manifest_action_dispatches_without_waiting_regardless_of_toggle(self):
        async_result = MagicMock(id="task-123")
        with patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async", return_value=async_result
        ) as mock_apply_async, patch.object(self.pm, "run_action") as mock_run:
            response = self._post("slow")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data, {"success": True, "status": "started", "task_id": "task-123"}
        )
        mock_apply_async.assert_called_once_with(args=["my-plugin", "slow", {}], queue="plugins")
        mock_run.assert_not_called()

    @patch("core.models.CoreSettings.get_plugin_dedicated_worker_enabled", return_value=True)
    def test_toggle_on_non_async_action_blocks_for_result_with_unchanged_response_shape(
        self, _mock_toggle
    ):
        async_result = MagicMock(id="task-456")
        async_result.get.return_value = {"status": "ok", "processed": 5}
        with patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async", return_value=async_result
        ) as mock_apply_async:
            response = self._post("quick")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data, {"success": True, "result": {"status": "ok", "processed": 5}}
        )
        mock_apply_async.assert_called_once_with(args=["my-plugin", "quick", {}], queue="plugins")
        async_result.get.assert_called_once()

    @patch("core.models.CoreSettings.get_plugin_dedicated_worker_enabled", return_value=True)
    def test_toggle_on_timeout_returns_504_with_task_id(self, _mock_toggle):
        from celery.exceptions import TimeoutError as CeleryTimeoutError

        async_result = MagicMock(id="task-789")
        async_result.get.side_effect = CeleryTimeoutError()
        with patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async", return_value=async_result
        ):
            response = self._post("quick")

        self.assertEqual(response.status_code, 504)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["task_id"], "task-789")

    def test_plugin_self_dispatched_started_result_is_normalized(self):
        """A plugin can call context['dispatch_task'] itself from a
        non-async-flagged action's run() and return {"status": "started",
        "task_id": ...}: the view must flatten this the same as the
        manifest-flag path, not wrap it under "result"."""
        with patch("core.models.CoreSettings.get_plugin_dedicated_worker_enabled", return_value=False), \
             patch.object(
                 self.pm, "run_action", return_value={"status": "started", "task_id": "self-1"}
             ):
            response = self._post("quick")

        self.assertEqual(response.data, {"success": True, "status": "started", "task_id": "self-1"})
