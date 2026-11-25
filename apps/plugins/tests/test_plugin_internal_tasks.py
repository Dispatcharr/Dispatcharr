from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.plugins.internal_tasks import (
    _PLUGIN_TASKS,
    dispatch_plugin_task,
    plugin_callable_task,
)
from apps.plugins.loader import LoadedPlugin, PluginManager


class PluginInternalTaskRegistryTests(SimpleTestCase):
    def test_registered_task_is_dispatched_to_plugins_queue(self):
        task = MagicMock()
        task.name = "apps.example.tasks.safe_task"
        task.apply_async.return_value = MagicMock(id="task-1")
        with patch.dict(_PLUGIN_TASKS, {}, clear=True):
            plugin_callable_task(task)
            result = dispatch_plugin_task(task.name, args=[1], kwargs={"force": True})

        self.assertEqual(result.id, "task-1")
        task.apply_async.assert_called_once_with(
            args=[1], kwargs={"force": True}, queue="plugins"
        )

    def test_unregistered_task_is_rejected(self):
        with patch.dict(_PLUGIN_TASKS, {}, clear=True):
            with self.assertRaises(ValueError):
                dispatch_plugin_task("apps.accounts.tasks.delete_user")

    def test_refresh_tasks_are_registered(self):
        from apps.epg.tasks import refresh_epg_data
        from apps.m3u.tasks import refresh_single_m3u_account

        self.assertIs(_PLUGIN_TASKS[refresh_epg_data.name], refresh_epg_data)
        self.assertIs(
            _PLUGIN_TASKS[refresh_single_m3u_account.name], refresh_single_m3u_account
        )


class PluginInternalTaskDispatcherTests(SimpleTestCase):
    def _plugin(self, capabilities=("celery_dispatch",), manifest_version=2):
        return LoadedPlugin(
            key="example",
            name="Example",
            capabilities=list(capabilities),
            manifest_schema_version=manifest_version,
        )

    def test_v2_requires_celery_dispatch_capability(self):
        dispatcher = PluginManager()._make_internal_task_dispatcher(
            self._plugin(capabilities=())
        )
        with patch("apps.plugins.internal_tasks.dispatch_plugin_task") as dispatch:
            with self.assertRaises(PermissionError):
                dispatcher("apps.m3u.tasks.refresh_single_m3u_account", [1])
        dispatch.assert_not_called()

    def test_legacy_and_v1_manifests_remain_advisory(self):
        for manifest_version in (0, 1):
            with self.subTest(manifest_version=manifest_version):
                result = MagicMock(id=f"task-{manifest_version}")
                dispatcher = PluginManager()._make_internal_task_dispatcher(
                    self._plugin(capabilities=(), manifest_version=manifest_version)
                )
                with patch(
                    "apps.plugins.internal_tasks.dispatch_plugin_task", return_value=result
                ) as dispatch:
                    self.assertEqual(
                        dispatcher("apps.m3u.tasks.refresh_single_m3u_account", [1]),
                        result.id,
                    )
                dispatch.assert_called_once_with(
                    "apps.m3u.tasks.refresh_single_m3u_account", args=[1], kwargs=None
                )

    def test_dispatcher_returns_task_id(self):
        result = MagicMock(id="task-2")
        dispatcher = PluginManager()._make_internal_task_dispatcher(self._plugin())
        with patch(
            "apps.plugins.internal_tasks.dispatch_plugin_task", return_value=result
        ) as dispatch:
            self.assertEqual(
                dispatcher("apps.epg.tasks.refresh_epg_data", [2], {"force": True}),
                "task-2",
            )
        dispatch.assert_called_once_with(
            "apps.epg.tasks.refresh_epg_data", args=[2], kwargs={"force": True}
        )
