from django.apps import AppConfig
import os
import sys
from django.core.cache import cache
from django.core.signals import request_started
from django.db.models.signals import post_migrate


class PluginsConfig(AppConfig):
    name = "apps.plugins"
    verbose_name = "Plugins"

    def ready(self):
        """Wire plugin discovery without querying the DB during app loading."""
        try:
            if os.environ.get("DISPATCHARR_SKIP_PLUGIN_AUTODISCOVERY", "").lower() in ("1", "true", "yes"):
                return

            argv = sys.argv[1:] if len(sys.argv) > 1 else []
            mgmt_cmds_to_skip = {
                # Skip immediate discovery for these commands
                "makemigrations", "collectstatic", "check", "test", "shell", "showmigrations",
            }
            if argv and argv[0] in mgmt_cmds_to_skip:
                return

            def _post_migrate_discover(sender=None, app_config=None, **kwargs):
                try:
                    if app_config and getattr(app_config, 'label', None) != 'plugins':
                        return
                    from .loader import PluginManager
                    PluginManager.get().discover_plugins(sync_db=True)
                    self._setup_repo_refresh_schedule()
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Plugin discovery failed in post_migrate")

            post_migrate.connect(
                _post_migrate_discover,
                dispatch_uid="apps.plugins.post_migrate_discover",
                weak=False,
            )

            _no_discovery_cmds = {'celery', 'beat', 'migrate', 'dbshell', 'loaddata'}
            if not any(cmd in sys.argv for cmd in _no_discovery_cmds):
                request_started.connect(
                    self._discover_for_web_process,
                    dispatch_uid="apps.plugins.discover_for_web_process",
                    weak=False,
                )
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Plugin discovery wiring failed during app ready")

    def _discover_for_web_process(self, **kwargs):
        """Discover plugins at the first request, after Django is fully ready."""
        try:
            from .loader import PluginManager

            PluginManager.get().discover_plugins(sync_db=False, use_cache=True)
            request_started.disconnect(
                dispatch_uid="apps.plugins.discover_for_web_process"
            )
            if cache.add("plugins:startup_repo_refresh", True, timeout=300):
                self._enqueue_startup_refresh()
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Plugin discovery failed at request startup")

    def _enqueue_startup_refresh(self):
        try:
            from .tasks import refresh_plugin_repos
            refresh_plugin_repos.apply_async(countdown=10)
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                "Could not enqueue startup plugin repo refresh (Celery may not be ready yet)"
            )

    def _setup_repo_refresh_schedule(self):
        from django.db import close_old_connections
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
        finally:
            # Boot ORM runs outside a request cycle; return geventpool checkouts.
            close_old_connections()
