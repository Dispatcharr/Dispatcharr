"""Plugin capabilities registry and manifest-version compatibility.

Single source of truth for what a plugin can declare it needs (e.g.
``background_tasks``) and what manifest schema version it was written
against. Pure/stdlib only, with no Django or DB dependency, so it can be
imported by lightweight standalone tooling without pulling in Celery or
triggering ``PluginManager``'s discovery/leadership machinery.
"""
from typing import Any, Dict, List, Optional

from .version_utils import compare_versions

# Each capability a plugin can declare in its manifest's "capabilities" list.
# `requires_restart` marks capabilities that bind to infrastructure only
# started at container boot. Granting one of these to a plugin doesn't take
# effect until the celery/AIO container is restarted, unlike most other
# capabilities which are expected to be pure runtime permission checks.
KNOWN_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "background_tasks": {
        "label": "Run background tasks",
        "description": "Runs long-running or scheduled work on Dispatcharr's shared background task queue.",
        "requires_restart": False,
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "persistent_service": {
        "label": "Run a persistent background service",
        "description": (
            "Elected as a cluster-wide leader to run a long-lived service "
            "(e.g. bind a port or run its own loop) via "
            "on_leader_acquired/on_leader_lost."
        ),
        "requires_restart": False,
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "network_listener": {
        "label": "Listen for network connections",
        "description": "Binds a socket or web server that accepts inbound network connections.",
        "requires_restart": True,
        "impact": "high",
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "subprocess": {
        "label": "Run host processes",
        "description": "Starts commands or processes on the Dispatcharr host.",
        "requires_restart": False,
        "impact": "high",
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "outbound_network": {
        "label": "Access external network services",
        "description": "Connects to remote hosts or makes outbound HTTP requests.",
        "requires_restart": False,
        "impact": "high",
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "filesystem_write": {
        "label": "Write outside plugin storage",
        "description": "Writes files outside the plugin's own data directory.",
        "requires_restart": False,
        "impact": "high",
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "celery_dispatch": {
        "label": "Dispatch approved internal tasks",
        "description": "Queues explicitly approved Dispatcharr background tasks.",
        "requires_restart": False,
        "impact": "high",
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "proxy_internals": {
        "label": "Use live proxy internals",
        "description": "Uses Dispatcharr live-stream proxy implementation details.",
        "requires_restart": False,
        "impact": "standard",
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "user_data": {
        "label": "Access user account data",
        "description": "Reads Dispatcharr user account data.",
        "requires_restart": False,
        "impact": "high",
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
    "external_dependencies": {
        "label": "Install external Python dependencies",
        "description": "Installs declared third-party Python packages for this plugin.",
        "requires_restart": False,
        "impact": "high",
        "min_manifest_version": 1,
        "max_manifest_version": None,
    },
}

# Manifest schema compatibility and behavior. Absent manifest_version is 0.
# A null bound means the schema has no bound in that direction yet.
MANIFEST_SCHEMA_POLICIES: Dict[int, Dict[str, Any]] = {
    0: {
        "min_app_version": None,
        "max_app_version": None,
        "parses_capabilities": False,
        "enforces_sandbox": False,
    },
    1: {
        "min_app_version": "0.28.2",
        "max_app_version": None,
        "parses_capabilities": True,
        "enforces_sandbox": False,
    },
    2: {
        "min_app_version": "0.29.0",
        "max_app_version": None,
        "parses_capabilities": True,
        "enforces_sandbox": True,
    },
}


def capability_supported_by_manifest_version(capability_id: str, manifest_version: int) -> bool:
    """Whether a known capability can be parsed for a manifest version.

    Unknown capability ids are retained so manifests from newer Dispatcharr
    releases continue to degrade gracefully.
    """
    if not manifest_version_parses_capabilities(manifest_version):
        return False

    policy = KNOWN_CAPABILITIES.get(capability_id)
    if policy is None:
        return True

    min_manifest_version = policy["min_manifest_version"]
    max_manifest_version = policy["max_manifest_version"]
    return (
        (min_manifest_version is None or manifest_version >= min_manifest_version)
        and (max_manifest_version is None or manifest_version <= max_manifest_version)
    )


def compute_effective_capabilities(manifest: Dict[str, Any]) -> List[str]:
    """Return the sorted, deduplicated set of capabilities a plugin needs.

    Uses each capability's manifest-version bounds, then combines explicit
    declarations with an inference: any action opting into "async": true
    implies background_tasks when that capability is valid for the manifest.
    """
    manifest_version = parse_manifest_version(manifest)
    declared = manifest.get("capabilities")
    caps = (
        set(
            capability_id
            for capability_id in declared
            if isinstance(capability_id, str)
            and capability_supported_by_manifest_version(capability_id, manifest_version)
        )
        if isinstance(declared, list)
        else set()
    )

    actions = manifest.get("actions")
    if isinstance(actions, list) and any(
        isinstance(a, dict) and a.get("async") for a in actions
    ):
        if capability_supported_by_manifest_version("background_tasks", manifest_version):
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
                "impact": info.get("impact", "standard"),
            })
        else:
            described.append({
                "id": capability_id,
                "label": f"Custom capability: {capability_id}",
                "description": "",
                "requires_restart": False,
                "impact": "standard",
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


def manifest_schema_policy(manifest_version: int) -> Dict[str, Any]:
    """Return the policy for a manifest version.

    Future manifest versions use the latest known policy. This preserves the
    existing best-effort compatibility behavior and keeps sandbox enforcement
    enabled for newer manifests.
    """
    if manifest_version in MANIFEST_SCHEMA_POLICIES:
        return MANIFEST_SCHEMA_POLICIES[manifest_version]
    return MANIFEST_SCHEMA_POLICIES[max(MANIFEST_SCHEMA_POLICIES)]


def manifest_version_enforces_sandbox(manifest_version: int) -> bool:
    """Whether a manifest version must satisfy capability sandbox gates.

    Version 0 is legacy and version 1 is the open-ended capabilities
    transition period. Future versions remain enforcing so a newer manifest
    does not lose protection when parsed best-effort by this build.
    """
    return bool(manifest_schema_policy(manifest_version)["enforces_sandbox"])


def manifest_version_parses_capabilities(manifest_version: int) -> bool:
    """Whether the manifest schema supports capability declarations."""
    return bool(manifest_schema_policy(manifest_version)["parses_capabilities"])


def min_app_version_for_manifest_version(manifest_version: int) -> Optional[str]:
    """Return the optional lower Dispatcharr compatibility bound."""
    return manifest_schema_policy(manifest_version)["min_app_version"]


def max_app_version_for_manifest_version(manifest_version: int) -> Optional[str]:
    """Return the optional upper Dispatcharr compatibility bound."""
    return manifest_schema_policy(manifest_version)["max_app_version"]


def manifest_version_supported(manifest_version: int, app_version: str) -> bool:
    """True if `app_version` is within the manifest compatibility bounds."""
    min_app_version = min_app_version_for_manifest_version(manifest_version)
    max_app_version = max_app_version_for_manifest_version(manifest_version)
    return (
        (min_app_version is None or compare_versions(app_version, min_app_version) >= 0)
        and (max_app_version is None or compare_versions(app_version, max_app_version) <= 0)
    )
