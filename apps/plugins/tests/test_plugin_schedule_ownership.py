import io
import importlib.util
import inspect
import json
import os
import py_compile
import shutil
import stat
import subprocess
import sys
import threading
import time
import zipfile
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from apps.plugins.api_views import PluginInstallFromRepoAPIView, _install_plugin_from_zip
from apps.plugins.loader import PluginManager
from apps.plugins.models import PluginConfig, PluginRepo
from apps.plugins.tests.test_plugin_schedule_lifecycle import (
    LifecycleFixture,
    _JOBS_PY,
    _PLUGIN_PY,
)
from dispatcharr.celery import app as celery_app


class ManagedPluginScheduleFixture(LifecycleFixture):
    def setUp(self):
        super().setUp()
        self.repo = PluginRepo.objects.create(
            name="Test plugins", url="https://plugins.example.test/manifest.json"
        )
        self._install("retained")
        self._install("duplicate")
        PluginConfig.objects.filter(key__in=["retained", "duplicate"]).update(
            source_repo=self.repo, slug="registry-plugin"
        )
        self.shared = self._schedule("shared", self._custom_name("retained"))
        self.old = self._schedule("old", self._custom_name("duplicate"), enabled=False)
        self.other = self._schedule("other", "unrelated.tick")
        PluginConfig.objects.filter(key="duplicate").update(
            owned_tasks=[self.old.task, self.shared.task],
            suspended_schedules=[self.old.pk, self.shared.pk],
        )

    def _update(self):
        response = Mock()
        response.iter_content.return_value = [b"archive"]
        request = self._factory.post(
            "/api/plugins/repos/install/",
            {
                "repo_id": self.repo.pk, "slug": "registry-plugin",
                "version": "2.0", "download_url": "https://plugins.example.test/plugin.zip",
            },
            format="json",
        )
        with (
            patch.object(PluginInstallFromRepoAPIView, "get_permissions", return_value=[]),
            patch("apps.plugins.api_views.get_with_validated_redirects", return_value=response),
            patch("apps.plugins.api_views._install_plugin_from_zip", return_value={
                "success": True, "plugin_key": "retained",
            }),
        ):
            return PluginInstallFromRepoAPIView.as_view()(request)


class ManagedPluginScheduleConsolidationTests(ManagedPluginScheduleFixture, TestCase):
    def _update(self, execute_callbacks=True):
        with self.captureOnCommitCallbacks(execute=execute_callbacks):
            return super()._update()

    def test_duplicate_history_survives_consolidation_and_cold_delete(self):
        cfg = PluginConfig.objects.get(key="retained")
        before = set(cfg.owned_tasks)
        PluginConfig.objects.filter(pk=cfg.pk).update(suspended_schedules=[self.other.pk])

        self.assertEqual(self._update().status_code, 200)

        cfg.refresh_from_db()
        self.assertEqual(set(cfg.owned_tasks), before | {self.old.task, self.shared.task})
        self.assertEqual(set(cfg.suspended_schedules), {self.old.pk, self.shared.pk, self.other.pk})
        self.assertFalse(PluginConfig.objects.filter(key="duplicate").exists())
        self.assertTrue(PeriodicTask.objects.get(pk=self.shared.pk).enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=self.old.pk).enabled)
        self.assertTrue(PeriodicTask.objects.get(pk=self.other.pk).enabled)
        self._reset_registry("retained")
        self._delete("retained")
        self.assertFalse(PeriodicTask.objects.filter(pk__in=[self.old.pk, self.shared.pk]).exists())
        self.assertTrue(PeriodicTask.objects.filter(pk=self.other.pk).exists())

    def test_enable_restores_only_current_tasks_from_consolidated_history(self):
        self._set_enabled("retained", False)
        self.assertEqual(self._update().status_code, 200)
        self._reset_registry("retained")

        self._set_enabled("retained", True)

        self.assertTrue(PeriodicTask.objects.get(pk=self.shared.pk).enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=self.old.pk).enabled)
        self.assertEqual(PluginConfig.objects.get(key="retained").suspended_schedules, [])

    def test_duplicate_history_survives_consolidation_and_warm_delete(self):
        self.assertIn(self.old.task, celery_app.tasks)
        self.assertEqual(self._update().status_code, 200)
        self.assertNotIn(self.old.task, celery_app.tasks)
        self.assertIn(self.shared.task, celery_app.tasks)

        self._delete("retained")

        self.assertFalse(PeriodicTask.objects.filter(pk__in=[self.old.pk, self.shared.pk]).exists())
        self.assertTrue(PeriodicTask.objects.filter(pk=self.other.pk).exists())

    def test_disabled_update_and_warm_delete_preserve_a_foreign_callable_in_history(self):
        self._set_enabled("retained", False)
        removed = self._schedule("duplicate.removed", self._default_name("duplicate"))
        source = _PLUGIN_PY[_PLUGIN_PY.index("class Plugin:"):].replace("__KEY__", "duplicate")
        with open(os.path.join(self._plugins_dir, "duplicate", "plugin.py"), "w") as plugin:
            plugin.write(source)
        celery_app.tasks.pop(self.old.task)
        self._install("foreign", custom=self.old.task)
        PluginManager.get().discover_plugins(sync_db=True)
        foreign = celery_app.tasks[self.old.task]
        self.assertTrue(foreign.run.__globals__["__file__"].startswith(
            os.path.join(self._plugins_dir, "foreign") + os.sep
        ))
        self.assertIn(self.old.task, PluginConfig.objects.get(key="duplicate").owned_tasks)
        self.assertIn(removed.task, PluginConfig.objects.get(key="duplicate").owned_tasks)
        PeriodicTask.objects.filter(pk=self.old.pk).update(enabled=True)
        PluginConfig.objects.filter(key="duplicate").update(suspended_schedules=[])
        before = self._payload(self.old)

        self.assertEqual(self._update().status_code, 200)

        self.assertIs(celery_app.tasks[self.old.task], foreign)
        self.assertNotIn(removed.task, celery_app.tasks)
        self.assertTrue(PeriodicTask.objects.get(pk=self.old.pk).enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=removed.pk).enabled)
        cfg = PluginConfig.objects.get(key="retained")
        self.assertIn(removed.pk, cfg.suspended_schedules)
        self.assertNotIn(self.old.pk, cfg.suspended_schedules)
        self._delete("retained")

        self.assertTrue(PeriodicTask.objects.get(pk=self.old.pk).enabled)
        self.assertEqual(self._payload(self.old), before)
        self.assertFalse(PeriodicTask.objects.filter(pk=removed.pk).exists())
        self.assertTrue(PluginConfig.objects.get(key="foreign").enabled)
        self.assertTrue(os.path.isfile(os.path.join(self._plugins_dir, "foreign", "plugin.py")))

    def test_retirement_rechecks_a_task_replaced_after_consolidation(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.assertEqual(self._update(execute_callbacks=False).status_code, 200)
        self.assertEqual(len(callbacks), 2)
        self.assertIn(self.old.task, celery_app.tasks)
        celery_app.tasks.pop(self.old.task)
        self._install("foreign", custom=self.old.task)
        foreign = celery_app.tasks[self.old.task]

        for callback in callbacks:
            callback()

        self.assertIs(celery_app.tasks[self.old.task], foreign)
        PeriodicTask.objects.filter(pk=self.old.pk).update(enabled=True)
        self._delete("retained")
        self.assertTrue(PeriodicTask.objects.get(pk=self.old.pk).enabled)
        self.assertTrue(PluginConfig.objects.get(key="foreign").enabled)

    def test_disabled_install_suspends_enabled_duplicate_schedules_on_update(self):
        self._set_enabled("retained", False)
        PeriodicTask.objects.filter(pk=self.old.pk).update(enabled=True)

        self.assertEqual(self._update().status_code, 200)

        cfg = PluginConfig.objects.get(key="retained")
        self.assertFalse(cfg.enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=self.old.pk).enabled)
        self.assertIn(self.old.pk, cfg.suspended_schedules)
        self.assertTrue(PeriodicTask.objects.get(pk=self.other.pk).enabled)
        self._set_enabled("retained", False)
        self._set_enabled("retained", True)
        self.assertTrue(PeriodicTask.objects.get(pk=self.shared.pk).enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=self.old.pk).enabled)

    def test_file_removal_failure_retains_both_histories_for_retry(self):
        before = list(PluginConfig.objects.order_by("pk").values_list(
            "key", "owned_tasks", "suspended_schedules"
        ))
        with patch("apps.plugins.api_views.shutil.rmtree", side_effect=OSError("injected")):
            self.assertEqual(self._update().status_code, 500)
        self.assertEqual(list(PluginConfig.objects.order_by("pk").values_list(
            "key", "owned_tasks", "suspended_schedules"
        )), before)
        self.assertEqual(self._update().status_code, 200)
        self._reset_registry("retained")
        self._delete("retained")
        self.assertFalse(PeriodicTask.objects.filter(pk=self.old.pk).exists())

    def test_database_failure_after_file_removal_retains_history_for_retry(self):
        real_save = PluginConfig.save
        old_task = celery_app.tasks[self.old.task]

        def fail_transfer(cfg, *args, **kwargs):
            if cfg.key == "retained" and "owned_tasks" in kwargs.get("update_fields", []):
                raise DatabaseError("injected")
            return real_save(cfg, *args, **kwargs)

        with patch.object(PluginConfig, "save", fail_transfer):
            self.assertEqual(self._update().status_code, 500)
        self.assertTrue(PluginConfig.objects.filter(key="duplicate").exists())
        self.assertFalse(os.path.exists(os.path.join(self._plugins_dir, "duplicate")))
        self.assertIs(celery_app.tasks[self.old.task], old_task)
        PluginManager.get().discover_plugins(sync_db=False, force_reload=True)
        self.assertIs(celery_app.tasks[self.old.task], old_task)
        self.assertEqual(self._update().status_code, 200)
        self._reset_registry("retained")
        self._delete("retained")
        self.assertFalse(PeriodicTask.objects.filter(pk=self.old.pk).exists())


