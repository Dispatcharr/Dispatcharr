from django.apps import AppConfig
from django.conf import settings
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
        from dispatcharr.app_initialization import should_skip_initialization

        from django.conf import settings as django_settings
        from dispatcharr.log_collector import apply_settings

        try:
            from core.models import CoreSettings

            apply_settings(
                getattr(django_settings, "LOG_FILE_DIR", None),
                CoreSettings.get_system_settings(),
            )
        except Exception:
            # Database not migrated yet: the collector keeps its defaults.
            pass

        try:
            self._seed_public_port_from_env()
        except Exception:
            # Database not migrated yet: seeding is retried on next startup.
            pass

        # Sync developer notifications and check for version updates on startup
        # Only run in the main process (not in management commands, migrations, or workers)
        if should_skip_initialization():
            return

        self._sync_developer_notifications()

    def _seed_public_port_from_env(self):
        """One-time seed of Settings > System > Public Port from
        DISPATCHARR_PUBLIC_PORT, for Docker deployments that map a
        non-default host port (e.g. `8080:9191`) and want it set at deploy
        time instead of clicking through the admin UI after first boot.

        Only applies while the setting has never been configured. Once set -
        by this seed or manually via the UI - the DB value is the source of
        truth and this env var is ignored on every later startup, so a UI
        correction always sticks even if the env var is later removed or
        left at a stale value.
        """
        import os
        from core.models import CoreSettings

        env_value = os.environ.get("DISPATCHARR_PUBLIC_PORT")
        if not env_value:
            return
        if CoreSettings.get_public_port() is not None:
            return
        CoreSettings.set_public_port(env_value)

    def _sync_developer_notifications(self):
        """Sync developer notifications from JSON file to database."""
        from django.db import close_old_connections
        import logging

        logger = logging.getLogger(__name__)

        try:
            from core.developer_notifications import sync_developer_notifications
            sync_developer_notifications()
        except Exception as e:
            logger.warning(f"Failed to sync developer notifications on startup: {e}")
        finally:
            # Boot ORM runs outside a request cycle; return geventpool checkouts.
            close_old_connections()

