"""Plugin capabilities registry and manifest-version compatibility.

Single source of truth for what a plugin can declare it needs (e.g.
``background_tasks``) and what manifest schema version it was written
against. Pure/stdlib only, with no Django or DB dependency, so it can be
imported by both ``PluginManager`` and lightweight standalone tooling (e.g.
the ``plugins_worker_needed`` management command) without pulling in Celery
or triggering ``PluginManager``'s discovery/leadership machinery.
"""
from typing import Any, Dict, List

from .version_utils import compare_versions

# Each capability a plugin can declare in its manifest's "capabilities" list.
# `requires_restart` marks capabilities that bind to infrastructure only
# started at container boot (e.g. the dedicated `plugins` Celery worker).
# Granting one of these to a plugin doesn't take effect until the
# celery/AIO container is restarted, unlike most future capabilities which
# are expected to be pure runtime permission checks.
KNOWN_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "background_tasks": {
        "label": "Run background tasks",
        "description": "Uses a dedicated Celery worker to run long-running or scheduled work.",
        "requires_restart": True,
    },
    "persistent_service": {
        "label": "Run a persistent background service",
        "description": (
            "Elected as a cluster-wide leader to run a long-lived service "
            "(e.g. bind a port or run its own loop) via "
            "on_leader_acquired/on_leader_lost."
        ),
        "requires_restart": False,
    },
}

# manifest_version -> minimum Dispatcharr app version that understands it.
# Absent "manifest_version" in plugin.json is treated as version 0 (every
# plugin manifest written before this capabilities system existed). Version
# 1 is the first schema version aware of "capabilities"/"manifest_version".
MANIFEST_VERSION_MIN_APP_VERSION: Dict[int, str] = {
    0: "0.0.0",
    1: "0.28.2",
}


def compute_effective_capabilities(manifest: Dict[str, Any]) -> List[str]:
    """Return the sorted, deduplicated set of capabilities a plugin needs.

    Combines the manifest's explicit "capabilities" array with a back-compat
    inference: any action already opting into "async": true implies
    background_tasks, even if the plugin author never updated the
    manifest-wide capabilities array.
    """
    declared = manifest.get("capabilities")
    caps = set(c for c in declared if isinstance(c, str)) if isinstance(declared, list) else set()

    actions = manifest.get("actions")
    if isinstance(actions, list) and any(
        isinstance(a, dict) and a.get("async") for a in actions
    ):
        caps.add("background_tasks")

    return sorted(caps)


def capability_requires_restart(capability_id: str) -> bool:
    return bool(KNOWN_CAPABILITIES.get(capability_id, {}).get("requires_restart", False))


def describe_capabilities(capability_ids: List[str]) -> List[Dict[str, Any]]:
    """Expand capability ids into {id, label, description, requires_restart}
    dicts for the API/frontend, so the label/description/restart-requirement
    only needs to live in one place (KNOWN_CAPABILITIES above). Unknown ids
    (e.g. declared by a plugin built against a newer Dispatcharr than this
    one) get a generic "Custom capability" label instead of being dropped,
    so newer plugins degrade gracefully on older frontends.
    """
    described = []
    for capability_id in capability_ids:
        info = KNOWN_CAPABILITIES.get(capability_id)
        if info:
            described.append({
                "id": capability_id,
                "label": info["label"],
                "description": info["description"],
                "requires_restart": bool(info.get("requires_restart", False)),
            })
        else:
            described.append({
                "id": capability_id,
                "label": f"Custom capability: {capability_id}",
                "description": "",
                "requires_restart": False,
            })
    return described


def parse_manifest_version(manifest: Dict[str, Any]) -> int:
    """Parse manifest["manifest_version"], defaulting to 0 (legacy/implicit).

    Falls back to 0 on any garbage input (non-int, negative) rather than
    raising, since a malformed manifest_version shouldn't prevent the rest
    of the manifest from loading.
    """
    raw = manifest.get("manifest_version", 0)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value >= 0 else 0


def min_app_version_for_manifest_version(manifest_version: int) -> str:
    """Return the minimum Dispatcharr version required to understand a
    given manifest_version. Unknown/future versions fall back to the
    highest version this build knows about, so a build encountering a
    manifest version newer than anything in the table treats it as
    "requires at least the newest version we know how to require" rather
    than silently assuming full compatibility."""
    if manifest_version in MANIFEST_VERSION_MIN_APP_VERSION:
        return MANIFEST_VERSION_MIN_APP_VERSION[manifest_version]
    return MANIFEST_VERSION_MIN_APP_VERSION[max(MANIFEST_VERSION_MIN_APP_VERSION)]


def manifest_version_supported(manifest_version: int, app_version: str) -> bool:
    """True if `app_version` is >= the minimum version required to
    understand `manifest_version`."""
    required = min_app_version_for_manifest_version(manifest_version)
    return compare_versions(app_version, required) >= 0