class ManagedPluginScheduleCommitTests(ManagedPluginScheduleFixture, TransactionTestCase):
    def _consolidate_with_warm_peer(self, *, disabled_duplicate=False):
        current = PluginManager.get()
        old_task = celery_app.tasks[self.old.task]
        if disabled_duplicate:
            self._set_enabled("duplicate", False)
            self.assertFalse(PluginConfig.objects.get(key="duplicate").enabled)
            self.assertFalse(current._registry["duplicate"].loaded)
            self.assertNotIn("duplicate", current._package_names)
            self.assertEqual(
                current._registry["duplicate"].path,
                os.path.join(self._plugins_dir, "duplicate"),
            )
            self.assertIs(celery_app.tasks[self.old.task], old_task)
        peer = PluginManager()
        peer._registry = dict(current._registry)
        peer._package_names = dict(current._package_names)
        peer._alias_names = dict(current._alias_names)
        peer._last_reload_token = current._last_reload_token
        peer._discovery_completed = True
        PeriodicTask.objects.filter(pk=self.old.pk).update(enabled=True)

        self.assertEqual(self._update().status_code, 200)
        self.assertFalse(PluginConfig.objects.filter(key="duplicate").exists())
        self.assertNotIn(self.old.task, celery_app.tasks)
        self.assertIn(self.old.task, PluginConfig.objects.get(key="retained").owned_tasks)

        # Simulate a peer's unchanged registrations after another process commits.
        celery_app.tasks[self.old.task] = old_task
        PluginManager._instance = peer
        self.assertIs(celery_app.tasks[self.old.task], old_task)

    def _assert_inherited_schedules_suspended(self):
        self.assertNotIn(self.old.task, celery_app.tasks)
        self.assertFalse(PeriodicTask.objects.get(pk=self.old.pk).enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=self.shared.pk).enabled)
        self.assertTrue(PeriodicTask.objects.get(pk=self.other.pk).enabled)

    def _assert_inherited_schedules_deleted(self):
        self.assertNotIn(self.old.task, celery_app.tasks)
        self.assertFalse(PeriodicTask.objects.filter(pk__in=[self.old.pk, self.shared.pk]).exists())
        self.assertTrue(PeriodicTask.objects.get(pk=self.other.pk).enabled)

    def test_warm_peer_disable_suspends_inherited_schedule(self):
        self._consolidate_with_warm_peer()

        self._set_enabled("retained", False)

        self._assert_inherited_schedules_suspended()

    def test_warm_peer_delete_removes_inherited_schedule(self):
        self._consolidate_with_warm_peer()

        self._delete("retained")

        self._assert_inherited_schedules_deleted()

    def test_disabled_peer_disable_suspends_inherited_schedule(self):
        self._consolidate_with_warm_peer(disabled_duplicate=True)

        self._set_enabled("retained", False)

        self._assert_inherited_schedules_suspended()

    def test_disabled_peer_delete_removes_inherited_schedule(self):
        self._consolidate_with_warm_peer(disabled_duplicate=True)

        self._delete("retained")

        self._assert_inherited_schedules_deleted()

    def test_successful_update_retires_duplicate_tasks_before_returning(self):
        self.assertIn(self.old.task, celery_app.tasks)

        self.assertEqual(self._update().status_code, 200)

        self.assertFalse(connection.in_atomic_block)
        self.assertNotIn(self.old.task, celery_app.tasks)
        self.assertIn(self.shared.task, celery_app.tasks)
        self._delete("retained")
        self.assertFalse(PeriodicTask.objects.filter(pk__in=[self.old.pk, self.shared.pk]).exists())


