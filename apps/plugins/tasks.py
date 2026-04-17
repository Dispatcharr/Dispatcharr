import logging
from celery import shared_task

logger = logging.getLogger(__name__)

PLUGIN_REPO_REFRESH_TASK_NAME = "plugin-repo-refresh-task"


@shared_task
def refresh_plugin_repos():
    """Refresh cached manifests for all enabled plugin repos."""
    from .models import PluginRepo
    from .api_views import _fetch_manifest, _save_fetched_manifest_to_repo, _unmanage_dropped_slugs
    from django.utils import timezone

    repos = PluginRepo.objects.filter(enabled=True)
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
