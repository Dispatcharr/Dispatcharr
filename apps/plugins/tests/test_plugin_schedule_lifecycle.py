import json
import os
import shutil
import sys
import tempfile
import threading
import types
from datetime import timedelta
from unittest.mock import patch

from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from django_celery_beat.schedulers import ModelEntry
from rest_framework.test import APIRequestFactory

from apps.plugins.api_views import PluginDeleteAPIView, PluginEnabledAPIView
from apps.plugins.loader import PluginManager
from apps.plugins.models import PluginConfig
from apps.plugins.tasks import PLUGIN_REPO_REFRESH_TASK_NAME
from dispatcharr.celery import app as celery_app

_PLUGIN_PY = """
import os
from celery import shared_task

with open(os.environ["PLUGIN_IMPORT_MARKER"], "a") as marker:
    marker.write("__KEY__\\n")

@shared_task(name="__CUSTOM__")
def custom_named():
    return "ok"

@shared_task
def default_named():
    return "ok"

class Plugin:
    name = "__KEY__"
    version = "1.0"
    description = "test"
    actions = []

    def run(self, action, params, context):
        return {"status": "ok"}
"""


_JOBS_PY = """
from celery import shared_task

@shared_task(name="__KEY__.scheduled_rescan")
def scan():
    return "ok"
"""

_JOBS_PLUGIN_PY = """
__IMPORT__

class Plugin:
    name = "__KEY__"
    version = "1"
    description = "test"
    actions = []

    def run(self, action, params, context):
        return {"status": "ok"}
"""


class LifecycleFixture:
    def setUp(self):
        super().setUp()
        self._plugins_dir = tempfile.mkdtemp(prefix="dispatcharr-plugins-")
        self._marker = os.path.join(self._plugins_dir, "import.marker")
        self._env = patch.dict(
            os.environ,
            {
                "DISPATCHARR_PLUGINS_DIR": self._plugins_dir,
                "PLUGIN_IMPORT_MARKER": self._marker,
            },
        )
        self._env.start()
        PluginManager._instance = None
        # discover_plugins() closes DB connections in a finally block; under
        # TestCase's atomic wrapper that breaks every later query in the test.
        self._close_conns = patch("apps.plugins.loader.close_old_connections")
        self._close_mock = self._close_conns.start()
        self._no_perms = patch.object(
            PluginEnabledAPIView, "get_permissions", return_value=[]
        )
        self._no_perms.start()
        self._no_perms_delete = patch.object(
            PluginDeleteAPIView, "get_permissions", return_value=[]
        )
        self._no_perms_delete.start()
        self._crontab = CrontabSchedule.objects.create(
            minute="0", hour="3", day_of_week="*", day_of_month="*", month_of_year="*"
        )
        self._factory = APIRequestFactory()
        self._task_names = set()

    def tearDown(self):
        for name in self._task_names:
            celery_app.tasks.pop(name, None)
        self._no_perms_delete.stop()
        self._no_perms.stop()
        self._close_conns.stop()
        self._env.stop()
        for name in list(sys.modules):
            if name.startswith("_dispatcharr_plugin_"):
                sys.modules.pop(name, None)
        PluginManager._instance = None
        shutil.rmtree(self._plugins_dir, ignore_errors=True)
        super().tearDown()

    def _custom_name(self, key):
        return f"{key}.scheduled_rescan"

    def _default_name(self, key):
        return f"_dispatcharr_plugin_{key}.plugin.default_named"

    def _install(self, key, enabled=True, custom=None):
        plugin_dir = os.path.join(self._plugins_dir, key)
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(plugin_dir, "plugin.json"), "w") as f:
            json.dump({"name": key, "version": "1.0", "description": "test", "actions": []}, f)
        custom = custom or self._custom_name(key)
        source = _PLUGIN_PY.replace("__CUSTOM__", custom).replace("__KEY__", key)
        with open(os.path.join(plugin_dir, "plugin.py"), "w") as f:
            f.write(source)
        self._task_names |= {custom, self._default_name(key)}
        PluginConfig.objects.update_or_create(
            key=key, defaults={"name": key, "enabled": enabled, "ever_enabled": enabled}
        )
        pm = PluginManager.get()
        pm.plugins_dir = self._plugins_dir
        pm.discover_plugins(sync_db=False, force_reload=True)
        return pm

    def _schedule(self, name, task, enabled=True, **extra):
        return PeriodicTask.objects.create(
            name=name, task=task, crontab=self._crontab, enabled=enabled, **extra
        )

    def _set_enabled(self, key, enabled, status_code=200):
        request = self._factory.post(
            f"/api/plugins/plugins/{key}/enabled/", {"enabled": enabled}, format="json"
        )
        response = PluginEnabledAPIView.as_view()(request, key=key)
        self.assertEqual(response.status_code, status_code)

    def _delete(self, key, status_code=200):
        request = self._factory.delete(f"/api/plugins/plugins/{key}/delete/")
        response = PluginDeleteAPIView.as_view()(request, key=key)
        self.assertEqual(response.status_code, status_code)

    def _reset_registry(self, key):
        """Drop the plugin from the PluginManager, Celery registry and sys.modules of this process."""
        PluginManager._instance = None
        for name in self._task_names:
            celery_app.tasks.pop(name, None)
        for name in list(sys.modules):
            if name.startswith(f"_dispatcharr_plugin_{key}"):
                sys.modules.pop(name, None)

    def _import_count(self, key):
        with open(self._marker) as f:
            return f.read().split().count(key)

    def _payload(self, row):
        row.refresh_from_db()
        return (row.name, row.task, row.args, row.kwargs, row.crontab_id, row.queue)