class PluginScheduleOwnershipTests(LifecycleFixture, TestCase):
    def test_cold_delete_does_not_import_enabled_plugin(self):
        self._install("cold_owner")
        owned = self._schedule("cold.owner", self._custom_name("cold_owner"))
        other = self._schedule("other.owner", "unrelated.tick")
        self._reset_registry("cold_owner")
        imports_before = self._import_count("cold_owner")

        self._delete("cold_owner")

        self.assertEqual(self._import_count("cold_owner"), imports_before)
        self.assertFalse(PeriodicTask.objects.filter(pk=owned.pk).exists())
        self.assertTrue(PeriodicTask.objects.filter(pk=other.pk).exists())
        self.assertFalse(PluginConfig.objects.filter(key="cold_owner").exists())
        self.assertNotIn(self._custom_name("cold_owner"), celery_app.tasks)

    def _assert_historical_name_registered_elsewhere(self, action, key, folder, alias=False):
        foreign_key = folder.replace(" ", "_").lower()
        moved_name = self._custom_name(foreign_key)
        removed_name = f"{key}.removed"
        self._task_names.add(removed_name)
        self._install(key, custom=moved_name, class_body=f'''
@shared_task(name="{removed_name}")
def removed_task():
    return "ok"
''')
        moved = self._schedule("moved", moved_name, kwargs='{"value": 1}', queue="default")
        removed = self._schedule("removed", removed_name)
        cfg = PluginConfig.objects.get(key=key)
        self.assertIn(moved_name, cfg.owned_tasks)
        self.assertIn(removed.task, cfg.owned_tasks)

        source = _PLUGIN_PY[_PLUGIN_PY.index("class Plugin:"):].replace("__KEY__", key)
        self._replace_plugin_from_zip(key, source)
        celery_app.tasks.pop(moved_name)
        celery_app.tasks.pop(removed.task)
        if alias:
            self._install_jobs_plugin(folder, f"from {folder}.jobs import scan")
        else:
            self._install(folder, custom=moved_name)
        PluginManager.get().discover_plugins(sync_db=True)
        foreign_path = os.path.join(self._plugins_dir, folder)
        registered = celery_app.tasks[moved_name]
        self.assertTrue(registered.run.__globals__["__file__"].startswith(foreign_path + os.sep))
        if alias:
            self.assertEqual(registered.__module__, f"{folder}.jobs")
        else:
            self.assertEqual(registered.__module__, f"_dispatcharr_plugin_{foreign_key}.plugin")
        self.assertNotIn(removed.task, celery_app.tasks)
        before = self._payload(moved)
        foreign_before = list(PluginConfig.objects.filter(key=foreign_key).values())
        PluginManager._instance = None

        if action == "disable":
            self._set_enabled(key, False)
            cfg.refresh_from_db()
            self.assertFalse(cfg.enabled)
            self.assertEqual(cfg.suspended_schedules, [removed.pk])
            self.assertFalse(PeriodicTask.objects.get(pk=removed.pk).enabled)
        else:
            self._delete(key)
            self.assertFalse(PluginConfig.objects.filter(key=key).exists())
            self.assertFalse(PeriodicTask.objects.filter(pk=removed.pk).exists())
            self.assertFalse(os.path.exists(os.path.join(self._plugins_dir, key)))

        self.assertTrue(PeriodicTask.objects.filter(pk=moved.pk).exists())
        self.assertTrue(PeriodicTask.objects.get(pk=moved.pk).enabled)
        self.assertEqual(self._payload(moved), before)
        self.assertEqual(list(PluginConfig.objects.filter(key=foreign_key).values()), foreign_before)
        self.assertTrue(os.path.isfile(os.path.join(foreign_path, "plugin.py")))

    def test_disable_ignores_historical_name_now_registered_outside_plugin(self):
        self._assert_historical_name_registered_elsewhere("disable", "bad-folder", "bad_folder")

    def test_delete_ignores_historical_name_now_registered_outside_plugin(self):
        self._assert_historical_name_registered_elsewhere("delete", "bad-folder", "bad_folder")

    def test_disable_ignores_historical_name_now_registered_through_foreign_alias(self):
        self._assert_historical_name_registered_elsewhere(
            "disable", "alias_owner", "alias_owner_extra", alias=True,
        )

    def test_delete_ignores_historical_name_now_registered_through_foreign_alias(self):
        self._assert_historical_name_registered_elsewhere(
            "delete", "alias_owner", "alias_owner_extra", alias=True,
        )

    def test_registered_callable_without_source_keeps_historical_cleanup(self):
        key = "unknownsource"
        self._install(key)
        name = self._custom_name(key)
        row = self._schedule("unknown.source", name)
        self.assertIn(name, PluginConfig.objects.get(key=key).owned_tasks)
        celery_app.tasks.pop(name)
        namespace = {"__name__": "unknown_source"}
        exec("def tick(): return 'ok'", namespace)
        celery_app.task(name=name)(namespace["tick"])
        self.assertNotIn("__file__", celery_app.tasks[name].run.__globals__)

        self._set_enabled(key, False)

        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertEqual(PluginConfig.objects.get(key=key).suspended_schedules, [row.pk])
        self._delete(key)
        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())

    def _mixed_case_registered_tasks(self):
        folder = "Mixed Case"
        key = self._install_jobs_plugin(folder, "from .jobs import scan")
        jobs_path = os.path.join(self._plugins_dir, folder, "jobs.py")
        moved_name = f"{key}.moved"
        self._task_names.add(moved_name)
        original = _JOBS_PY.replace("__KEY__", key)
        with open(jobs_path, "w") as jobs:
            jobs.write(original + f'''
@shared_task(name="{moved_name}")
def moved():
    return "ok"
''')
        PluginManager.get().discover_plugins(force_reload=True)
        self.assertIn(moved_name, PluginConfig.objects.get(key=key).owned_tasks)
        with open(jobs_path, "w") as jobs:
            jobs.write(original)
        celery_app.tasks.pop(moved_name)
        self._install("foreign", custom=moved_name)
        own = self._schedule("mixed.owned", self._custom_name(key))
        moved = self._schedule("mixed.moved", moved_name)
        self.assertIn(own.task, celery_app.tasks)
        self.assertTrue(celery_app.tasks[own.task].run.__globals__["__file__"].startswith(
            os.path.join(self._plugins_dir, folder) + os.sep
        ))
        self.assertTrue(celery_app.tasks[moved_name].run.__globals__["__file__"].startswith(
            os.path.join(self._plugins_dir, "foreign") + os.sep
        ))
        return folder, key, own, moved

    def _assert_mixed_case_deleted(self, folder, key, own, moved):
        self.assertFalse(PeriodicTask.objects.filter(pk=own.pk).exists())
        self.assertFalse(PluginConfig.objects.filter(key=key).exists())
        self.assertFalse(os.path.exists(os.path.join(self._plugins_dir, folder)))
        self.assertTrue(PeriodicTask.objects.filter(pk=moved.pk).exists())
        self.assertTrue(PeriodicTask.objects.get(pk=moved.pk).enabled)
        self.assertTrue(PluginConfig.objects.get(key="foreign").enabled)
        self.assertTrue(os.path.isfile(os.path.join(self._plugins_dir, "foreign", "plugin.py")))

    def test_cold_delete_uses_actual_folder_for_warm_registered_tasks(self):
        folder, key, own, moved = self._mixed_case_registered_tasks()
        PluginManager._instance = None

        self._delete(key)

        self._assert_mixed_case_deleted(folder, key, own, moved)

    def test_failed_cleanup_can_retry_with_missing_folder_and_warm_registered_tasks(self):
        folder, key, own, moved = self._mixed_case_registered_tasks()
        config_table = PluginConfig._meta.db_table
        own_task = celery_app.tasks[own.task]
        moved_task = celery_app.tasks[moved.task]
        failed = []

        def fail_config_delete(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith(f'DELETE FROM "{config_table}"'.upper()):
                failed.append((
                    not os.path.exists(os.path.join(self._plugins_dir, folder)),
                    not PeriodicTask.objects.filter(pk=own.pk).exists(),
                    PeriodicTask.objects.filter(pk=moved.pk).exists(),
                ))
                return execute("DELETE FROM history_missing_schedule_table", None, False, context)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(fail_config_delete):
            self._delete(key, status_code=500)

        self.assertEqual(failed, [(True, True, True)])
        self.assertFalse(os.path.exists(os.path.join(self._plugins_dir, folder)))
        self.assertTrue(PeriodicTask.objects.get(pk=own.pk).enabled)
        self.assertTrue(PeriodicTask.objects.get(pk=moved.pk).enabled)
        self.assertIn(own.task, PluginConfig.objects.get(key=key).owned_tasks)
        self.assertIs(celery_app.tasks[own.task], own_task)
        self.assertIs(celery_app.tasks[moved.task], moved_task)
        PluginManager._instance = None

        self._delete(key)

        self._assert_mixed_case_deleted(folder, key, own, moved)

    def test_colliding_package_names_keep_separate_schedule_ownership(self):
        self._install("bad-folder", custom="dash_unique.tick")
        self._install("bad_folder", custom="underscore_unique.tick")
        dash = self._schedule("dash", "dash_unique.tick")
        underscore = self._schedule("underscore", "underscore_unique.tick")
        dash_config = PluginConfig.objects.get(key="bad-folder")
        underscore_config = PluginConfig.objects.get(key="bad_folder")
        self.assertIn(dash.task, dash_config.owned_tasks)
        self.assertNotIn(underscore.task, dash_config.owned_tasks)
        self.assertIn(underscore.task, underscore_config.owned_tasks)
        self.assertNotIn(dash.task, underscore_config.owned_tasks)

        self._set_enabled("bad-folder", False)

        self.assertFalse(PeriodicTask.objects.get(pk=dash.pk).enabled)
        self.assertTrue(PeriodicTask.objects.get(pk=underscore.pk).enabled)
        self._reset_registry("bad-folder")
        self._delete("bad-folder")
        self.assertFalse(PeriodicTask.objects.filter(pk=dash.pk).exists())
        self.assertTrue(PeriodicTask.objects.get(pk=underscore.pk).enabled)
        self.assertTrue(PluginConfig.objects.get(key="bad_folder").enabled)

    def _replace_plugin_from_zip(self, key, source):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr(f"{key}/plugin.py", source)
            with open(os.path.join(self._plugins_dir, key, "plugin.json"), "rb") as f:
                zipped.writestr(f"{key}/plugin.json", f.read())
        archive.seek(0)
        result = _install_plugin_from_zip(
            archive, self._plugins_dir, allow_overwrite_key=key, install_key=key,
        )
        self.assertTrue(result["success"], result)

    def _upgrade_while_disabled(self, cold_registry):
        self._install("vod2mlib", custom="vod2mlib.task_v1")
        old = self._schedule("vod2mlib.v1", "vod2mlib.task_v1")
        self._set_enabled("vod2mlib", False)
        self.assertFalse(PeriodicTask.objects.get(pk=old.pk).enabled)

        new_name = "vod2mlib.renamed_task_v2"
        source = _PLUGIN_PY.replace("__CUSTOM__", new_name).replace("__KEY__", "vod2mlib")
        self._replace_plugin_from_zip("vod2mlib", source)
        self._task_names.add(new_name)
        self.assertIn("vod2mlib.task_v1", celery_app.tasks)
        if cold_registry:
            self._reset_registry("vod2mlib")
        else:
            PluginManager._instance = None

        self._set_enabled("vod2mlib", True)

        self.assertFalse(PeriodicTask.objects.get(pk=old.pk).enabled)
        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertIn("vod2mlib.task_v1", cfg.owned_tasks)
        self._delete("vod2mlib")
        self.assertFalse(PeriodicTask.objects.filter(pk=old.pk).exists())

    def test_upgrade_while_disabled_does_not_restore_removed_task_with_stale_registry(self):
        self._upgrade_while_disabled(cold_registry=False)

    def test_upgrade_while_disabled_does_not_restore_removed_task_after_restart(self):
        self._upgrade_while_disabled(cold_registry=True)

    def test_upgrade_does_not_restore_a_removed_task_imported_through_folder_name(self):
        key = self._install_jobs_plugin(
            "AliasPlugin", "from AliasPlugin.jobs import scan"
        )
        old_name = f"{key}.scheduled_rescan"
        row = self._schedule(f"{key}.auto_rescan", old_name)
        self._set_enabled(key, False)
        self.assertNotIn("AliasPlugin.jobs", sys.modules)
        self.assertIn(old_name, celery_app.tasks)
        jobs_path = os.path.join(self._plugins_dir, "AliasPlugin", "jobs.py")
        with open(jobs_path, "w") as f:
            f.write("def scan():\n    return 'no scheduled task'\n")
        PluginManager._instance = None

        self._set_enabled(key, True)

        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertNotIn(old_name, celery_app.tasks)
        self.assertIn(old_name, PluginConfig.objects.get(key=key).owned_tasks)
        self._delete(key)
        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())

    def test_reload_keeps_a_task_name_replaced_by_an_outside_callable(self):
        self._install("vod2mlib", custom="vod2mlib.task_v1")
        row = self._schedule("vod2mlib.v1", "vod2mlib.task_v1")
        self._set_enabled("vod2mlib", False)
        old_task = celery_app.tasks["vod2mlib.task_v1"]

        def outside_task():
            return "unrelated"

        old_task.run = outside_task
        source = _PLUGIN_PY.replace("__CUSTOM__", "vod2mlib.task_v2").replace("__KEY__", "vod2mlib")
        self._replace_plugin_from_zip("vod2mlib", source)
        self._task_names.add("vod2mlib.task_v2")
        PluginManager._instance = None

        self._set_enabled("vod2mlib", True)

        self.assertIs(celery_app.tasks["vod2mlib.task_v1"], old_task)
        self.assertIs(old_task.run, outside_task)
        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)

    def test_same_size_overwrite_does_not_use_old_plugin_bytecode(self):
        self._install("vod2mlib", custom="vod2mlib.task_v1")
        row = self._schedule("vod2mlib.v1", "vod2mlib.task_v1")
        self._set_enabled("vod2mlib", False)
        plugin_path = os.path.join(self._plugins_dir, "vod2mlib", "plugin.py")
        py_compile.compile(
            plugin_path, cfile=importlib.util.cache_from_source(plugin_path), doraise=True
        )
        old_stat = os.stat(plugin_path)
        self.assertTrue(os.path.isfile(importlib.util.cache_from_source(plugin_path)))
        old_source = _PLUGIN_PY.replace("__CUSTOM__", "vod2mlib.task_v1").replace("__KEY__", "vod2mlib")
        new_source = _PLUGIN_PY.replace("__CUSTOM__", "vod2mlib.task_v2").replace("__KEY__", "vod2mlib")
        self.assertEqual(len(old_source), len(new_source))
        with open(plugin_path, "w") as f:
            f.write(new_source)
        os.utime(plugin_path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        self._task_names.add("vod2mlib.task_v2")
        PluginManager._instance = None

        self._set_enabled("vod2mlib", True)

        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertIn("vod2mlib.task_v2", celery_app.tasks)
        self.assertNotIn("vod2mlib.task_v1", celery_app.tasks)

    def test_cold_restore_reads_changed_submodule_in_a_spaced_plugin_folder(self):
        key = self._install_jobs_plugin(
            "Mixed Case", "from .jobs import scan"
        )
        old_name = f"{key}.scheduled_rescan"
        row = self._schedule(f"{key}.auto_rescan", old_name)
        self._set_enabled(key, False)
        jobs_path = os.path.join(self._plugins_dir, "Mixed Case", "jobs.py")
        py_compile.compile(
            jobs_path, cfile=importlib.util.cache_from_source(jobs_path), doraise=True
        )
        old_stat = os.stat(jobs_path)
        self.assertTrue(os.path.isfile(importlib.util.cache_from_source(jobs_path)))
        old_source = _JOBS_PY.replace("__KEY__", key)
        new_name = f"{key}.scheduled_rescAn"
        new_source = old_source.replace(old_name, new_name)
        self.assertEqual(len(old_source), len(new_source))
        with open(jobs_path, "w") as f:
            f.write(new_source)
        os.utime(jobs_path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        self._task_names.add(new_name)
        self._reset_registry(key)

        self._set_enabled(key, True)

        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertIn(new_name, celery_app.tasks)
        self.assertNotIn(old_name, celery_app.tasks)
        self.assertIn(old_name, PluginConfig.objects.get(key=key).owned_tasks)
        PluginManager._instance = None
        self._delete(key)
        self.assertFalse(os.path.exists(os.path.join(self._plugins_dir, "Mixed Case")))
        self.assertFalse(PluginConfig.objects.filter(key=key).exists())
        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())

    def test_reenabled_task_lazily_imports_current_helper_with_stale_cache(self):
        key = "lazyprobe"
        pm = self._install(key)
        plugin_dir = os.path.join(self._plugins_dir, key)
        plugin_path = os.path.join(plugin_dir, "plugin.py")
        helper_path = os.path.join(plugin_dir, "helper.py")
        with open(plugin_path, "w") as plugin:
            plugin.write("""from celery import shared_task
@shared_task(name='lazyprobe.scheduled_rescan')
def rescan():
    from .helper import VALUE
    return VALUE
class Plugin:
    name = 'lazyprobe'
""")
        with open(helper_path, "w") as helper:
            helper.write("VALUE = 'v1'\n")
        cache_path = importlib.util.cache_from_source(helper_path)
        py_compile.compile(helper_path, cfile=cache_path, doraise=True)
        old_stat = os.stat(helper_path)
        with open(cache_path, "rb") as cache:
            old_cache = cache.read()
        with open(helper_path, "w") as helper:
            helper.write("VALUE = 'v2'\n")
        os.utime(helper_path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        self.assertEqual(os.stat(helper_path).st_size, old_stat.st_size)

        pm.discover_plugins(force_reload=True)
        row = self._schedule(f"{key}.row", self._custom_name(key))
        self._set_enabled(key, False)
        self._set_enabled(key, True)

        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertNotIn("_dispatcharr_plugin_lazyprobe.helper", sys.modules)
        self.assertEqual(celery_app.tasks[self._custom_name(key)].run(), "v2")
        with open(cache_path, "rb") as cache:
            self.assertEqual(cache.read(), old_cache)

    def test_upgrade_keeps_a_still_defined_task_eligible_for_restoration(self):
        self._install("vod2mlib", custom="vod2mlib.task_v1")
        retained = self._schedule("vod2mlib.v1", "vod2mlib.task_v1")
        self._set_enabled("vod2mlib", False)
        source = _PLUGIN_PY.replace("__CUSTOM__", "vod2mlib.task_v1").replace("__KEY__", "vod2mlib")
        source += '\n@shared_task(name="vod2mlib.task_v2")\ndef added():\n    return "ok"\n'
        self._replace_plugin_from_zip("vod2mlib", source)
        self._task_names.add("vod2mlib.task_v2")
        PluginManager._instance = None

        self._set_enabled("vod2mlib", True)

        self.assertTrue(PeriodicTask.objects.get(pk=retained.pk).enabled)

    def test_failed_import_keeps_suspended_row_for_a_later_retry(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        self._set_enabled("vod2mlib", False)
        self._replace_plugin_from_zip("vod2mlib", "raise ImportError('injected plugin import failure')\n")
        PluginManager._instance = None

        self._set_enabled("vod2mlib", True, status_code=500)

        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.suspended_schedules, [row.pk])
        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)

        source = _PLUGIN_PY.replace("__CUSTOM__", self._custom_name("vod2mlib")).replace("__KEY__", "vod2mlib")
        self._replace_plugin_from_zip("vod2mlib", source)
        PluginManager._instance = None
        self._set_enabled("vod2mlib", True)
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)


