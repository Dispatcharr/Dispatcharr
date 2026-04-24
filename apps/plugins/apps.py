from django.apps import AppConfig
import os
import sys
from django.db.models.signals import post_migrate


class PluginsConfig(AppConfig):
    name = "apps.plugins"
    verbose_name = "Plugins"

    def ready(self):
        """Wire up plugin discovery without hitting the DB during app init.

        - Skip during common management commands that don't need discovery.
        - Register post_migrate handler to sync plugin registry to DB after migrations.
        - Do an in-memory discovery (no DB) so registry is available early.
        """
        try:
            # Allow explicit opt-out via env var
            if os.environ.get("DISPATCHARR_SKIP_PLUGIN_AUTODISCOVERY", "").lower() in ("1", "true", "yes"):
                return

            argv = sys.argv[1:] if len(sys.argv) > 1 else []
            mgmt_cmds_to_skip = {
                # Skip immediate discovery for these commands
                "makemigrations", "collectstatic", "check", "test", "shell", "showmigrations",
            }
            if argv and argv[0] in mgmt_cmds_to_skip:
                return

            # Run discovery with DB sync after the plugins app has been migrated
            def _post_migrate_discover(sender=None, app_config=None, **kwargs):
                try:
                    if app_config and getattr(app_config, 'label', None) != 'plugins':
                        return
                    from .loader import PluginManager
                    PluginManager.get().discover_plugins(sync_db=True)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Plugin discovery failed in post_migrate")

            post_migrate.connect(
                _post_migrate_discover,
                dispatch_uid="apps.plugins.post_migrate_discover",
            )

            # Perform non-DB discovery now to populate in-memory registry.
            from .loader import PluginManager
            PluginManager.get().discover_plugins(sync_db=False)
        except Exception:
            # Avoid breaking startup due to plugin errors
            import logging

            logging.getLogger(__name__).exception("Plugin discovery wiring failed during app ready")

        # Register periodic task for refreshing plugin repo manifests
        self._setup_repo_refresh_schedule()

        # Refresh repo manifests once at startup so the UI always has current data
        self._enqueue_startup_refresh()

    def _enqueue_startup_refresh(self):
        from dispatcharr.app_initialization import should_skip_initialization
        if should_skip_initialization():
            return
        try:
            from .tasks import refresh_plugin_repos
            refresh_plugin_repos.apply_async(countdown=10)
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                "Could not enqueue startup plugin repo refresh (Celery may not be ready yet)"
            )

    def _setup_repo_refresh_schedule(self):
        from dispatcharr.app_initialization import should_skip_initialization
        if should_skip_initialization():
            return
        try:
            from core.scheduling import create_or_update_periodic_task, delete_periodic_task
            from core.models import CoreSettings
            from .tasks import PLUGIN_REPO_REFRESH_TASK_NAME

            interval = 6
            try:
                obj = CoreSettings.objects.get(key="plugin_repo_settings")
                interval = obj.value.get("refresh_interval_hours", 6)
            except CoreSettings.DoesNotExist:
                pass

            if interval == 0:
                delete_periodic_task(PLUGIN_REPO_REFRESH_TASK_NAME)
            else:
                create_or_update_periodic_task(
                    task_name=PLUGIN_REPO_REFRESH_TASK_NAME,
                    celery_task_path="apps.plugins.tasks.refresh_plugin_repos",
                    interval_hours=interval,
                    enabled=True,
                )
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                "Could not set up plugin repo refresh schedule (migrations may not have run yet)"
            )
