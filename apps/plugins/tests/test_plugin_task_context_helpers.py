"""context['report_progress'] and context['dispatch_task'], the two helpers
_build_context adds for async plugin actions (see PluginManager.run_action)."""

from unittest.mock import ANY, MagicMock, patch

from django.test import SimpleTestCase

from apps.plugins.loader import LoadedPlugin, PluginManager


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
        with patch("core.utils.send_websocket_update") as mock_send, patch(
            "apps.plugins.task_history.record_task_progress"
        ) as mock_record:
            report_progress(50, "halfway")

        mock_send.assert_called_once_with("updates", "update", {
            "type": "plugin_task_progress",
            "plugin": "my-plugin",
            "task_id": "task-1",
            "percent": 50,
            "message": "halfway",
            "updatedAt": ANY,
        })
        mock_record.assert_called_once_with("my-plugin", "task-1", 50, "halfway")


class DispatchTaskTests(SimpleTestCase):
    def _lp(self, capabilities=("background_tasks",)):
        return LoadedPlugin(
            key="my-plugin",
            name="My Plugin",
            actions=[{"id": "do_work", "label": "Do Work"}],
            capabilities=list(capabilities),
        )

    def test_raises_permission_error_without_background_tasks_capability(self):
        pm = PluginManager()
        dispatch_task = pm._make_task_dispatcher(self._lp(capabilities=()))

        with patch("apps.plugins.tasks.run_plugin_action_task.apply_async") as mock_apply_async:
            with self.assertRaises(PermissionError):
                dispatch_task("do_work")

        mock_apply_async.assert_not_called()

    def test_dispatches_to_plugins_queue_and_returns_task_id(self):
        pm = PluginManager()
        dispatch_task = pm._make_task_dispatcher(self._lp())

        async_result = MagicMock(id="task-2")
        with patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async", return_value=async_result
        ) as mock_apply_async, patch(
            "apps.plugins.task_history.record_task_started"
        ) as mock_record:
            task_id = dispatch_task("do_work", {"limit": 5})

        self.assertEqual(task_id, "task-2")
        mock_apply_async.assert_called_once_with(
            args=["my-plugin", "do_work", {"limit": 5}], queue="plugins"
        )
        mock_record.assert_called_once_with("my-plugin", "task-2", "do_work", "Do Work")

    def test_default_params_is_empty_dict(self):
        pm = PluginManager()
        dispatch_task = pm._make_task_dispatcher(self._lp())

        with patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async",
            return_value=MagicMock(id="task-3"),
        ) as mock_apply_async, patch("apps.plugins.task_history.record_task_started"):
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
