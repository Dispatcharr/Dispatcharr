from __future__ import annotations

from django.db import models
from django.utils import timezone
from pathlib import Path
from django.conf import settings


class BackupJob(models.Model):
    class JobType(models.TextChoices):
        BACKUP = "backup", "Backup"
        RESTORE = "restore", "Restore"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    job_type = models.CharField(
        max_length=16,
        choices=JobType.choices,
        default=JobType.BACKUP,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    scheduled = models.BooleanField(default=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backup_jobs",
    )
    file_path = models.CharField(max_length=1024, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def mark_running(self):
        self.status = self.Status.RUNNING
        self.error_message = ""
        self.save(update_fields=["status", "error_message", "updated_at"])

    def mark_failed(self, message: str):
        self.status = self.Status.FAILED
        self.error_message = message[:65535]
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at", "updated_at"])

    def mark_succeeded(self, file_size: int | None = None):
        self.status = self.Status.SUCCEEDED
        fields = ["status", "completed_at", "updated_at"]
        if file_size is not None:
            self.file_size = file_size
            fields.append("file_size")
        self.completed_at = timezone.now()
        self.save(update_fields=fields)

    def mark_canceled(self):
        self.status = self.Status.CANCELED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    @property
    def file_name(self) -> str:
        path = self.archive_path
        return path.name if path else ""

    @property
    def archive_path(self) -> Path | None:
        if not self.file_path:
            return None
        path = Path(self.file_path)
        if path.is_absolute():
            return path
        try:
            from core.models import CoreSettings  # Local import to avoid circular

            configured = CoreSettings.get_backup_path()
        except Exception:
            configured = None

        base = Path(settings.BACKUP_ROOT)
        if configured:
            configured_path = Path(configured)
            if configured_path.is_absolute():
                base = configured_path
            else:
                base = (base / configured_path).resolve()
        return base / path

    def delete_archive(self):
        path = self.archive_path
        if not path:
            return
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

    @property
    def can_cancel(self) -> bool:
        return (
            self.job_type == self.JobType.BACKUP
            and self.status in {self.Status.PENDING, self.Status.RUNNING}
            and bool(self.celery_task_id)
        )

    @property
    def can_delete(self) -> bool:
        if self.status in {self.Status.RUNNING}:
            return False
        return True

    def __str__(self) -> str:
        return f"{self.get_job_type_display()} job {self.pk} ({self.status})"
