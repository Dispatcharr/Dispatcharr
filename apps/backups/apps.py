import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


class BackupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backups"
    verbose_name = "Backups"

    def ready(self):
        post_migrate.connect(
            self._sync_backup_scheduler,
            sender=self,
            dispatch_uid="apps.backups.sync_scheduler",
            weak=False,
        )

    def _sync_backup_scheduler(self, **kwargs):
        """Sync the backup scheduler after migrations finish."""
        from django.db import close_old_connections

        from core.models import CoreSettings
        from .scheduler import _sync_periodic_task, DEFAULTS
        try:
            CoreSettings.objects.get_or_create(
                key="backup_settings",
                defaults={"name": "Backup Settings", "value": DEFAULTS.copy()}
            )

            logger.debug("Syncing backup scheduler")
            _sync_periodic_task()
        except Exception as e:
            logger.warning(f"Failed to initialize backup scheduler: {e}")
        finally:
            close_old_connections()
