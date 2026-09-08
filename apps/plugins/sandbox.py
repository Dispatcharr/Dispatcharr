"""Plugin-local, best-effort wrappers for selected high-risk Python APIs.

Wrappers are installed in a plugin module's builtins rather than globally. They
are defense in depth only: a plugin shares this interpreter and is not isolated.
"""
import builtins
import os
from functools import wraps
from types import ModuleType
from typing import Any, Dict

from .context import current_plugin_key, require_plugin_capability


def _guard(capability_id, func):
    @wraps(func)
    def guarded(*args, **kwargs):
        require_plugin_capability(capability_id)
        return func(*args, **kwargs)
    return guarded


class _SocketProxy:
    def __init__(self, socket):
        self._socket = socket

    def bind(self, *args, **kwargs):
        require_plugin_capability("network_listener")
        return self._socket.bind(*args, **kwargs)

    def listen(self, *args, **kwargs):
        require_plugin_capability("network_listener")
        return self._socket.listen(*args, **kwargs)

    def connect(self, *args, **kwargs):
        require_plugin_capability("outbound_network")
        return self._socket.connect(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._socket, name)


class _ModuleProxy(ModuleType):
    def __init__(self, module, wrappers):
        super().__init__(module.__name__)
        self._module = module
        self._wrappers = wrappers

    def __getattr__(self, name):
        value = getattr(self._module, name)
        wrapper = self._wrappers.get(name)
        return wrapper(value) if wrapper else value


def _guard_module(name: str, module):
    if name == "subprocess":
        return _ModuleProxy(module, {
            attr: lambda value: _guard("subprocess", value)
            for attr in ("Popen", "run", "call", "check_call", "check_output")
        })
    if name == "socket":
        return _ModuleProxy(module, {"socket": lambda value: lambda *a, **kw: _SocketProxy(value(*a, **kw))})
    if name == "requests":
        return _ModuleProxy(module, {
            attr: lambda value: _guard("outbound_network", value)
            for attr in ("get", "post", "put", "patch", "delete", "request")
        })
    if name == "urllib.request":
        return _ModuleProxy(module, {
            attr: lambda value: _guard("outbound_network", value)
            for attr in ("urlopen", "urlretrieve")
        })
    return module


def stable_plugin_data_path(plugin_key: str, plugin_path: str, storage_key: str = "") -> str:
    """Return the version-stable sibling directory owned by a plugin."""
    plugin_path = os.path.abspath(plugin_path)
    stable_storage_key = storage_key or plugin_key
    if (
        not isinstance(stable_storage_key, str)
        or not stable_storage_key
        or stable_storage_key in {".", ".."}
        or os.path.basename(stable_storage_key) != stable_storage_key
    ):
        stable_storage_key = plugin_key
    return os.path.join(os.path.dirname(plugin_path), f"{stable_storage_key}_data")


def _plugin_open(plugin_key: str, plugin_path: str, storage_key: str = ""):
    plugin_path = os.path.abspath(plugin_path)
    stable_data_path = stable_plugin_data_path(plugin_key, plugin_path, storage_key)
    allowed_roots = (plugin_path, stable_data_path)

    @wraps(builtins.open)
    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            try:
                path = os.path.abspath(os.fspath(file))
            except TypeError:
                path = ""
            if not any(path == root or path.startswith(f"{root}{os.sep}") for root in allowed_roots):
                require_plugin_capability("filesystem_write")
        return builtins.open(file, mode, *args, **kwargs)
    return guarded_open


def plugin_builtins(plugin_key: str, plugin_path: str, storage_key: str = "") -> Dict[str, Any]:
    """Return a builtins mapping that guards imports made by one plugin module."""
    values = dict(vars(builtins))
    original_import = builtins.__import__

    @wraps(original_import)
    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        module = original_import(name, globals, locals, fromlist, level)
        if current_plugin_key() != plugin_key:
            return module
        if name in {"subprocess", "socket", "requests", "urllib.request"}:
            return _guard_module(name, module)
        return module

    values["__import__"] = guarded_import
    values["open"] = _plugin_open(plugin_key, plugin_path, storage_key)
    return values
