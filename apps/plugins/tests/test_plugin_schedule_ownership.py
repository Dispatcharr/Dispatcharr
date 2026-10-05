import io
import importlib.util
import os
import sys
import threading
import time
import zipfile
from unittest import skipUnless
from unittest.mock import patch

from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from apps.plugins.api_views import _install_plugin_from_zip
from apps.plugins.loader import PluginManager
from apps.plugins.models import PluginConfig
from apps.plugins.tests.test_plugin_schedule_lifecycle import (
    LifecycleFixture,
    _JOBS_PY,
    _PLUGIN_PY,
    PluginScheduleLifecycleTests,
)
from dispatcharr.celery import app as celery_app


class PluginScheduleOwnershipTests(LifecycleFixture, TestCase):
    def _replace_plugin_from_zip(self, key, source):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr(f"{key}/plugin.py", source)
            with open(os.path.join(self._plugins_dir, key, "plugin.json"), "rb") as f:
                zipped.writestr(f"{key}/plugin.json", f.read())
        archive.seek(0)
        result = _install_plugin_from_zip(archive, self._plugins_dir, allow_overwrite_key=key)
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
        key = PluginScheduleLifecycleTests._install_jobs_plugin(
            self, "AliasPlugin", "from AliasPlugin.jobs import scan"
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

    def test_cold_restore_reads_changed_submodule_in_a_spaced_plugin_folder(self):
        key = PluginScheduleLifecycleTests._install_jobs_plugin(
            self, "Mixed Case", "from .jobs import scan"
        )
        old_name = f"{key}.scheduled_rescan"
        row = self._schedule(f"{key}.auto_rescan", old_name)
        self._set_enabled(key, False)
        jobs_path = os.path.join(self._plugins_dir, "Mixed Case", "jobs.py")
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
        self.assertIn(old_name, PluginConfig.objects.get(key=key).owned_tasks)
        PluginManager._instance = None
        self._delete(key)
        self.assertFalse(os.path.exists(os.path.join(self._plugins_dir, "Mixed Case")))
        self.assertFalse(PluginConfig.objects.filter(key=key).exists())
        self.assertFalse(PeriodicTask.objects.filter(pk=row.pk).exists())

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
