from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import BackupJob
from core.models import CoreSettings
from . import services, tasks


import json
import tarfile

class BackupServicesTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.tempdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tempdir, ignore_errors=True))
        self.backup_root = self.tempdir / "backups"
        self.backup_root.mkdir()
        self.data_dir = self.tempdir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "sample.txt").write_text("original", encoding="utf-8")
        self.recordings_dir = self.tempdir / "recordings"
        self.recordings_dir.mkdir()
        (self.recordings_dir / "clip.txt").write_text("recording", encoding="utf-8")

        self.settings_override = override_settings(
            BACKUP_ROOT=str(self.backup_root),
            BACKUP_DATA_DIRS=[self.data_dir, self.recordings_dir],
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        CoreSettings.set_backup_path(str(self.backup_root))
        CoreSettings.set_backup_retention_count(2)
        CoreSettings.set_backup_include_recordings(True)

    @patch("apps.backups.services.call_command")
    def test_create_backup_archive_generates_manifest_and_tarball(self, call_command):
        def side_effect(command, *args, **kwargs):
            if command == "dumpdata":
                stdout = kwargs["stdout"]
                stdout.write("[]")
            return None

        call_command.side_effect = side_effect

        job = BackupJob.objects.create(job_type=BackupJob.JobType.BACKUP)
        archive_path = services.create_backup_archive(job)

        self.assertTrue(archive_path.exists())
        job.refresh_from_db()
        self.assertEqual(job.file_path, archive_path.name)
        self.assertIsNotNone(job.file_size)

        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()
            self.assertIn("database.json", names)
            self.assertIn("manifest.json", names)
            self.assertTrue(any(name.startswith("data/") for name in names))

            manifest = json.loads(tar.extractfile("manifest.json").read())
            self.assertIn(str(self.data_dir), manifest["data_directories"])
            self.assertIn(str(self.recordings_dir), manifest["data_directories"])
            self.assertIn("schedule", manifest)
            self.assertEqual(manifest["schedule"]["preset"], "daily")

    @patch("apps.backups.services.call_command")
    def test_create_backup_archive_excludes_recordings_when_disabled(self, call_command):
        def side_effect(command, *args, **kwargs):
            if command == "dumpdata":
                kwargs["stdout"].write("[]")
            return None

        call_command.side_effect = side_effect
        CoreSettings.set_backup_include_recordings(False)

        job = BackupJob.objects.create(job_type=BackupJob.JobType.BACKUP)
        archive_path = services.create_backup_archive(job)

        with tarfile.open(archive_path, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read())
            self.assertNotIn(str(self.recordings_dir), manifest["data_directories"])
        CoreSettings.set_backup_include_recordings(True)

    def test_enforce_retention_prunes_older_archives(self):
        CoreSettings.set_backup_retention_count(1)
        job_old = BackupJob.objects.create(job_type=BackupJob.JobType.BACKUP)
        job_new = BackupJob.objects.create(job_type=BackupJob.JobType.BACKUP)

        older_file = self.backup_root / "older.tar.gz"
        older_file.write_text("older")
        job_old.file_path = older_file.name
        job_old.status = BackupJob.Status.SUCCEEDED
        job_old.save()

        newer_file = self.backup_root / "newer.tar.gz"
        newer_file.write_text("newer")
        job_new.file_path = newer_file.name
        job_new.status = BackupJob.Status.SUCCEEDED
        job_new.save()

        services.enforce_retention()

        self.assertFalse(BackupJob.objects.filter(pk=job_old.pk).exists())
        self.assertTrue(BackupJob.objects.filter(pk=job_new.pk).exists())

    @patch("apps.backups.services.call_command")
    def test_restore_archive_rehydrates_files(self, call_command):
        def call_side_effect(command, *args, **kwargs):
            # skip destructive database operations during test
            return None

        call_command.side_effect = call_side_effect

        with patch("apps.backups.services.call_command") as dump_mock:
            def dump_side_effect(command, *args, **kwargs):
                if command == "dumpdata":
                    kwargs["stdout"].write("[]")
                return None

            dump_mock.side_effect = dump_side_effect
            job = BackupJob.objects.create(job_type=BackupJob.JobType.BACKUP)
            archive_path = services.create_backup_archive(job)

        # mutate data after backup so restore must rewrite it
        (self.data_dir / "sample.txt").write_text("modified", encoding="utf-8")

        job.file_path = archive_path.name
        job.status = BackupJob.Status.SUCCEEDED
        job.save(update_fields=["file_path", "status"])

        services.restore_archive(job)

        restored_content = (self.data_dir / "sample.txt").read_text(encoding="utf-8")
        self.assertEqual(restored_content, "original")


class BackupTaskTests(APITestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tempdir, ignore_errors=True))
        self.override = override_settings(BACKUP_ROOT=str(self.tempdir))
        self.override.enable()
        self.addCleanup(self.override.disable)

    @patch("apps.backups.tasks.services.enforce_retention")
    @patch("apps.backups.tasks.services.create_backup_archive")
    def test_run_backup_task_marks_job_success(self, create_archive, enforce_retention):
        archive = self.tempdir / "job.tar.gz"
        archive.write_text("payload")
        create_archive.return_value = archive

        job = BackupJob.objects.create(job_type=BackupJob.JobType.BACKUP)

        tasks.run_backup_task.run(job.id, scheduled=True)

        job.refresh_from_db()
        self.assertEqual(job.status, BackupJob.Status.SUCCEEDED)
        self.assertEqual(job.scheduled, True)
        enforce_retention.assert_called_once()

    @patch("apps.backups.tasks.services.create_backup_archive", side_effect=RuntimeError("boom"))
    def test_run_backup_task_failure_marks_job_failed(self, create_archive):
        job = BackupJob.objects.create(job_type=BackupJob.JobType.BACKUP)

        with self.assertRaises(RuntimeError):
            tasks.run_backup_task.run(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, BackupJob.Status.FAILED)
        self.assertTrue(job.error_message)

    @patch("apps.backups.tasks.services.restore_archive")
    def test_run_restore_task_marks_success(self, restore_archive):
        job = BackupJob.objects.create(
            job_type=BackupJob.JobType.RESTORE,
            file_path="archive.tar.gz",
        )
        job.save()

        tasks.run_restore_task.run(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, BackupJob.Status.SUCCEEDED)


