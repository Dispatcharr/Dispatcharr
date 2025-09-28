from __future__ import annotations

import logging

from celery import shared_task
from .models import BackupJob
from . import services

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_backup_task(self, job_id: int, scheduled: bool = False) -> int:
    job = BackupJob.objects.get(pk=job_id)
    job.scheduled = scheduled
    job.save(update_fields=["scheduled"])
    if self.request and getattr(self.request, "id", None):
        if job.celery_task_id != self.request.id:
            job.celery_task_id = self.request.id
            job.save(update_fields=["celery_task_id", "updated_at"])
    job.mark_running()
    try:
        archive_path = services.create_backup_archive(job)
        job.mark_succeeded(file_size=archive_path.stat().st_size)
        services.enforce_retention()
        logger.info("Backup job %s completed", job_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Backup job %s failed", job_id)
        job.mark_failed(str(exc))
        raise
    return job_id


@shared_task(bind=True)
def run_scheduled_backup(self, scheduled: bool = True) -> int:
    job = BackupJob.objects.create(
        job_type=BackupJob.JobType.BACKUP,
        status=BackupJob.Status.PENDING,
        scheduled=scheduled,
    )
    async_result = run_backup_task.apply_async(args=[job.id], kwargs={"scheduled": scheduled})
    job.celery_task_id = async_result.id
    job.save(update_fields=["celery_task_id", "updated_at"])
    return job.id


@shared_task(bind=True)
def run_restore_task(self, job_id: int) -> int:
    job = BackupJob.objects.get(pk=job_id)
    if self.request and getattr(self.request, "id", None):
        job.celery_task_id = self.request.id
        job.save(update_fields=["celery_task_id", "updated_at"])
    job.mark_running()
    try:
        services.restore_archive(job)
        job.mark_succeeded()
        logger.info("Restore job %s completed", job_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Restore job %s failed", job_id)
        job.mark_failed(str(exc))
        raise
    return job_id
