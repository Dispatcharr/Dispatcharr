"""Tests for the beat-driven log rotation task (core.tasks.rotate_log_file)."""

import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase, override_settings

from core import tasks
from core.models import CoreSettings, SYSTEM_SETTINGS_KEY
from core.serializers import CoreSettingsSerializer, _clamp_int


class RotateLogFileTests(TestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="dispatcharr-logrot-")
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)
        self.live = os.path.join(self.log_dir, "dispatcharr.log")

    # Patch the Redis-backed lock (no real Redis needed) and CoreSettings (force a small 1MB cap).
    @mock.patch(
        "core.tasks.CoreSettings.get_system_settings",
        return_value={"log_max_mb": 1, "log_keep": 5},
    )
    @mock.patch("core.tasks.release_task_lock", return_value=None)
    @mock.patch("core.tasks.acquire_task_lock", return_value=True)
    def test_noop_when_under_cap(self, mock_acquire, mock_release, mock_settings):
        with override_settings(LOG_FILE_DIR=self.log_dir):
            with open(self.live, "wb") as f:
                f.write(b"a small amount of log output\n")
            before = os.path.getsize(self.live)

            tasks.rotate_log_file.run()

        # File left untouched and no rotated generation created.
        self.assertTrue(os.path.exists(self.live))
        self.assertEqual(os.path.getsize(self.live), before)
        self.assertFalse(os.path.exists(self.live + ".1"))
        # The cheap size check returns before the lock is ever taken.
        mock_acquire.assert_not_called()

    @mock.patch(
        "core.tasks.CoreSettings.get_system_settings",
        return_value={"log_max_mb": 1, "log_keep": 5},
    )
    @mock.patch("core.tasks.release_task_lock", return_value=None)
    @mock.patch("core.tasks.acquire_task_lock", return_value=True)
    def test_rotates_when_over_cap(self, mock_acquire, mock_release, mock_settings):
        # Just over the 1 MB cap so a rotation is forced.
        payload = b"OLD-LOG-CONTENT\n" + b"x" * (1024 * 1024)
        with override_settings(LOG_FILE_DIR=self.log_dir):
            with open(self.live, "wb") as f:
                f.write(payload)

            tasks.rotate_log_file.run()

        # Live file recreated empty; previous content preserved in .1.
        self.assertTrue(os.path.exists(self.live))
        self.assertEqual(os.path.getsize(self.live), 0)
        rotated = self.live + ".1"
        self.assertTrue(os.path.exists(rotated))
        with open(rotated, "rb") as f:
            self.assertEqual(f.read(), payload)
        # Rotation is serialized under the lock.
        mock_acquire.assert_called_once()
        mock_release.assert_called_once()

    @mock.patch("core.tasks.release_task_lock", return_value=None)
    @mock.patch("core.tasks.acquire_task_lock", return_value=True)
    def test_returns_early_when_live_file_absent(self, mock_acquire, mock_release):
        # Returns on the missing-file check before any settings are read.
        with override_settings(LOG_FILE_DIR=self.log_dir):
            # No dispatcharr.log written at all.
            tasks.rotate_log_file.run()
        mock_acquire.assert_not_called()

    @mock.patch("core.tasks.release_task_lock", return_value=None)
    @mock.patch("core.tasks.acquire_task_lock", return_value=True)
    def test_noop_in_console_only_mode(self, mock_acquire, mock_release):
        # LOG_FILE_DIR is None when /data isn't writable (console-only).
        with override_settings(LOG_FILE_DIR=None):
            tasks.rotate_log_file.run()
        mock_acquire.assert_not_called()

    @mock.patch(
        "core.tasks.CoreSettings.get_system_settings",
        return_value={"log_max_mb": 100, "log_keep": 3},
    )
    @mock.patch("core.tasks.release_task_lock", return_value=None)
    @mock.patch("core.tasks.acquire_task_lock", return_value=True)
    def test_prunes_archives_beyond_keep(self, mock_acquire, mock_release, mock_settings):
        # Live file is well under the cap, but the container-start rotation
        # (which never deletes) has left more archives than the retention limit.
        with override_settings(LOG_FILE_DIR=self.log_dir):
            with open(self.live, "wb") as f:
                f.write(b"current run\n")
            for i in range(1, 8):
                with open(f"{self.live}.{i}", "wb") as f:
                    f.write(f"archive {i}\n".encode())

            tasks.rotate_log_file.run()

        # Only log_keep (3) archives survive; the older ones are pruned.
        for i in range(1, 4):
            self.assertTrue(os.path.exists(f"{self.live}.{i}"))
        for i in range(4, 8):
            self.assertFalse(os.path.exists(f"{self.live}.{i}"))
        # Live file untouched (under cap); prune runs under the lock.
        self.assertTrue(os.path.exists(self.live))
        mock_acquire.assert_called_once()
        mock_release.assert_called_once()

    @mock.patch(
        "core.tasks.CoreSettings.get_system_settings",
        return_value={"log_max_mb": 1, "log_keep": 5},
    )
    @mock.patch("core.tasks.release_task_lock", return_value=None)
    @mock.patch("core.tasks.acquire_task_lock", return_value=True)
    def test_rotation_shifts_existing_archives(self, mock_acquire, mock_release, mock_settings):
        with override_settings(LOG_FILE_DIR=self.log_dir):
            with open(f"{self.live}.1", "wb") as f:
                f.write(b"previous\n")
            with open(self.live, "wb") as f:
                f.write(b"NEW\n" + b"x" * (1024 * 1024))  # over the 1 MB cap

            tasks.rotate_log_file.run()

        # New content becomes .1; the old .1 shifts to .2.
        self.assertEqual(os.path.getsize(self.live), 0)
        with open(f"{self.live}.1", "rb") as f:
            self.assertTrue(f.read().startswith(b"NEW\n"))
        with open(f"{self.live}.2", "rb") as f:
            self.assertEqual(f.read(), b"previous\n")

    @mock.patch(
        "core.tasks.CoreSettings.get_system_settings",
        return_value={"log_max_mb": "abc", "log_keep": "xyz"},
    )
    @mock.patch("core.tasks.release_task_lock", return_value=None)
    @mock.patch("core.tasks.acquire_task_lock", return_value=True)
    def test_survives_garbage_settings(self, mock_acquire, mock_release, mock_settings):
        # A non-numeric API value used to crash on int("abc"); it must now fall back to the 10 MB default and leave a small log untouched.
        with override_settings(LOG_FILE_DIR=self.log_dir):
            with open(self.live, "wb") as f:
                f.write(b"small\n")
            tasks.rotate_log_file.run()  # must not raise
        self.assertTrue(os.path.exists(self.live))
        self.assertFalse(os.path.exists(self.live + ".1"))
        mock_acquire.assert_not_called()

    @mock.patch(
        "core.tasks.CoreSettings.get_system_settings",
        return_value={"log_max_mb": 0, "log_keep": 5},
    )
    @mock.patch("core.tasks.release_task_lock", return_value=None)
    @mock.patch("core.tasks.acquire_task_lock", return_value=True)
    def test_zero_cap_clamps_to_floor(self, mock_acquire, mock_release, mock_settings):
        # log_max_mb=0 would "rotate every tick"; the 1 MB floor makes it a real cap, so a >1 MB log rotates exactly once.
        with override_settings(LOG_FILE_DIR=self.log_dir):
            with open(self.live, "wb") as f:
                f.write(b"x" * (2 * 1024 * 1024))
            tasks.rotate_log_file.run()
        self.assertTrue(os.path.exists(self.live + ".1"))
        self.assertEqual(os.path.getsize(self.live), 0)


