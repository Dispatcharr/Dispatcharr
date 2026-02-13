import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class BackupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backups"
    verbose_name = "Backups"

    def ready(self):
        """Initialize backup scheduler on app startup."""
        from dispatcharr.app_initialization import should_skip_initialization

        # Skip if this is a management command, worker process, or dev server
        if should_skip_initialization():
            return

        logger.debug("Syncing backup scheduler on app startup")
        self._sync_backup_scheduler()

    def _sync_backup_scheduler(self):
        """Sync backup scheduler task to database."""
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
