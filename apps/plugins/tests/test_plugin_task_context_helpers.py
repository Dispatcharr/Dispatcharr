"""context['report_progress'] and context['dispatch_task'], the two helpers
_build_context adds for async plugin actions (see PluginManager.run_action)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.plugins.loader import PluginManager


class ReportProgressTests(SimpleTestCase):
    def test_no_op_when_task_id_is_none(self):
        pm = PluginManager()
        report_progress = pm._make_progress_reporter("my-plugin", task_id=None)
        with patch("core.utils.send_websocket_update") as mock_send:
            report_progress(50, "halfway")
        mock_send.assert_not_called()

    def test_sends_websocket_update_when_task_id_present(self):
        pm = PluginManager()
        report_progress = pm._make_progress_reporter("my-plugin", task_id="task-1")
        with patch("core.utils.send_websocket_update") as mock_send:
            report_progress(50, "halfway")

        mock_send.assert_called_once_with("updates", "update", {
            "type": "plugin_task_progress",
            "plugin": "my-plugin",
            "task_id": "task-1",
            "percent": 50,
            "message": "halfway",
        })


class DispatchTaskTests(SimpleTestCase):
    def test_dispatches_to_plugins_queue_and_returns_task_id(self):
        pm = PluginManager()
        dispatch_task = pm._make_task_dispatcher("my-plugin")

        async_result = MagicMock(id="task-2")
        with patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async", return_value=async_result
        ) as mock_apply_async:
            task_id = dispatch_task("do_work", {"limit": 5})

        self.assertEqual(task_id, "task-2")
        mock_apply_async.assert_called_once_with(
            args=["my-plugin", "do_work", {"limit": 5}], queue="plugins"
        )

    def test_default_params_is_empty_dict(self):
        pm = PluginManager()
        dispatch_task = pm._make_task_dispatcher("my-plugin")

        with patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async",
            return_value=MagicMock(id="task-3"),
        ) as mock_apply_async:
            dispatch_task("do_work")

        mock_apply_async.assert_called_once_with(
            args=["my-plugin", "do_work", {}], queue="plugins"
        )


class RunActionResponseNormalizationTests(SimpleTestCase):
    def test_plugin_returned_started_shape_passes_through_unchanged(self):
        """run_action() itself doesn't need to normalize; it already
        returns the plugin's dict as-is; normalization for the API-view
        contract lives in PluginRunAPIView._response_for_result."""
        instance = MagicMock()
        instance.run = MagicMock(return_value={"status": "started", "task_id": "self-1"})
        from apps.plugins.loader import LoadedPlugin

        lp = LoadedPlugin(key="my-plugin", name="My Plugin", instance=instance)
        pm = PluginManager()
        cfg = MagicMock(enabled=True, settings={})
        with patch.object(pm, "get_plugin", return_value=lp), patch(
            "apps.plugins.loader.PluginConfig.objects.get", return_value=cfg
        ):
            result = pm.run_action("my-plugin", "quick")

        self.assertEqual(result, {"status": "started", "task_id": "self-1"})