class ClampIntTests(TestCase):
    def test_coerces_and_clamps(self):
        self.assertEqual(tasks._clamped_int("abc", 10, 1, 1000), 10)  # garbage -> default
        self.assertEqual(tasks._clamped_int(None, 10, 1, 1000), 10)  # missing -> default
        self.assertEqual(tasks._clamped_int("50", 10, 1, 1000), 50)  # numeric string
        self.assertEqual(tasks._clamped_int(5000, 10, 1, 1000), 1000)  # above hi -> hi
        self.assertEqual(tasks._clamped_int(0, 10, 1, 1000), 1)  # below lo -> lo
        self.assertEqual(tasks._clamped_int(10.9, 10, 1, 1000), 10)  # float truncates

    def test_serializer_and_task_helpers_agree(self):
        # Two independent copies (defense in depth) must behave identically.
        for v in ("abc", None, "7", 99999, -3, 12.5):
            self.assertEqual(tasks._clamped_int(v, 5, 1, 50), _clamp_int(v, 5, 1, 50))


# locmem cache: isolates this test's settings write from the shared Redis-backed group cache.
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "log-rotation-tests",
        }
    }
)
class SystemSettingsCoercionTests(TestCase):
    def test_update_coerces_log_settings(self):
        # A raw API payload with garbage log settings must persist as clamped ints, so the rotator never reads back garbage.
        inst, _ = CoreSettings.objects.get_or_create(
            key=SYSTEM_SETTINGS_KEY, defaults={"value": {}}
        )
        CoreSettingsSerializer().update(
            inst, {"value": {"log_max_mb": "abc", "log_keep": 999}}
        )
        inst.refresh_from_db()
        self.assertEqual(inst.value["log_max_mb"], 10)  # garbage -> default
        self.assertEqual(inst.value["log_keep"], 50)  # above max -> clamped
