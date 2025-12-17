import logging
import traceback
from celery import shared_task

from . import services

logger = logging.getLogger(__name__)


def _cleanup_old_backups(retention_count: int) -> int:
    """Delete old backups, keeping only the most recent N. Returns count deleted."""
    if retention_count <= 0:
        return 0

    backups = services.list_backups()
    if len(backups) <= retention_count:
        return 0

    # Backups are sorted newest first, so delete from the end
    to_delete = backups[retention_count:]
    deleted = 0

    for backup in to_delete:
        try:
            services.delete_backup(backup["name"])
            deleted += 1
            logger.info(f"[CLEANUP] Deleted old backup: {backup['name']}")
        except Exception as e:
            logger.error(f"[CLEANUP] Failed to delete {backup['name']}: {e}")

    return deleted


@shared_task(bind=True)
def create_backup_task(self):
    """Celery task to create a backup asynchronously."""
    try:
        logger.info(f"[BACKUP] Starting backup task {self.request.id}")
        backup_file = services.create_backup()
        logger.info(f"[BACKUP] Task {self.request.id} completed: {backup_file.name}")
        return {
            "status": "completed",
            "filename": backup_file.name,
            "size": backup_file.stat().st_size,
        }
    except Exception as e:
        logger.error(f"[BACKUP] Task {self.request.id} failed: {str(e)}")
        logger.error(f"[BACKUP] Traceback: {traceback.format_exc()}")
        return {
            "status": "failed",
            "error": str(e),
        }


@shared_task(bind=True)
def restore_backup_task(self, filename: str):
    """Celery task to restore a backup asynchronously."""
    try:
        logger.info(f"[RESTORE] Starting restore task {self.request.id} for {filename}")
        backup_dir = services.get_backup_dir()
        backup_file = backup_dir / filename
        logger.info(f"[RESTORE] Backup file path: {backup_file}")
        services.restore_backup(backup_file)
        logger.info(f"[RESTORE] Task {self.request.id} completed successfully")
        return {
            "status": "completed",
            "filename": filename,
        }
    except Exception as e:
        logger.error(f"[RESTORE] Task {self.request.id} failed: {str(e)}")
        logger.error(f"[RESTORE] Traceback: {traceback.format_exc()}")
        return {
            "status": "failed",
            "error": str(e),
        }


@shared_task(bind=True)
def scheduled_backup_task(self, retention_count: int = 0):
    """Celery task for scheduled backups with optional retention cleanup."""
    try:
        logger.info(f"[SCHEDULED] Starting scheduled backup task {self.request.id}")

        # Create backup
        backup_file = services.create_backup()
        logger.info(f"[SCHEDULED] Backup created: {backup_file.name}")

        # Cleanup old backups if retention is set
        deleted = 0
        if retention_count > 0:
            deleted = _cleanup_old_backups(retention_count)
            logger.info(f"[SCHEDULED] Cleanup complete, deleted {deleted} old backup(s)")

        return {
            "status": "completed",
            "filename": backup_file.name,
            "size": backup_file.stat().st_size,
            "deleted_count": deleted,
        }
    except Exception as e:
        logger.error(f"[SCHEDULED] Task {self.request.id} failed: {str(e)}")
        logger.error(f"[SCHEDULED] Traceback: {traceback.format_exc()}")
        return {
            "status": "failed",
            "error": str(e),
        }
