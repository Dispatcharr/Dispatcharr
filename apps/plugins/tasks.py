import logging
import os
import time

from celery import shared_task

logger = logging.getLogger(__name__)

PLUGIN_REPO_REFRESH_TASK_NAME = "plugin-repo-refresh-task"

# opt in via env var if you want one anyway.
PLUGIN_TASK_SOFT_TIME_LIMIT = os.environ.get("CELERY_PLUGIN_TASK_SOFT_TIME_LIMIT_SECONDS")
PLUGIN_TASK_TIME_LIMIT = os.environ.get("CELERY_PLUGIN_TASK_TIME_LIMIT_SECONDS")

_task_kwargs = {"bind": True, "name": "apps.plugins.tasks.run_plugin_action"}
if PLUGIN_TASK_SOFT_TIME_LIMIT:
    _task_kwargs["soft_time_limit"] = int(PLUGIN_TASK_SOFT_TIME_LIMIT)
if PLUGIN_TASK_TIME_LIMIT:
    _task_kwargs["time_limit"] = int(PLUGIN_TASK_TIME_LIMIT)


@shared_task(**_task_kwargs)
def run_plugin_action_task(self, key, action_id, params=None):
    """Runs a plugin action on the dedicated `plugins` queue and always sends
    a terminal plugin_task_complete websocket event."""
    from apps.plugins.loader import PluginManager
    from apps.plugins.task_history import record_task_complete
    from core.utils import send_websocket_update

    task_id = self.request.id
    try:
        result = PluginManager.get().run_action(key, action_id, params or {}, task_id=task_id)
    except Exception as e:
        send_websocket_update("updates", "update", {
            "type": "plugin_task_complete",
            "plugin": key,
            "task_id": task_id,
            "status": "error",
            "error": str(e),
            "updatedAt": int(time.time() * 1000),
        })
        record_task_complete(key, task_id, "error", error=str(e))
        raise
    send_websocket_update("updates", "update", {
        "type": "plugin_task_complete",
        "plugin": key,
        "task_id": task_id,
        "status": "ok",
        "result": result,
        "updatedAt": int(time.time() * 1000),
    })
    record_task_complete(key, task_id, "ok", result=result)
    return result


def evaluate_plugin_update_notification(plugin_key, name, installed_version, latest_version, install_status):
    """
    Create, update, or delete the SystemNotification for a single plugin's
    update-available state, keyed by plugin_key so re-evaluation is idempotent.

    Mirrors apps.m3u.tasks.evaluate_profile_expiration_notification: only an
    "update_available" status keeps the notification active; any other status
    deletes it (and broadcasts the dismissal so other open sessions clear it).
    """
    from core.models import SystemNotification
    from core.utils import send_websocket_notification, send_notification_dismissed

    key = f"plugin-update-{plugin_key}"

    if install_status != "update_available":
        deleted = list(
            SystemNotification.objects.filter(notification_key=key)
            .values_list("notification_key", flat=True)
        )
        SystemNotification.objects.filter(notification_key=key).delete()
        for k in deleted:
            send_notification_dismissed(k)
        return None

    notification, _created = SystemNotification.objects.update_or_create(
        notification_key=key,
        defaults={
            "notification_type": SystemNotification.NotificationType.PLUGIN_UPDATE,
            "priority": SystemNotification.Priority.NORMAL,
            "title": f"Plugin Update Available: {name}",
            "message": f'"{name}" can be updated from {installed_version} to {latest_version}.',
            "action_data": {
                "plugin_key": plugin_key,
                "installed_version": installed_version,
                "latest_version": latest_version,
                "action_url": f"/plugins/{plugin_key}",
                "action_text": "View Plugin",
            },
            "is_active": True,
            "admin_only": True,
        },
    )
    send_websocket_notification(notification)
    return key


@shared_task
def refresh_plugin_repos():
    """Refresh cached manifests for all enabled plugin repos."""
    from .models import PluginConfig, PluginRepo
    from .api_views import _fetch_manifest, _save_fetched_manifest_to_repo, _unmanage_dropped_slugs
    from .version_utils import get_plugin_status
    from core.models import SystemNotification
    from core.utils import send_notification_dismissed
    from django.utils import timezone

    repos = list(PluginRepo.objects.filter(enabled=True))
    for repo in repos:
        try:
            key_text = repo.public_key if not repo.is_official else None
            data, verified = _fetch_manifest(repo.url, public_key_text=key_text)
            err = _save_fetched_manifest_to_repo(repo, data, verified)
            if err:
                logger.warning("Skipping repo '%s': %s", repo.name, err)
                continue
            _unmanage_dropped_slugs(repo, data)
            logger.info("Refreshed plugin repo '%s'", repo.name)
        except Exception as e:
            resp = getattr(e, 'response', None)
            status_str = str(resp.status_code) if resp is not None and hasattr(resp, 'status_code') else type(e).__name__
            repo.last_fetch_status = status_str[:255]
            repo.last_fetched = timezone.now()
            repo.save(update_fields=["last_fetch_status", "last_fetched", "updated_at"])
            logger.warning("Failed to refresh plugin repo '%s': %s", repo.name, e)

    # Evaluate plugin-update notifications for every managed plugin against
    # the freshly-refreshed repo manifests.
    active_keys = set()
    manifest_by_repo = {}
    for repo in repos:
        manifest_data = repo.cached_manifest or {}
        manifest = manifest_data.get("manifest", manifest_data)
        manifest_by_repo[repo.id] = {
            rp.get("slug", ""): rp.get("latest_version", "")
            for rp in manifest.get("plugins", []) if rp.get("slug")
        }

    for cfg in PluginConfig.objects.filter(source_repo_id__isnull=False).select_related("source_repo"):
        latest = manifest_by_repo.get(cfg.source_repo_id, {}).get(cfg.slug, "")
        install_status = get_plugin_status(
            cfg.version,
            latest,
            is_prerelease=cfg.installed_version_is_prerelease,
            is_managed=True,
        )
        active_key = evaluate_plugin_update_notification(
            cfg.key, cfg.name, cfg.version, latest, install_status
        )
        if active_key:
            active_keys.add(active_key)

    stale = SystemNotification.objects.filter(
        is_active=True, notification_key__startswith="plugin-update-"
    ).exclude(notification_key__in=active_keys)
    stale_keys = list(stale.values_list("notification_key", flat=True))
    stale.delete()
    for k in stale_keys:
        send_notification_dismissed(k)