class PluginScheduleLifecycleTests(LifecycleFixture, TestCase):
    def test_disable_suspends_only_owned_enabled_rows_and_enable_restores_them(self):
        self._install("vod2mlib")
        self._install("vod2mlib_extra")
        owned_custom = self._schedule(
            "vod2mlib.auto_rescan", self._custom_name("vod2mlib"), kwargs='{"action": "rescan"}'
        )
        owned_default = self._schedule("vod2mlib.other", self._default_name("vod2mlib"))
        owned_off = self._schedule(
            "vod2mlib.paused", self._custom_name("vod2mlib"), enabled=False
        )
        lookalike = self._schedule(
            "vod2mlib_extra.auto_rescan", self._custom_name("vod2mlib_extra")
        )
        repo_refresh = self._schedule(
            PLUGIN_REPO_REFRESH_TASK_NAME, "apps.plugins.tasks.refresh_plugin_repos"
        )
        before = {row.pk: self._payload(row) for row in PeriodicTask.objects.all()}

        self._set_enabled("vod2mlib", False)

        enabled_after_disable = dict(PeriodicTask.objects.values_list("pk", "enabled"))
        self.assertFalse(enabled_after_disable[owned_custom.pk])
        self.assertFalse(enabled_after_disable[owned_default.pk])
        self.assertFalse(enabled_after_disable[owned_off.pk])
        self.assertTrue(enabled_after_disable[lookalike.pk])
        self.assertTrue(enabled_after_disable[repo_refresh.pk])

        self._set_enabled("vod2mlib", True)

        enabled_after_enable = dict(PeriodicTask.objects.values_list("pk", "enabled"))
        self.assertTrue(enabled_after_enable[owned_custom.pk])
        self.assertTrue(enabled_after_enable[owned_default.pk])
        self.assertFalse(enabled_after_enable[owned_off.pk])
        self.assertTrue(enabled_after_enable[lookalike.pk])
        self.assertTrue(enabled_after_enable[repo_refresh.pk])
        self.assertEqual({row.pk: self._payload(row) for row in PeriodicTask.objects.all()}, before)

    def test_enable_tolerates_rows_deleted_while_disabled(self):
        self._install("vod2mlib")
        gone = self._schedule("vod2mlib.gone", self._custom_name("vod2mlib"))
        kept = self._schedule("vod2mlib.kept", self._default_name("vod2mlib"))
        self._set_enabled("vod2mlib", False)
        self.assertFalse(PeriodicTask.objects.get(pk=kept.pk).enabled)
        gone.delete()

        self._set_enabled("vod2mlib", True)

        self.assertTrue(PeriodicTask.objects.get(pk=kept.pk).enabled)

    def test_delete_removes_custom_and_default_named_rows_of_an_enabled_plugin(self):
        self._install("vod2mlib")
        self._install("vod2mlib_extra")
        self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        self._schedule("vod2mlib.other", self._default_name("vod2mlib"))
        lookalike = self._schedule(
            "vod2mlib_extra.auto_rescan", self._custom_name("vod2mlib_extra")
        )
        repo_refresh = self._schedule(
            PLUGIN_REPO_REFRESH_TASK_NAME, "apps.plugins.tasks.refresh_plugin_repos"
        )

        self._delete("vod2mlib")

        remaining = set(PeriodicTask.objects.values_list("name", flat=True))
        self.assertNotIn("vod2mlib.auto_rescan", remaining)
        self.assertNotIn("vod2mlib.other", remaining)
        self.assertLessEqual({lookalike.name, repo_refresh.name}, remaining)

    def test_delete_after_disable_after_registry_reset(self):
        self._install("vod2mlib")
        self._install("vod2mlib_extra")
        self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        self._schedule("vod2mlib.other", self._default_name("vod2mlib"))
        lookalike = self._schedule(
            "vod2mlib_extra.auto_rescan", self._custom_name("vod2mlib_extra")
        )
        self._set_enabled("vod2mlib", False)
        self._reset_registry("vod2mlib")
        imports_before = self._import_count("vod2mlib")
        self.assertNotIn(self._custom_name("vod2mlib"), celery_app.tasks)

        self._delete("vod2mlib")

        self.assertEqual(self._import_count("vod2mlib"), imports_before)
        self.assertNotIn(self._custom_name("vod2mlib"), celery_app.tasks)
        remaining = set(PeriodicTask.objects.values_list("name", flat=True))
        self.assertNotIn("vod2mlib.auto_rescan", remaining)
        self.assertNotIn("vod2mlib.other", remaining)
        self.assertIn(lookalike.name, remaining)
        self.assertFalse(PluginConfig.objects.filter(key="vod2mlib").exists())

    def test_disable_after_registry_reset(self):
        self._install("vod2mlib")
        owned = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        unrelated = self._schedule("other.auto_rescan", "other.task")
        self._reset_registry("vod2mlib")
        imports_before = self._import_count("vod2mlib")

        self._set_enabled("vod2mlib", False)

        self.assertEqual(self._import_count("vod2mlib"), imports_before)
        self.assertFalse(PeriodicTask.objects.get(pk=owned.pk).enabled)
        self.assertTrue(PeriodicTask.objects.get(pk=unrelated.pk).enabled)

    def test_enable_after_registry_reset_restores_suspended_rows(self):
        self._install("vod2mlib")
        suspended = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        paused = self._schedule("vod2mlib.paused", self._default_name("vod2mlib"), enabled=False)
        self._set_enabled("vod2mlib", False)
        self._reset_registry("vod2mlib")

        self._set_enabled("vod2mlib", True)

        self.assertTrue(PeriodicTask.objects.get(pk=suspended.pk).enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=paused.pk).enabled)

    def test_later_load_with_fewer_registered_tasks_keeps_recorded_names(self):
        self._install("vod2mlib")
        self._reset_registry("vod2mlib")
        custom_only = {self._custom_name("vod2mlib")}
        with patch.object(PluginManager, "_registered_task_names", return_value=custom_only):
            PluginManager.get().plugins_dir = self._plugins_dir
            PluginManager.get().discover_plugins(sync_db=False, force_reload=True)
        custom = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        default = self._schedule("vod2mlib.other", self._default_name("vod2mlib"))
        self._reset_registry("vod2mlib")

        self._set_enabled("vod2mlib", False)

        self.assertFalse(PeriodicTask.objects.get(pk=custom.pk).enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=default.pk).enabled)

    def _fail_save(self, field):
        real_save = PluginConfig.save

        def save(instance, *args, **kwargs):
            if field in (kwargs.get("update_fields") or ()):
                raise RuntimeError("injected")
            return real_save(instance, *args, **kwargs)

        return patch.object(PluginConfig, "save", save)

    def _fail_update_changed(self):
        return patch(
            "django_celery_beat.models.PeriodicTasks.update_changed",
            side_effect=RuntimeError("injected"),
        )

    def _fail_suspend(self):
        return patch.object(PluginManager, "suspend_schedules", side_effect=RuntimeError("injected"))

    def _assert_failed_disable_is_retryable(self, injection):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))

        with injection:
            self._set_enabled("vod2mlib", False, status_code=500)

        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.suspended_schedules, [])
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)
        self._set_enabled("vod2mlib", False)
        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertEqual(PluginConfig.objects.get(key="vod2mlib").suspended_schedules, [row.pk])

    def test_disable_fails_before_rows_change_and_is_retryable(self):
        self._assert_failed_disable_is_retryable(self._fail_suspend())

    def test_disable_fails_after_rows_change_and_rolls_them_back(self):
        self._assert_failed_disable_is_retryable(self._fail_update_changed())

    def test_disable_fails_saving_the_suspended_record_and_rolls_rows_back(self):
        self._assert_failed_disable_is_retryable(self._fail_save("suspended_schedules"))

    def test_disable_fails_saving_the_plugin_state_and_rolls_rows_back(self):
        self._assert_failed_disable_is_retryable(self._fail_save("enabled"))

    def _assert_failed_enable_is_retryable(self, injection):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        self._set_enabled("vod2mlib", False)

        with injection:
            self._set_enabled("vod2mlib", True, status_code=500)

        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.suspended_schedules, [row.pk])
        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
        self._set_enabled("vod2mlib", True)
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertEqual(PluginConfig.objects.get(key="vod2mlib").suspended_schedules, [])

    def test_enable_fails_restoring_rows_and_keeps_the_suspended_record(self):
        self._assert_failed_enable_is_retryable(self._fail_update_changed())

    def test_enable_fails_clearing_the_suspended_record_and_rolls_rows_back(self):
        self._assert_failed_enable_is_retryable(self._fail_save("suspended_schedules"))

    def test_enable_fails_saving_the_plugin_state_and_keeps_the_suspended_record(self):
        self._assert_failed_enable_is_retryable(self._fail_save("enabled"))

    def test_enable_does_not_restore_a_row_edited_to_an_unrelated_task(self):
        self._install("vod2mlib")
        kept = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        edited = self._schedule("vod2mlib.other", self._default_name("vod2mlib"))
        self._set_enabled("vod2mlib", False)
        PeriodicTask.objects.filter(pk=edited.pk).update(task="other.task")

        self._set_enabled("vod2mlib", True)

        self.assertTrue(PeriodicTask.objects.get(pk=kept.pk).enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=edited.pk).enabled)
        self.assertEqual(PluginConfig.objects.get(key="vod2mlib").suspended_schedules, [])

    def test_delete_fails_cleaning_schedules_keeps_plugin_and_is_retryable(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))

        with patch("core.scheduling.delete_periodic_task", side_effect=RuntimeError("injected")):
            self._delete("vod2mlib", status_code=500)

        self.assertTrue(os.path.isdir(os.path.join(self._plugins_dir, "vod2mlib")))
        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertIn(self._custom_name("vod2mlib"), cfg.owned_tasks)
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)
        self._delete("vod2mlib")
        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())
        self.assertFalse(PluginConfig.objects.filter(key="vod2mlib").exists())

    def test_upgrade_keeps_names_of_removed_tasks_for_delete_after_registry_reset(self):
        self._install("vod2mlib", custom="vod2mlib.task_v1")
        old = self._schedule("vod2mlib.v1", "vod2mlib.task_v1")
        self._install("vod2mlib", custom="vod2mlib.renamed_task_v2")
        new = self._schedule("vod2mlib.v2", "vod2mlib.renamed_task_v2")
        self._reset_registry("vod2mlib")

        self._delete("vod2mlib")

        self.assertFalse(PeriodicTask.objects.filter(pk__in=[old.pk, new.pk]).exists())

    def test_reenabled_rows_do_not_fire_a_catch_up_run(self):
        self._install("vod2mlib")
        now = timezone.now()
        crontab = CrontabSchedule.objects.create(
            minute="0",
            hour=str((now - timedelta(hours=2)).hour),
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone="UTC",
        )
        row = PeriodicTask.objects.create(
            name="vod2mlib.auto_rescan",
            task=self._custom_name("vod2mlib"),
            crontab=crontab,
            last_run_at=now - timedelta(hours=26),
        )
        self.assertTrue(ModelEntry(PeriodicTask.objects.get(pk=row.pk), app=celery_app).is_due().is_due)

        self._set_enabled("vod2mlib", False)
        # The schedule may stay disabled past its next run time.
        PeriodicTask.objects.filter(pk=row.pk).update(date_changed=now - timedelta(hours=26))
        self._set_enabled("vod2mlib", True)

        row.refresh_from_db()
        self.assertTrue(row.enabled)
        self.assertFalse(ModelEntry(row, app=celery_app).is_due().is_due)

    def _install_jobs_plugin(self, folder, import_line):
        """A plugin in `folder` whose task lives in jobs.py, imported by `import_line`."""
        key = folder.replace(" ", "_").lower()
        plugin_dir = os.path.join(self._plugins_dir, folder)
        os.makedirs(plugin_dir)
        with open(os.path.join(plugin_dir, "jobs.py"), "w") as f:
            f.write(_JOBS_PY.replace("__KEY__", key))
        with open(os.path.join(plugin_dir, "plugin.py"), "w") as f:
            f.write(_JOBS_PLUGIN_PY.replace("__IMPORT__", import_line).replace("__KEY__", key))
        self._task_names.add(f"{key}.scheduled_rescan")
        self.addCleanup(
            lambda: [
                sys.modules.pop(name)
                for name in list(sys.modules)
                if name == folder or name.startswith(f"{folder}.")
            ]
        )
        PluginConfig.objects.create(key=key, name=key, enabled=True, ever_enabled=True)
        pm = PluginManager.get()
        pm.plugins_dir = self._plugins_dir
        pm.discover_plugins(sync_db=False, force_reload=True)
        return key

    def _register_foreign_task(self, name, module):
        def foreign():
            return "ok"

        foreign.__module__ = module
        celery_app.task(name=name)(foreign)
        self._task_names.add(name)

    def _assert_follows_disable_and_delete(self, key):
        row = self._schedule(f"{key}.auto_rescan", f"{key}.scheduled_rescan")
        self.assertEqual(PluginConfig.objects.get(key=key).owned_tasks, [f"{key}.scheduled_rescan"])

        self._set_enabled(key, False)
        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
        self._set_enabled(key, True)
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)
        self._reset_registry(key)
        self._delete(key)

        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())

    def test_task_imported_through_the_folder_name_follows_disable_enable_and_delete(self):
        key = self._install_jobs_plugin("aliasplug", "from aliasplug.jobs import scan")
        self._assert_follows_disable_and_delete(key)

    def test_task_imported_relatively_follows_disable_enable_and_delete(self):
        key = self._install_jobs_plugin("relplug", "from .jobs import scan")
        self.assertEqual(celery_app.tasks[f"{key}.scheduled_rescan"].__module__, "_dispatcharr_plugin_relplug.jobs")
        self._assert_follows_disable_and_delete(key)

    def test_folder_name_that_differs_from_the_key_is_recognized(self):
        key = self._install_jobs_plugin("MixedCase", "from MixedCase.jobs import scan")
        self.assertEqual(key, "mixedcase")
        self.assertEqual(celery_app.tasks["mixedcase.scheduled_rescan"].__module__, "MixedCase.jobs")
        self._assert_follows_disable_and_delete(key)

    def test_tasks_of_similarly_named_modules_are_not_owned(self):
        key = self._install_jobs_plugin("aliasplug", "from aliasplug.jobs import scan")
        rows = []
        for module in ("aliasplug_extra.jobs", "aliasplugin.jobs", "aliasplug2"):
            name = f"{module}.foreign"
            self._register_foreign_task(name, module)
            rows.append(self._schedule(f"{module}.schedule", name))
        own = self._schedule("aliasplug.auto_rescan", f"{key}.scheduled_rescan")

        self.assertEqual(PluginConfig.objects.get(key=key).owned_tasks, [f"{key}.scheduled_rescan"])
        self._set_enabled(key, False)
        self.assertTrue(all(PeriodicTask.objects.get(pk=row.pk).enabled for row in rows))
        self._delete(key)

        self.assertTrue(all(PeriodicTask.objects.filter(pk=row.pk).exists() for row in rows))
        self.assertFalse(PeriodicTask.objects.filter(pk=own.pk).exists())

    def test_reserved_and_invalid_folder_names_match_nothing(self):
        for folder in ("json", "bad-folder"):
            with self.subTest(folder=folder):
                self._install(folder)
                self._register_foreign_task(f"{folder}.foreign", f"{folder}.jobs")
                foreign = self._schedule(f"{folder}.foreign_schedule", f"{folder}.foreign")
                own = self._schedule(f"{folder}.auto_rescan", self._custom_name(folder))

                self.assertNotIn(f"{folder}.foreign", PluginConfig.objects.get(key=folder).owned_tasks)
                self._delete(folder)

                self.assertTrue(PeriodicTask.objects.filter(pk=foreign.pk).exists())
                self.assertFalse(PeriodicTask.objects.filter(pk=own.pk).exists())

    def test_folder_name_matching_an_unrelated_module_matches_none_of_its_tasks(self):
        unrelated = types.ModuleType("collidemod")
        unrelated.__path__ = ["/nonexistent"]
        sys.modules["collidemod"] = unrelated
        self.addCleanup(sys.modules.pop, "collidemod", None)

        self._register_foreign_task("collidemod.unrelated", "collidemod.jobs")
        self._install("collidemod")
        other = self._schedule("collidemod.other", "collidemod.unrelated")
        owned = self._schedule("collidemod.auto_rescan", self._custom_name("collidemod"))

        self.assertNotIn(
            "collidemod.unrelated", PluginConfig.objects.get(key="collidemod").owned_tasks
        )
        self._delete("collidemod")

        self.assertTrue(PeriodicTask.objects.filter(pk=other.pk).exists())
        self.assertFalse(PeriodicTask.objects.filter(pk=owned.pk).exists())

    def test_delete_leaves_rows_of_a_plugin_that_was_never_enabled(self):
        self._install("neverenabled", enabled=False)
        row = self._schedule("neverenabled.auto_rescan", self._custom_name("neverenabled"))

        self._delete("neverenabled")

        self.assertTrue(PeriodicTask.objects.filter(pk=row.pk).exists())
        self.assertFalse(os.path.isdir(os.path.join(self._plugins_dir, "neverenabled")))

    def test_reinstall_after_delete_recreates_a_single_schedule(self):
        self._install("vod2mlib")
        self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        self._delete("vod2mlib")
        self.assertFalse(PeriodicTask.objects.filter(name="vod2mlib.auto_rescan").exists())

        self._install("vod2mlib")
        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute="0", hour="3", day_of_week="*", day_of_month="*", month_of_year="*"
        )
        _, created = PeriodicTask.objects.update_or_create(
            name="vod2mlib.auto_rescan",
            defaults={"task": self._custom_name("vod2mlib"), "crontab": crontab},
        )

        self.assertTrue(created)
        self.assertEqual(PeriodicTask.objects.filter(name="vod2mlib.auto_rescan").count(), 1)
        self._set_enabled("vod2mlib", False)
        self._set_enabled("vod2mlib", True)
        self.assertTrue(PeriodicTask.objects.get(name="vod2mlib.auto_rescan").enabled)