User = get_user_model()


class BackupSettingsAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.client.force_authenticate(self.user)

    def test_get_settings_defaults(self):
        url = reverse("api:backups:backup-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("enabled", response.data)
        self.assertIn("include_recordings", response.data)
        schedule = response.data["schedule"]
        self.assertEqual(schedule["preset"], "daily")
        self.assertEqual(schedule["minute"], "15")
        self.assertEqual(schedule["hour"], "3")
        self.assertEqual(schedule["timezone"], "UTC")

    @patch("apps.backups.api_views.services.sync_backup_schedule")
    def test_update_settings(self, sync_mock):
        url = reverse("api:backups:backup-settings")
        payload = {
            "enabled": True,
            "retention": 3,
            "path": "/tmp/backups",
            "extra_paths": ["/opt/dispatcharr/custom"],
            "include_recordings": False,
            "schedule": {
                "preset": "daily",
                "minute": "45",
                "hour": "12",
                "day_of_month": "*",
                "month": "*",
                "day_of_week": "*",
                "timezone": "UTC",
            },
        }
        response = self.client.put(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(CoreSettings.get_backup_enabled())
        self.assertEqual(CoreSettings.get_backup_retention_count(), 3)
        self.assertEqual(CoreSettings.get_backup_path(), payload["path"])
        self.assertEqual(CoreSettings.get_backup_extra_paths(), payload["extra_paths"])
        self.assertFalse(CoreSettings.get_backup_include_recordings())
        schedule = CoreSettings.get_backup_schedule()
        self.assertEqual(schedule["preset"], "daily")
        self.assertEqual(schedule["minute"], "45")
        self.assertEqual(schedule["hour"], "12")
        sync_mock.assert_called_once()

    def test_invalid_cron_component_rejected(self):
        url = reverse("api:backups:backup-settings")
        payload = {
            "enabled": True,
            "retention": 1,
            "path": "/tmp/backups",
            "schedule": {
                "preset": "custom",
                "minute": "invalid",
                "hour": "*",
                "day_of_month": "*",
                "month": "*",
                "day_of_week": "*",
                "timezone": "UTC",
            },
        }
        response = self.client.put(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.backups.api_views.services.sync_backup_schedule")
    def test_weekly_schedule(self, sync_mock):
        url = reverse("api:backups:backup-settings")
        payload = {
            "enabled": True,
            "retention": 2,
            "path": "/tmp/backups",
            "schedule": {
                "preset": "weekly",
                "minute": "0",
                "hour": "6",
                "day_of_month": "*",
                "month": "*",
                "day_of_week": "mon,wed,fri",
                "timezone": "UTC",
            },
        }
        response = self.client.put(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        schedule = CoreSettings.get_backup_schedule()
        self.assertEqual(schedule["preset"], "weekly")
        self.assertEqual(schedule["day_of_week"], "mon,wed,fri")
        sync_mock.assert_called_once()


class BackupJobAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.client.force_authenticate(self.user)
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tempdir, ignore_errors=True))
        self.override = override_settings(BACKUP_ROOT=Path(self.tempdir))
        self.override.enable()
        self.addCleanup(self.override.disable)
        CoreSettings.set_backup_path(self.tempdir)

    @patch("apps.backups.api_views.run_backup_task.apply_async")
    def test_create_backup_job(self, apply_async_mock):
        from unittest.mock import Mock

        async_result = Mock()
        async_result.id = "celery123"
        apply_async_mock.return_value = async_result
        url = reverse("api:backups:backup-job-list")
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(BackupJob.objects.count(), 1)
        job = BackupJob.objects.first()
        apply_async_mock.assert_called_once_with(args=[job.id], kwargs={"scheduled": False})
        self.assertEqual(job.celery_task_id, "celery123")

    @patch("apps.backups.api_views.run_restore_task.apply_async")
    def test_restore_backup_job(self, apply_async_mock):
        from unittest.mock import Mock

        async_result = Mock()
        async_result.id = "restore123"
        apply_async_mock.return_value = async_result
        job = BackupJob.objects.create(
            job_type=BackupJob.JobType.BACKUP,
            status=BackupJob.Status.SUCCEEDED,
            file_path="sample.tar.gz",
        )
        Path(self.tempdir, "sample.tar.gz").write_bytes(b"example")

        url = reverse("api:backups:backup-job-restore-backup", args=[job.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        restore_job = BackupJob.objects.filter(job_type=BackupJob.JobType.RESTORE).first()
        self.assertIsNotNone(restore_job)
        apply_async_mock.assert_called_once()
        self.assertEqual(restore_job.celery_task_id, "restore123")

    def test_download_backup_job(self):
        archive_path = Path(self.tempdir, "download.tar.gz")
        archive_path.write_bytes(b"data")
        job = BackupJob.objects.create(
            job_type=BackupJob.JobType.BACKUP,
            status=BackupJob.Status.SUCCEEDED,
            file_path="download.tar.gz",
            file_size=archive_path.stat().st_size,
        )
        url = reverse("api:backups:backup-job-download-archive", args=[job.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(int(response["Content-Length"]), 0)

    def test_upload_requires_file(self):
        url = reverse("api:backups:backup-job-upload-and-restore")
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.backups.api_views.run_backup_task.AsyncResult")
    def test_cancel_running_job(self, async_result_mock):
        revoke_mock = async_result_mock.return_value.revoke
        archive_path = Path(self.tempdir, "cancel.tar.gz")
        archive_path.write_bytes(b"partial")
        job = BackupJob.objects.create(
            job_type=BackupJob.JobType.BACKUP,
            status=BackupJob.Status.RUNNING,
            file_path="cancel.tar.gz",
            celery_task_id="task123",
        )

        url = f"/api/backups/jobs/{job.id}/cancel/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        revoke_mock.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJob.Status.CANCELED)
        self.assertFalse(archive_path.exists())

    def test_cancel_job_invalid_state(self):
        job = BackupJob.objects.create(
            job_type=BackupJob.JobType.BACKUP,
            status=BackupJob.Status.SUCCEEDED,
            celery_task_id="task123",
        )
        url = f"/api/backups/jobs/{job.id}/cancel/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_completed_job(self):
        archive_path = Path(self.tempdir, "finished.tar.gz")
        archive_path.write_bytes(b"done")
        job = BackupJob.objects.create(
            job_type=BackupJob.JobType.BACKUP,
            status=BackupJob.Status.SUCCEEDED,
            file_path="finished.tar.gz",
        )
        url = reverse("api:backups:backup-job-detail", kwargs={"pk": job.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BackupJob.objects.filter(pk=job.id).exists())
        self.assertFalse(archive_path.exists())

    def test_delete_running_job_forbidden(self):
        job = BackupJob.objects.create(
            job_type=BackupJob.JobType.BACKUP,
            status=BackupJob.Status.RUNNING,
        )
        url = reverse("api:backups:backup-job-detail", args=[job.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