class PluginScheduleReadonlyCacheTests(LifecycleFixture, TransactionTestCase):
    def test_readonly_plugin_loads_current_source_without_changing_cache(self):
        if os.name != "posix":
            self.skipTest("requires POSIX file permissions")
        if connection.vendor != "postgresql":
            self.skipTest("requires a shared PostgreSQL test database")

        key = "readonlyprobe"
        old_name = f"{key}.task_v1"
        new_name = f"{key}.task_v2"
        self._install(key, custom=old_name)
        row = self._schedule(f"{key}.row", old_name)
        self._set_enabled(key, False)
        plugin_dir = os.path.join(self._plugins_dir, key)
        source_path = os.path.join(plugin_dir, "plugin.py")
        cache_dir = os.path.join(plugin_dir, "__pycache__")
        cache_path = importlib.util.cache_from_source(source_path)
        py_compile.compile(source_path, cfile=cache_path, doraise=True)
        self.assertTrue(os.path.isfile(cache_path))
        original_stat = os.stat(source_path)
        old_source = _PLUGIN_PY.replace("__CUSTOM__", old_name).replace("__KEY__", key)
        new_source = _PLUGIN_PY.replace("__CUSTOM__", new_name).replace("__KEY__", key)
        new_source = new_source.replace('description = "test"', 'description = "live"')
        self.assertEqual(len(old_source), len(new_source))
        with open(source_path, "w") as source:
            source.write(new_source)
        os.utime(source_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        self.assertEqual(os.stat(source_path).st_mtime_ns, original_stat.st_mtime_ns)
        with open(cache_path, "rb") as cache:
            old_cache = cache.read()
        cache_mtime = os.stat(cache_path).st_mtime_ns

        paths = (self._plugins_dir, self._marker, plugin_dir, cache_dir, source_path, cache_path)
        original_modes = {path: stat.S_IMODE(os.stat(path).st_mode) for path in paths}
        try:
            os.chmod(self._plugins_dir, 0o755)
            os.chmod(self._marker, 0o666)
            os.chmod(plugin_dir, 0o555)
            os.chmod(cache_dir, 0o555)
            os.chmod(source_path, 0o444)
            os.chmod(cache_path, 0o444)
            readonly_modes = {
                path: stat.S_IMODE(os.stat(path).st_mode)
                for path in (plugin_dir, cache_dir, source_path, cache_path)
            }
            child = """import django, json, os, sys
django.setup()
from apps.plugins.api_views import PluginEnabledAPIView
from apps.plugins.loader import PluginManager
from apps.plugins.models import PluginConfig
from django_celery_beat.models import PeriodicTask
from dispatcharr.celery import app as celery_app
from rest_framework.test import APIRequestFactory
PluginEnabledAPIView.get_permissions = lambda self: []
response = PluginEnabledAPIView.as_view()(
    APIRequestFactory().post('/', {'enabled': True}, format='json'), key='readonlyprobe'
)
cfg = PluginConfig.objects.get(key='readonlyprobe')
loaded = PluginManager.get().get_plugin('readonlyprobe')
sys.stdout.write('READONLY_RESULT ' + json.dumps({
    'status': response.status_code,
    'uid': os.geteuid(),
    'old_registered': 'readonlyprobe.task_v1' in celery_app.tasks,
    'new_registered': 'readonlyprobe.task_v2' in celery_app.tasks,
    'row_enabled': PeriodicTask.objects.get(name='readonlyprobe.row').enabled,
    'new_recorded': 'readonlyprobe.task_v2' in cfg.owned_tasks,
    'loaded_description': loaded.instance.description if loaded else None,
    'reported_description': response.data.get('plugin', {}).get('description'),
    'plugin_writable': os.access(os.environ['READONLY_PLUGIN_DIR'], os.W_OK),
    'cache_writable': os.access(os.environ['READONLY_CACHE_DIR'], os.W_OK),
}))
"""
            env = dict(
                os.environ,
                DJANGO_SETTINGS_MODULE="dispatcharr.settings_test",
                POSTGRES_DB=connection.settings_dict["NAME"],
                DISPATCHARR_SKIP_PLUGIN_AUTODISCOVERY="1",
                READONLY_PLUGIN_DIR=plugin_dir,
                READONLY_CACHE_DIR=cache_dir,
            )
            identity = {"user": 65534, "group": 65534} if os.geteuid() == 0 else {}
            result = subprocess.run(
                [sys.executable, "-c", child], env=env,
                capture_output=True, text=True, timeout=40, **identity,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            observations = [
                line.removeprefix("READONLY_RESULT ") for line in result.stdout.splitlines()
                if line.startswith("READONLY_RESULT ")
            ]
            self.assertEqual(len(observations), 1, result.stdout + result.stderr)
            observed = json.loads(observations[0])
            self.assertGreater(observed["uid"], 0, observed)
            self.assertEqual(observed["status"], 200, observed)
            self.assertFalse(observed["old_registered"], observed)
            self.assertTrue(observed["new_registered"], observed)
            self.assertFalse(observed["row_enabled"], observed)
            self.assertTrue(observed["new_recorded"], observed)
            self.assertEqual(observed["loaded_description"], "live", observed)
            self.assertEqual(observed["reported_description"], "live", observed)
            self.assertFalse(observed["plugin_writable"], observed)
            self.assertFalse(observed["cache_writable"], observed)
            self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
            with open(cache_path, "rb") as cache:
                self.assertEqual(cache.read(), old_cache)
            self.assertEqual(os.stat(cache_path).st_mtime_ns, cache_mtime)
            self.assertEqual(os.stat(source_path).st_mtime_ns, original_stat.st_mtime_ns)
            self.assertEqual(
                {path: stat.S_IMODE(os.stat(path).st_mode) for path in readonly_modes},
                readonly_modes,
            )
        finally:
            for path, mode in original_modes.items():
                if os.path.exists(path):
                    os.chmod(path, mode)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL row locks")
class PluginScheduleOwnershipConcurrencyTests(LifecycleFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self._errors = []

    def _spawn(self, name, fn):
        def target():
            try:
                fn()
            except BaseException as exc:
                self._errors.append((name, repr(exc)))
            finally:
                connections.close_all()

        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        return thread

    def _join(self, *threads):
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(self._errors, [])

    def _wait_for_database_lock(self, pid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid]
                )
                row = cursor.fetchone()
            if row and row[0] == "Lock":
                return
            time.sleep(0.02)
        self.fail(f"operation backend {pid} never waited for the schedule row lock")

    def _run_while_schedule_is_repointed(self, action):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        writer_ready, writer_release = threading.Event(), threading.Event()
        operation_ready = threading.Event()
        operation_pid = []

        def writer():
            with transaction.atomic():
                locked = PeriodicTask.objects.select_for_update().get(pk=row.pk)
                locked.task = "other.task"
                locked.save(update_fields=["task"])
                writer_ready.set()
                assert writer_release.wait(10)

        def operation():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                operation_pid.append(cursor.fetchone()[0])
            operation_ready.set()
            if action == "disable":
                self._set_enabled("vod2mlib", False)
            else:
                self._delete("vod2mlib")

        writer_thread = self._spawn("schedule-writer", writer)
        operation_thread = None
        try:
            self.assertTrue(writer_ready.wait(10))
            operation_thread = self._spawn(action, operation)
            self.assertTrue(operation_ready.wait(10))
            self._wait_for_database_lock(operation_pid[0])
        finally:
            writer_release.set()
            self._join(*(t for t in (writer_thread, operation_thread) if t is not None))
        self.assertTrue(PeriodicTask.objects.filter(pk=row.pk).exists())
        row.refresh_from_db()
        self.assertEqual(row.task, "other.task")
        self.assertTrue(row.enabled)
        if action == "disable":
            cfg = PluginConfig.objects.get(key="vod2mlib")
            self.assertFalse(cfg.enabled)
            self.assertNotIn(row.pk, cfg.suspended_schedules)
        else:
            self.assertFalse(PluginConfig.objects.filter(key="vod2mlib").exists())

    def test_disable_waits_for_schedule_repoint_and_leaves_unrelated_row_enabled(self):
        self._run_while_schedule_is_repointed("disable")

    def test_delete_waits_for_schedule_repoint_and_keeps_unrelated_row(self):
        self._run_while_schedule_is_repointed("delete")

    def test_delete_does_not_remove_a_new_row_reusing_the_selected_name(self):
        self._install("vod2mlib")
        owned = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        reached, resume = threading.Event(), threading.Event()
        writer_started = threading.Event()
        writer_pid, replacement_pk = [], []
        task_table = PeriodicTask._meta.db_table

        def pause_delete(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith(f'DELETE FROM "{task_table}"'.upper()):
                reached.set()
                assert resume.wait(10)
            return execute(sql, params, many, context)

        def delete():
            with connection.execute_wrapper(pause_delete):
                self._delete("vod2mlib")

        def writer():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                writer_pid.append(cursor.fetchone()[0])
            writer_started.set()
            with transaction.atomic():
                current = PeriodicTask.objects.select_for_update().filter(pk=owned.pk).first()
                if current is not None:
                    current.delete()
                replacement = self._schedule("vod2mlib.auto_rescan", "other.task")
                replacement_pk.append(replacement.pk)

        deletion = self._spawn("delete", delete)
        writer_thread = None
        try:
            self.assertTrue(reached.wait(10))
            writer_thread = self._spawn("replacement-writer", writer)
            self.assertTrue(writer_started.wait(10))
            writer_thread.join(0.3)
            if writer_thread.is_alive():
                self._wait_for_database_lock(writer_pid[0])
        finally:
            resume.set()
            self._join(*(t for t in (deletion, writer_thread) if t is not None))

        self.assertEqual(len(replacement_pk), 1)
        replacement = PeriodicTask.objects.filter(pk=replacement_pk[0]).first()
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.task, "other.task")

    def test_delete_keeps_a_schedule_with_a_new_foreign_reference(self):
        self._install("vod2mlib")
        owned = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        schedule = self._crontab
        writer_ready, writer_release = threading.Event(), threading.Event()
        delete_ready = threading.Event()
        delete_pid, row_pk = [], []

        def writer():
            with transaction.atomic():
                row = PeriodicTask.objects.create(
                    name="other.concurrent", task="other.task", crontab=schedule
                )
                row_pk.append(row.pk)
                writer_ready.set()
                assert writer_release.wait(10)

        def delete():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                delete_pid.append(cursor.fetchone()[0])
            delete_ready.set()
            self._delete("vod2mlib")

        writer_thread = self._spawn("reference-writer", writer)
        delete_thread = None
        try:
            self.assertTrue(writer_ready.wait(10))
            delete_thread = self._spawn("plugin-delete", delete)
            self.assertTrue(delete_ready.wait(10))
            self._wait_for_database_lock(delete_pid[0])
        finally:
            writer_release.set()
            self._join(*(t for t in (writer_thread, delete_thread) if t is not None))

        self.assertFalse(PeriodicTask.objects.filter(pk=owned.pk).exists())
        self.assertTrue(CrontabSchedule.objects.filter(pk=schedule.pk).exists())
        self.assertTrue(PeriodicTask.objects.filter(pk=row_pk[0]).exists())

    def test_metadata_sync_preserves_concurrent_plugin_state_and_settings(self):
        pm = self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        cfg = PluginConfig.objects.get(key="vod2mlib")
        plugin = pm.get_plugin("vod2mlib")
        plugin.name = "Updated Plugin"
        plugin.version = "2.0"
        plugin.description = "Updated description"
        reached, resume = threading.Event(), threading.Event()
        real_save = PluginConfig.save

        def pause_metadata_save(obj, *args, **kwargs):
            if threading.current_thread().name == "metadata-sync":
                reached.set()
                assert resume.wait(10)
            return real_save(obj, *args, **kwargs)

        with patch.object(PluginConfig, "save", pause_metadata_save):
            syncing = self._spawn(
                "metadata-sync", lambda: pm._sync_db_with_registry({"vod2mlib": plugin})
            )
            try:
                self.assertTrue(reached.wait(10))
                PluginConfig.objects.filter(pk=cfg.pk).update(
                    enabled=False,
                    ever_enabled=True,
                    owned_tasks=[self._custom_name("vod2mlib")],
                    suspended_schedules=[row.pk],
                )
                pm.update_settings("vod2mlib", {"scan_mode": "fast"})
            finally:
                resume.set()
                self._join(syncing)

        cfg.refresh_from_db()
        self.assertEqual((cfg.name, cfg.version, cfg.description), (
            "Updated Plugin", "2.0", "Updated description"
        ))
        self.assertFalse(cfg.enabled)
        self.assertTrue(cfg.ever_enabled)
        self.assertEqual(cfg.owned_tasks, [self._custom_name("vod2mlib")])
        self.assertEqual(cfg.suspended_schedules, [row.pk])
        self.assertEqual(cfg.settings, {"scan_mode": "fast"})


class PluginScheduleOwnershipDeleteTests(LifecycleFixture, TransactionTestCase):
    def test_file_removal_failure_keeps_config_and_schedules_for_retry(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        plugin_dir = os.path.join(self._plugins_dir, "vod2mlib")

        with patch("apps.plugins.api_views.shutil.rmtree", side_effect=OSError("injected")):
            self._delete("vod2mlib", status_code=500)

        self.assertTrue(os.path.isdir(plugin_dir))
        self.assertTrue(PluginConfig.objects.filter(key="vod2mlib").exists())
        self.assertTrue(PeriodicTask.objects.filter(pk=row.pk).exists())
        self._delete("vod2mlib")
        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())

    def test_partial_file_removal_failure_keeps_schedule_history_for_retry(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        plugin_dir = os.path.join(self._plugins_dir, "vod2mlib")

        def remove_one_file_then_fail(path):
            self.assertEqual(path, plugin_dir)
            os.remove(os.path.join(path, "plugin.py"))
            raise OSError("injected partial removal")

        with patch("apps.plugins.api_views.shutil.rmtree", side_effect=remove_one_file_then_fail):
            self._delete("vod2mlib", status_code=500)

        self.assertTrue(os.path.isdir(plugin_dir))
        self.assertFalse(os.path.exists(os.path.join(plugin_dir, "plugin.py")))
        self.assertTrue(PeriodicTask.objects.filter(pk=row.pk).exists())
        self.assertIn(
            self._custom_name("vod2mlib"), PluginConfig.objects.get(key="vod2mlib").owned_tasks
        )
        PluginManager._instance = None
        self._delete("vod2mlib")
        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())

    def test_database_failure_after_file_removal_is_reported_and_retryable(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        plugin_dir = os.path.join(self._plugins_dir, "vod2mlib")
        config_table = PluginConfig._meta.db_table
        failed = []

        def fail_config_delete(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith(f'DELETE FROM "{config_table}"'.upper()):
                failed.append(not os.path.exists(plugin_dir))
                raise DatabaseError("injected config deletion failure")
            return execute(sql, params, many, context)

        with connection.execute_wrapper(fail_config_delete):
            self._delete("vod2mlib", status_code=500)

        self.assertEqual(failed, [True])
        self.assertFalse(os.path.exists(plugin_dir))
        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertIn(self._custom_name("vod2mlib"), cfg.owned_tasks)
        self.assertTrue(PeriodicTask.objects.filter(pk=row.pk).exists())

        PluginManager._instance = None
        self._delete("vod2mlib")
        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())
        self.assertFalse(PluginConfig.objects.filter(key="vod2mlib").exists())


class PluginScheduleRegistryTests(LifecycleFixture, TestCase):
    def test_discovery_keeps_registration_when_removed_folder_has_config(self):
        pm = self._install("registry_owner")
        name = self._custom_name("registry_owner")
        task = celery_app.tasks[name]
        shutil.rmtree(os.path.join(self._plugins_dir, "registry_owner"))

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            pm.discover_plugins(sync_db=False, force_reload=True)

        self.assertEqual(callbacks, [])
        self.assertIs(celery_app.tasks[name], task)

    def test_discovery_keeps_registration_when_removed_config_has_folder(self):
        pm = self._install("registry_owner")
        name = self._custom_name("registry_owner")
        task = celery_app.tasks[name]
        PluginConfig.objects.filter(key="registry_owner").delete()

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            pm.discover_plugins(sync_db=False, force_reload=True)

        self.assertEqual(callbacks, [])
        self.assertIs(celery_app.tasks[name], task)

    def test_discovery_keeps_registration_when_configs_cannot_be_read(self):
        pm = self._install("registry_owner")
        name = self._custom_name("registry_owner")
        task = celery_app.tasks[name]
        shutil.rmtree(os.path.join(self._plugins_dir, "registry_owner"))
        PluginConfig.objects.filter(key="registry_owner").delete()

        with (
            self.captureOnCommitCallbacks(execute=True) as callbacks,
            patch.object(PluginConfig.objects, "all", side_effect=DatabaseError("injected")),
        ):
            pm.discover_plugins(sync_db=False, force_reload=True)

        self.assertEqual(callbacks, [])
        self.assertIs(celery_app.tasks[name], task)
        self.assertFalse(pm._discovery_completed)

        with self.captureOnCommitCallbacks(execute=True):
            pm.discover_plugins(sync_db=False, use_cache=True)

        self.assertNotIn(name, celery_app.tasks)

    def test_rolled_back_discovery_can_retry_registration_retirement(self):
        pm = self._install("registry_owner")
        name = self._custom_name("registry_owner")
        task = celery_app.tasks[name]
        shutil.rmtree(os.path.join(self._plugins_dir, "registry_owner"))
        PluginConfig.objects.filter(key="registry_owner").delete()

        with self.assertRaisesMessage(ValueError, "injected rollback"):
            with transaction.atomic():
                pm.discover_plugins(sync_db=False, force_reload=True)
                self.assertIs(celery_app.tasks[name], task)
                raise ValueError("injected rollback")

        self.assertIs(celery_app.tasks[name], task)
        self.assertFalse(pm._discovery_completed)
        with self.captureOnCommitCallbacks(execute=True):
            pm.discover_plugins(sync_db=False, use_cache=True)

        self.assertNotIn(name, celery_app.tasks)

    def test_deferred_retirement_preserves_a_reinstalled_plugin(self):
        pm = self._install("registry_owner")
        name = self._custom_name("registry_owner")
        path = os.path.join(self._plugins_dir, "registry_owner")
        shutil.rmtree(path)
        PluginConfig.objects.filter(key="registry_owner").delete()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            pm.discover_plugins(sync_db=False, force_reload=True)
        self.assertEqual(len(callbacks), 1)
        self._install("registry_owner")
        task = celery_app.tasks[name]

        callbacks[0]()

        self.assertIs(celery_app.tasks[name], task)
        self.assertTrue(PluginConfig.objects.get(key="registry_owner").enabled)
        self.assertTrue(os.path.isfile(os.path.join(path, "plugin.py")))

    def test_failed_retirement_config_read_can_retry(self):
        pm = self._install("registry_owner")
        name = self._custom_name("registry_owner")
        task = celery_app.tasks[name]
        shutil.rmtree(os.path.join(self._plugins_dir, "registry_owner"))
        PluginConfig.objects.filter(key="registry_owner").delete()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            pm.discover_plugins(sync_db=False, force_reload=True)
        self.assertEqual(len(callbacks), 1)

        with patch.object(PluginConfig.objects, "filter", side_effect=DatabaseError("injected")):
            callbacks[0]()

        self.assertIs(celery_app.tasks[name], task)
        self.assertFalse(pm._discovery_completed)
        with self.captureOnCommitCallbacks(execute=True):
            pm.discover_plugins(sync_db=False, use_cache=True)

        self.assertNotIn(name, celery_app.tasks)

    def _prepare_foreign_schedule(self):
        self._install("registry_owner")
        self._install("registry_foreign")
        cfg = PluginConfig.objects.get(key="registry_owner")
        cfg.owned_tasks = sorted(set(cfg.owned_tasks) | {"registry_foreign.scheduled_rescan"})
        cfg.save(update_fields=["owned_tasks"])
        row = self._schedule("registry_foreign.row", "registry_foreign.scheduled_rescan")
        own_row = self._schedule("registry_owner.row", "registry_owner.scheduled_rescan")
        return row, own_row

    def _change_registry_during_scan(self, action):
        foreign_row, own_row = self._prepare_foreign_schedule()
        pm = PluginManager.get()
        foreign_task = celery_app.tasks["registry_foreign.scheduled_rescan"]
        foreign_run = foreign_task.run
        foreign_path = pm._task_source_path(foreign_task)
        self.assertTrue(foreign_path.startswith(os.path.join(self._plugins_dir, "registry_foreign")))
        started, registered = threading.Event(), threading.Event()
        intercepted = []
        errors = []
        task_name = "registry_concurrent.tick"
        self._task_names.add(task_name)
        source_path = os.path.join(self._plugins_dir, "registration.py")
        source = "def tick(): return 'ok'\n"
        with open(source_path, "w") as file:
            file.write(source)
        task_globals = {"__file__": source_path, "__name__": "registry_concurrent"}
        exec(compile(source, source_path, "exec"), task_globals)
        old_unwrap = inspect.unwrap

        def unwrap(run):
            if run is foreign_run and not intercepted:
                intercepted.append(True)
                started.set()
                if not registered.wait(10):
                    raise AssertionError("registration did not reach barrier")
            return old_unwrap(run)

        def register():
            try:
                if not started.wait(10):
                    raise AssertionError("source scan did not reach barrier")
                celery_app.task(name=task_name, lazy=False)(task_globals["tick"])
            except Exception as error:
                errors.append(error)
            finally:
                registered.set()

        thread = threading.Thread(target=register)
        thread.start()
        try:
            with patch.object(inspect, "unwrap", side_effect=unwrap):
                if action == "disable":
                    self._set_enabled("registry_owner", False)
                else:
                    self._delete("registry_owner")
        finally:
            started.set()
            registered.set()
            thread.join(12)
        self.assertFalse(thread.is_alive(), "registration thread retained")
        self.assertFalse(errors, errors)
        self.assertEqual(intercepted, [True])
        self.assertIn(task_name, celery_app.tasks)
        self.assertIs(celery_app.tasks["registry_foreign.scheduled_rescan"], foreign_task)
        self.assertEqual(pm._task_source_path(foreign_task), foreign_path)
        if action == "disable":
            self.assertFalse(PeriodicTask.objects.get(pk=own_row.pk).enabled)
            self.assertTrue(PeriodicTask.objects.get(pk=foreign_row.pk).enabled)
        else:
            self.assertFalse(PeriodicTask.objects.filter(pk=own_row.pk).exists())
            self.assertTrue(PeriodicTask.objects.filter(pk=foreign_row.pk).exists())

    def test_disable_preserves_foreign_row_during_concurrent_registration(self):
        self._change_registry_during_scan("disable")

    def test_delete_preserves_foreign_row_during_concurrent_registration(self):
        self._change_registry_during_scan("delete")

    def test_disable_preserves_current_foreign_task_when_discovery_fails(self):
        row, _ = self._prepare_foreign_schedule()
        pm = PluginManager.get()
        with patch.object(pm, "_task_names_from_path", side_effect=RuntimeError(
            "dictionary changed size during iteration"
        )):
            self._set_enabled("registry_owner", False)
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)

    def test_delete_preserves_current_foreign_task_when_discovery_fails(self):
        row, _ = self._prepare_foreign_schedule()
        pm = PluginManager.get()
        with patch.object(pm, "_task_names_from_path", side_effect=RuntimeError(
            "dictionary changed size during iteration"
        )):
            self._delete("registry_owner")
        self.assertTrue(PeriodicTask.objects.filter(pk=row.pk).exists())
