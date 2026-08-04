import os
import sys

from django.core.management.base import BaseCommand

from apps.plugins.capabilities import compute_effective_capabilities
from apps.plugins.loader import read_plugin_manifest
from apps.plugins.models import PluginConfig


class Command(BaseCommand):
    """Exit 0 if any *enabled* plugin declares (or implies via a manifest
    action's "async": true) the "background_tasks" capability, exit 1
    otherwise.

    Deliberately standalone: does not instantiate PluginManager, to avoid
    its discovery/leadership side effects. Used by docker/plugins-worker-guard.sh
    at container startup to decide whether to spawn the dedicated `plugins`
    Celery worker. Fails open (exit 0) on any unexpected error, since a
    detection bug should never silently prevent a plugin's background tasks
    from running.
    """

    help = "Exit 0 if the dedicated plugins Celery worker is needed, exit 1 otherwise."

    def handle(self, *args, **options):
        try:
            needed = self._is_worker_needed()
        except Exception as exc:
            self.stderr.write(self.style.WARNING(
                f"plugins_worker_needed: detection failed ({exc}); failing open (worker needed)."
            ))
            sys.exit(0)

        if needed:
            self.stdout.write("yes")
            sys.exit(0)
        self.stdout.write("no")
        sys.exit(1)

    def _is_worker_needed(self) -> bool:
        plugins_dir = os.environ.get("DISPATCHARR_PLUGINS_DIR", "/data/plugins")
        enabled_keys = set(
            PluginConfig.objects.filter(enabled=True).values_list("key", flat=True)
        )
        if not enabled_keys:
            return False

        if not os.path.isdir(plugins_dir):
            return False

        for entry in os.listdir(plugins_dir):
            path = os.path.join(plugins_dir, entry)
            if not os.path.isdir(path):
                continue
            has_pkg = os.path.exists(os.path.join(path, "__init__.py"))
            has_pluginpy = os.path.exists(os.path.join(path, "plugin.py"))
            if not (has_pkg or has_pluginpy):
                continue

            plugin_key = entry.replace(" ", "_").lower()
            if plugin_key not in enabled_keys:
                continue

            manifest, has_manifest = read_plugin_manifest(path)
            if not has_manifest or not isinstance(manifest, dict):
                continue

            if "background_tasks" in compute_effective_capabilities(manifest):
                return True

        return False
