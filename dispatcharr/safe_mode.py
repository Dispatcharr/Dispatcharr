"""Runtime-only recovery mode, shared by web and Celery processes."""
import os
from functools import wraps


AUTOMATIC_REFRESH_TASKS = frozenset({
    "apps.m3u.tasks.refresh_single_m3u_account",
    "apps.m3u.tasks.refresh_m3u_accounts",
    "apps.m3u.tasks.refresh_m3u_groups",
    "apps.epg.tasks.refresh_epg_data",
    "apps.epg.tasks.refresh_all_epg_data",
})

SAFE_MODE_EFFECTS = (
    {"id": "plugins", "label": "Plugins", "status": "Disabled"},
    {"id": "automatic_refreshes", "label": "Automatic M3U and EPG refreshes", "status": "Disabled"},
)


def safe_mode_enabled():
    return os.environ.get("DISPATCHARR_SAFE_MODE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def safe_mode_status():
    enabled = safe_mode_enabled()
    return {"safe_mode": enabled, "safe_mode_effects": list(SAFE_MODE_EFFECTS) if enabled else []}


def plugins_allowed():
    return not safe_mode_enabled()


def automatic_refreshes_allowed():
    return not safe_mode_enabled()


def require_plugins_allowed():
    if not plugins_allowed():
        raise RuntimeError("Plugins cannot be loaded while Dispatcharr safe mode is active")


def unloaded_plugin_status(path):
    """Distinguish deliberately unloaded plugins from missing files."""
    if plugins_allowed():
        return {"missing": True, "safe_mode_paused": False}
    missing = not any(os.path.isfile(os.path.join(path, name))
                      for name in ("plugin.py", "__init__.py"))
    return {"missing": missing, "safe_mode_paused": not missing}


def skip_queued_periodic_refresh():
    """Recognize refresh jobs that Beat queued before safe mode started."""
    if automatic_refreshes_allowed():
        return False
    from celery import current_task
    if current_task is None:
        return False
    request = current_task.request
    return bool(getattr(request, "periodic_task_name", None) or
                (getattr(request, "headers", None) or {}).get("periodic_task_name"))


def skip_periodic_refresh(result):
    """Leave manual refreshes available but skip periodic jobs queued before startup."""
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            if skip_queued_periodic_refresh():
                return result
            return func(*args, **kwargs)
        return wrapped
    return decorator
