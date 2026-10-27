"""Host-owned execution for persistent plugin services.

Plugin services run outside Celery task lifetimes, but must not depend on a
gevent hub being available in every process.  This runner gives lifecycle hooks
a native thread and a cooperative stop event while retaining their plugin
capability context.
"""
import contextvars
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional


DEFAULT_STOP_TIMEOUT = 5


def _native_threading_type(name):
    """Return the pre-gevent implementation of a threading primitive."""
    primitive = getattr(threading, name)
    try:
        import gevent.monkey

        if gevent.monkey.is_module_patched("threading"):
            return gevent.monkey.get_original("threading", name)
    except Exception:
        pass
    return primitive


@dataclass
class PluginService:
    name: str
    stop_event: object
    thread: object


class PluginServiceRunner:
    """Own native-thread lifecycle for one persistent service per plugin."""

    def __init__(self, logger: logging.Logger, stop_timeout: float = DEFAULT_STOP_TIMEOUT):
        self._logger = logger
        self._stop_timeout = stop_timeout
        self._lock = threading.RLock()
        self._services: Dict[str, PluginService] = {}

    def start(self, plugin_key: str, target: Callable, *, name: Optional[str] = None) -> PluginService:
        if not callable(target):
            raise TypeError("Persistent service target must be callable")

        with self._lock:
            current = self._services.get(plugin_key)
            if current and current.thread.is_alive():
                raise RuntimeError(f"Plugin '{plugin_key}' already has a running persistent service")

            event_cls = _native_threading_type("Event")
            thread_cls = _native_threading_type("Thread")
            stop_event = event_cls()
            context = contextvars.copy_context()
            service_name = name or plugin_key

            def run():
                try:
                    context.run(target, stop_event)
                    if not stop_event.is_set():
                        self._logger.warning(
                            "Plugin '%s' persistent service '%s' exited unexpectedly",
                            plugin_key,
                            service_name,
                        )
                except Exception:
                    self._logger.exception(
                        "Plugin '%s' persistent service '%s' failed",
                        plugin_key,
                        service_name,
                    )

            thread = thread_cls(target=run, daemon=True)
            thread.name = f"plugin-service:{plugin_key}:{service_name}"
            service = PluginService(service_name, stop_event, thread)
            self._services[plugin_key] = service
            thread.start()
            return service

    def stop(self, plugin_key: str) -> None:
        with self._lock:
            service = self._services.pop(plugin_key, None)
        if service is None:
            return
        service.stop_event.set()
        service.thread.join(timeout=self._stop_timeout)
        if service.thread.is_alive():
            self._logger.warning(
                "Plugin '%s' persistent service '%s' did not stop within %ss",
                plugin_key,
                service.name,
                self._stop_timeout,
            )

    def stop_all(self) -> None:
        with self._lock:
            keys = list(self._services)
        for plugin_key in keys:
            self.stop(plugin_key)
