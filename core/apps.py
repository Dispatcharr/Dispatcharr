from django.apps import AppConfig
from django.db.models.signals import post_migrate
import logging

# Define TRACE level (5 is below DEBUG which is 10)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

# Add trace method to the Logger class
def trace(self, message, *args, **kwargs):
    """Log a message with TRACE level (more detailed than DEBUG)"""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)

# Add the trace method to the Logger class
logging.Logger.trace = trace


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Import signals to ensure they get registered
        import core.signals
        post_migrate.connect(
            self._initialize_runtime_state,
            sender=self,
            dispatch_uid="core.initialize_runtime_state",
            weak=False,
        )

    def _initialize_runtime_state(self, **kwargs):
        """Apply database-backed runtime state after migrations finish."""
        from django.db import close_old_connections
        from django.conf import settings
        from core.models import CoreSettings, SYSTEM_SETTINGS_KEY
        from core.developer_notifications import sync_developer_notifications
        from dispatcharr.log_collector import apply_settings

        try:
            apply_settings(
                getattr(settings, "LOG_FILE_DIR", None),
                CoreSettings.objects.filter(key=SYSTEM_SETTINGS_KEY)
                .values_list("value", flat=True)
                .first()
                or {},
            )
            sync_developer_notifications()
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Failed to initialize core runtime state: %s", e
            )
        finally:
            close_old_connections()