@skipUnlessDBFeature("has_select_for_update")
class PluginScheduleConcurrencyTests(LifecycleFixture, TransactionTestCase):
    def _spawn(self, name, fn):
        def target():
            try:
                fn()
            except BaseException as e:
                self._errors.append((name, repr(e)))
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

    def _pausing(self, attr, thread_name, reached, resume, static=False):
        real = getattr(PluginManager, attr)

        def wrapper(*args, **kwargs):
            if threading.current_thread().name == thread_name and not reached.is_set():
                reached.set()
                assert resume.wait(10)
            return real(*args, **kwargs)

        return patch.object(PluginManager, attr, staticmethod(wrapper) if static else wrapper)

    def _pausing_before_lock(self, thread_name, reached, resume):
        manager = PluginConfig.objects
        real = manager.select_for_update

        def select_for_update(*args, **kwargs):
            if threading.current_thread().name == thread_name and not reached.is_set():
                reached.set()
                assert resume.wait(10)
            return real(*args, **kwargs)

        return patch.object(manager, "select_for_update", select_for_update)

    def setUp(self):
        super().setUp()
        self._errors = []

    def test_stale_disable_after_a_concurrent_enable_still_suspends_schedules(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        self._set_enabled("vod2mlib", False)
        reached, resume = threading.Event(), threading.Event()

        with self._pausing_before_lock("disable", reached, resume):
            disable = self._spawn("disable", lambda: self._set_enabled("vod2mlib", False))
            self.assertTrue(reached.wait(10))
            self._set_enabled("vod2mlib", True)
            resume.set()
            self._join(disable)

        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertFalse(cfg.enabled)
        self.assertFalse(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertEqual(cfg.suspended_schedules, [row.pk])

    def test_stale_enable_after_a_concurrent_disable_restores_schedules(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        reached, resume = threading.Event(), threading.Event()

        with self._pausing_before_lock("enable", reached, resume):
            enable = self._spawn("enable", lambda: self._set_enabled("vod2mlib", True))
            self.assertTrue(reached.wait(10))
            self._set_enabled("vod2mlib", False)
            resume.set()
            self._join(enable)

        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertTrue(cfg.enabled)
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertEqual(cfg.suspended_schedules, [])

    def test_enable_waits_for_a_disable_holding_the_row_lock(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        reached, resume = threading.Event(), threading.Event()

        with self._pausing("suspend_schedules", "disable", reached, resume):
            disable = self._spawn("disable", lambda: self._set_enabled("vod2mlib", False))
            self.assertTrue(reached.wait(10))
            enable = self._spawn("enable", lambda: self._set_enabled("vod2mlib", True))
            enable.join(1)
            self.assertTrue(enable.is_alive())
            resume.set()
            self._join(disable, enable)

        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertTrue(cfg.enabled)
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertEqual(cfg.suspended_schedules, [])

    def test_concurrent_recorders_with_different_registries_keep_both_names(self):
        self._install("vod2mlib")
        pm = PluginManager.get()
        cfg = PluginConfig.objects.get(key="vod2mlib")
        registries = {"first": {"vod2mlib.only_first"}, "second": {"vod2mlib.only_second"}}
        reached, resume = threading.Event(), threading.Event()

        def registered(manager, key):
            if threading.current_thread().name == "first" and not reached.is_set():
                reached.set()
                assert resume.wait(10)
            return registries[threading.current_thread().name]

        with patch.object(PluginManager, "_registered_task_names", registered):
            first = self._spawn("first", lambda: pm._record_owned_tasks("vod2mlib", cfg))
            self.assertTrue(reached.wait(10))
            second = self._spawn("second", lambda: pm._record_owned_tasks("vod2mlib", cfg))
            second.join(10)
            resume.set()
            self._join(first, second)

        recorded = set(PluginConfig.objects.get(key="vod2mlib").owned_tasks)
        self.assertLessEqual({"vod2mlib.only_first", "vod2mlib.only_second"}, recorded)
        self.assertIn(self._custom_name("vod2mlib"), recorded)

    def test_recorder_waits_for_the_row_lock_and_merges_with_the_locked_value(self):
        self._install("vod2mlib")
        pm = PluginManager.get()
        cfg = PluginConfig.objects.get(key="vod2mlib")

        with patch.object(
            PluginManager, "_registered_task_names", lambda manager, key: {"vod2mlib.recorded"}
        ):
            with transaction.atomic():
                locked = PluginConfig.objects.select_for_update().get(key="vod2mlib")
                recorder = self._spawn("recorder", lambda: pm._record_owned_tasks("vod2mlib", cfg))
                recorder.join(1)
                self.assertTrue(recorder.is_alive())
                PluginConfig.objects.filter(pk=locked.pk).update(
                    owned_tasks=sorted(set(locked.owned_tasks) | {"vod2mlib.written_under_lock"})
                )
            self._join(recorder)

        recorded = set(PluginConfig.objects.get(key="vod2mlib").owned_tasks)
        self.assertLessEqual({"vod2mlib.recorded", "vod2mlib.written_under_lock"}, recorded)

    def _record_stop_calls(self, events, pause=None):
        real = PluginManager.stop_plugin

        def stop_plugin(manager, key, reason=None, **kwargs):
            events.append(("stop", reason))
            if pause is not None:
                reached, resume = pause
                reached.set()
                assert resume.wait(10)
            return real(manager, key, reason, **kwargs)

        return patch.object(PluginManager, "stop_plugin", stop_plugin)

    def test_enable_cannot_complete_between_a_disable_and_its_stop_callback(self):
        self._install("vod2mlib")
        row = self._schedule("vod2mlib.auto_rescan", self._custom_name("vod2mlib"))
        events = []
        reached, resume = threading.Event(), threading.Event()

        def enable():
            self._set_enabled("vod2mlib", True)
            events.append(("enable done", None))

        with self._record_stop_calls(events, pause=(reached, resume)):
            disable = self._spawn("disable", lambda: self._set_enabled("vod2mlib", False))
            self.assertTrue(reached.wait(10))
            enabling = self._spawn("enable", enable)
            enabling.join(1)
            self.assertTrue(enabling.is_alive())
            resume.set()
            self._join(disable, enabling)

        self.assertEqual(events, [("stop", "disable"), ("enable done", None)])
        cfg = PluginConfig.objects.get(key="vod2mlib")
        self.assertTrue(cfg.enabled)
        self.assertTrue(PeriodicTask.objects.get(pk=row.pk).enabled)
        self.assertEqual(cfg.suspended_schedules, [])

    def test_plain_disable_calls_stop_once(self):
        self._install("vod2mlib")
        events = []

        with self._record_stop_calls(events):
            self._set_enabled("vod2mlib", False)

        self.assertEqual(events, [("stop", "disable")])
        self.assertFalse(PluginConfig.objects.get(key="vod2mlib").enabled)

    def test_disable_stops_the_plugin_without_closing_the_transaction_connection(self):
        self._install("vod2mlib")
        real = PluginManager.stop_plugin
        seen = []

        def stop_plugin(manager, key, reason=None, **kwargs):
            closes = self._close_mock.call_count
            result = real(manager, key, reason, **kwargs)
            seen.append((connections["default"].in_atomic_block, self._close_mock.call_count - closes))
            return result

        with patch.object(PluginManager, "stop_plugin", stop_plugin):
            self._set_enabled("vod2mlib", False)

        self.assertEqual(seen, [(True, 0)])
