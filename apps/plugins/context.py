"""Execution context and capability checks for plugin code.

These checks are a same-process safety net, not an isolation boundary. Plugin
code remains trusted and can deliberately bypass Python-level guards.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional, Sequence

_plugin_key: ContextVar[Optional[str]] = ContextVar("running_plugin_key", default=None)
_plugin_capabilities: ContextVar[Optional[Sequence[str]]] = ContextVar(
    "running_plugin_capabilities", default=None
)
_plugin_manifest_schema_version: ContextVar[Optional[int]] = ContextVar(
    "running_plugin_manifest_schema_version", default=None
)


@contextmanager
def running_as_plugin(
    key: str,
    *,
    capabilities: Optional[Sequence[str]] = None,
    manifest_schema_version: Optional[int] = None,
) -> Iterator[None]:
    token = _plugin_key.set(key)
    capabilities_token = _plugin_capabilities.set(capabilities)
    schema_token = _plugin_manifest_schema_version.set(manifest_schema_version)
    try:
        yield
    finally:
        _plugin_manifest_schema_version.reset(schema_token)
        _plugin_capabilities.reset(capabilities_token)
        _plugin_key.reset(token)


def current_plugin_key() -> Optional[str]:
    return _plugin_key.get()


def plugin_has_capability(capability_id: str) -> bool:
    """Return whether the active plugin is allowed to use a capability.

    Core code is never gated. Legacy and transition manifests remain advisory;
    sandbox checks only apply to manifest version 2 and later.
    """
    key = current_plugin_key()
    if key is None:
        return True

    from .capabilities import manifest_version_enforces_sandbox
    from .loader import PluginManager

    plugin = PluginManager.get().get_plugin(key)
    if plugin is None:
        manifest_schema_version = _plugin_manifest_schema_version.get()
        capabilities = _plugin_capabilities.get()
        if manifest_schema_version is None or capabilities is None:
            return False
        return (
            not manifest_version_enforces_sandbox(manifest_schema_version)
            or capability_id in capabilities
        )
    return bool(
        not manifest_version_enforces_sandbox(plugin.manifest_schema_version)
        or capability_id in (plugin.capabilities or [])
    )


def require_plugin_capability(capability_id: str) -> None:
    if plugin_has_capability(capability_id):
        return
    raise PermissionError(
        f"Plugin '{current_plugin_key()}' requires the '{capability_id}' capability."
    )
