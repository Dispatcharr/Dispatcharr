from django.apps import AppConfig
from django.conf import settings
import os, logging

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

        # Sync developer notifications and check for version updates on startup
        # Only run in the main process (not in management commands or migrations)
        import sys
        if 'runserver' in sys.argv or 'uwsgi' in sys.argv[0] if sys.argv else False:
            self._sync_developer_notifications()
            self._check_version_update()

    def _sync_developer_notifications(self):
        """Sync developer notifications from JSON file to database."""
        from django.db import connection
        import logging

        logger = logging.getLogger(__name__)

        # Check if tables exist (avoid running during migrations)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'core_systemnotification'"
                )
                if not cursor.fetchone():
                    # For SQLite
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='core_systemnotification'"
                    )
                    if not cursor.fetchone():
                        return
        except Exception:
            # If we can't check, the table might not exist yet
            pass

        try:
            from core.developer_notifications import sync_developer_notifications
            sync_developer_notifications()
        except Exception as e:
            logger.warning(f"Failed to sync developer notifications on startup: {e}")

    def _check_version_update(self):
        """Check for version updates on startup."""
        import logging

        logger = logging.getLogger(__name__)

        try:
            from core.tasks import check_for_version_update
            check_for_version_update.delay()
        except Exception as e:
            logger.warning(f"Failed to check for version updates on startup: {e}")
