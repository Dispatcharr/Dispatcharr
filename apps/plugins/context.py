"""Execution context and capability checks for plugin code.

These checks are a same-process safety net, not an isolation boundary. Plugin
code remains trusted and can deliberately bypass Python-level guards.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_plugin_key: ContextVar[Optional[str]] = ContextVar("running_plugin_key", default=None)


@contextmanager
def running_as_plugin(key: str) -> Iterator[None]:
    token = _plugin_key.set(key)
    try:
        yield
    finally:
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
    return bool(
        plugin
        and (
            not manifest_version_enforces_sandbox(plugin.manifest_schema_version)
            or capability_id in (plugin.capabilities or [])
        )
    )


def require_plugin_capability(capability_id: str) -> None:
    if plugin_has_capability(capability_id):
        return
    raise PermissionError(
        f"Plugin '{current_plugin_key()}' requires the '{capability_id}' capability."
    )
