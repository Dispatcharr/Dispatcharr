import os
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from dispatcharr.safe_mode import (
    automatic_refreshes_allowed, plugins_allowed, require_plugins_allowed,
    safe_mode_enabled, safe_mode_status, skip_periodic_refresh, skip_queued_periodic_refresh,
    unloaded_plugin_status,
)


class SafeModeTests(TestCase):
    def test_entrypoint_propagates_and_clears_safe_mode(self):
        entrypoint = (Path(__file__).resolve().parents[1] / "docker/entrypoint.sh").read_text()
        self.assertIn("export DISPATCHARR_SAFE_MODE=${DISPATCHARR_SAFE_MODE:-false}", entrypoint)
        variables = entrypoint.split("variables=(", 1)[1].split(")", 1)[0]
        self.assertIn("DISPATCHARR_SAFE_MODE", variables.split())

    def test_environment_values(self):
        for value in ("1", "true", "YES", " on "):
            with self.subTest(value=value), patch.dict(os.environ, {"DISPATCHARR_SAFE_MODE": value}):
                self.assertTrue(safe_mode_enabled())
        for value in ("", "0", "false", "no"):
            with self.subTest(value=value), patch.dict(os.environ, {"DISPATCHARR_SAFE_MODE": value}):
                self.assertFalse(safe_mode_enabled())

    def test_scheduler_filters_only_source_refreshes(self):
        from dispatcharr.safe_mode_scheduler import SafeModeScheduler

        entries = {
            "m3u": SimpleNamespace(task="apps.m3u.tasks.refresh_single_m3u_account"),
            "epg": SimpleNamespace(task="apps.epg.tasks.refresh_epg_data"),
            "scan": SimpleNamespace(task="core.tasks.scan_and_process_files"),
            "recording": SimpleNamespace(task="apps.channels.tasks.run_recording"),
        }
        with patch("django_celery_beat.schedulers.DatabaseScheduler.all_as_schedule", return_value=entries):
            scheduler = object.__new__(SafeModeScheduler)
            self.assertEqual(set(scheduler.all_as_schedule()), {"scan", "recording"})
        self.assertEqual(len(entries), 4)

    def test_previously_queued_periodic_refresh(self):
        with patch.dict(os.environ, {"DISPATCHARR_SAFE_MODE": "true"}):
            with patch("celery.current_task", SimpleNamespace(request=SimpleNamespace(periodic_task_name="epg"))):
                self.assertTrue(skip_queued_periodic_refresh())
            with patch("celery.current_task", SimpleNamespace(request=SimpleNamespace(headers={"periodic_task_name": "m3u"}))):
                self.assertTrue(skip_queued_periodic_refresh())
            with patch("celery.current_task", SimpleNamespace(request=SimpleNamespace(headers=None))):
                self.assertFalse(skip_queued_periodic_refresh())

    def test_policies_and_refresh_decorator(self):
        refresh = skip_periodic_refresh("skipped")(lambda: "refreshed")
        with patch.dict(os.environ, {"DISPATCHARR_SAFE_MODE": "true"}):
            self.assertFalse(plugins_allowed())
            self.assertFalse(automatic_refreshes_allowed())
            with self.assertRaises(RuntimeError):
                require_plugins_allowed()
            with patch("dispatcharr.safe_mode.skip_queued_periodic_refresh", return_value=True):
                self.assertEqual(refresh(), "skipped")
            with patch("dispatcharr.safe_mode.skip_queued_periodic_refresh", return_value=False):
                self.assertEqual(refresh(), "refreshed")
        with patch.dict(os.environ, {"DISPATCHARR_SAFE_MODE": "false"}):
            self.assertTrue(plugins_allowed())
            self.assertTrue(automatic_refreshes_allowed())
            self.assertEqual(unloaded_plugin_status(None), {"missing": True, "safe_mode_paused": False})
            self.assertEqual(safe_mode_status(), {"safe_mode": False, "safe_mode_effects": []})
            require_plugins_allowed()

    def test_celery_periodic_headers_and_manual_tasks(self):
        from celery import Celery

        app = Celery("safe_mode_test", broker="memory://")

        @app.task
        @skip_periodic_refresh("skipped")
        def refresh():
            return "refreshed"

        with patch.dict(os.environ, {"DISPATCHARR_SAFE_MODE": "true"}):
            self.assertEqual(refresh.apply(headers={"periodic_task_name": "source"}).get(), "skipped")
            self.assertEqual(refresh.apply().get(), "refreshed")
