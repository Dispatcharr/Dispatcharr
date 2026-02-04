import logging
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class BackupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backups"
    verbose_name = "Backups"

    def ready(self):
        """Initialize backup scheduler on app startup."""
        # Only run in the main process (not in workers, beat, or management commands)
        if 'runserver' in sys.argv or 'uwsgi' in sys.argv[0] if sys.argv else False:
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
