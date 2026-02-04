import logging
import sys
import os

from django.apps import AppConfig
import psutil

logger = logging.getLogger(__name__)


def _is_worker_process():
    """Check if this process is a worker spawned by uwsgi/gunicorn."""
    try:
        parent = psutil.Process(os.getppid())
        parent_name = parent.name()
        return parent_name in ['uwsgi', 'gunicorn']
    except Exception:
        # If we can't determine, assume it's not a worker (safe default)
        return False


class BackupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backups"
    verbose_name = "Backups"

    def ready(self):
        """Initialize backup scheduler on app startup."""
        # Skip management commands and celery
        skip_commands = ['celery', 'beat', 'migrate', 'makemigrations', 'shell', 'dbshell', 'collectstatic', 'loaddata']
        if any(cmd in sys.argv for cmd in skip_commands):
            return

        # Skip daphne dev server
        if 'daphne' in sys.argv[0] if sys.argv else False:
            return

        # Skip if this is a worker process spawned by uwsgi/gunicorn
        if _is_worker_process():
            return

        # Proceed with syncing the backup scheduler
        self._sync_backup_scheduler()

    def _sync_backup_scheduler(self):
        """Sync backup scheduler task to database."""
        # Import here to avoid circular imports
        from core.models import CoreSettings
        from .scheduler import _sync_periodic_task, DEFAULTS
        try:
            # Ensure settings exist with defaults if this is a new install
            CoreSettings.objects.get_or_create(
                key="backup_settings",
                defaults={"name": "Backup Settings", "value": DEFAULTS.copy()}
            )

            # Always sync the periodic task (handles new installs, updates, or missing tasks)
            logger.debug("Syncing backup scheduler")
            _sync_periodic_task()
        except Exception as e:
            # Log but don't fail startup if there's an issue
            logger.warning(f"Failed to initialize backup scheduler: {e}")
