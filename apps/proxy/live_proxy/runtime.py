"""Decide when the full live-proxy runtime should run.

uWSGI (and gunicorn) workers serve streams: they need the cleanup thread and
the ``live:events:*`` pubsub listener.

Celery, Daphne, and management commands only need Redis coordination when
something like ``ChannelService.stop_channel`` runs. Those processes use
``ProxyServer.get_instance()`` in client-only mode (Redis + worker id, no
background threads).
"""

from __future__ import annotations

from dispatcharr.db.process_label import get_process_role

# Process roles that own/serve live streams (see get_process_role()).
_RUNTIME_ROLES = frozenset({"uwsgi", "gunicorn"})


def should_run_live_proxy_runtime(argv: list[str] | None = None) -> bool:
    """Return True only for processes that should run cleanup + event listener."""
    return get_process_role(argv) in _RUNTIME_ROLES


def start_live_proxy_if_stream_worker():
    """Eager-start the singleton only in stream-serving processes.

    Returns the ``ProxyServer`` instance when started, otherwise ``None``.
    """
    if not should_run_live_proxy_runtime():
        return None
    from .server import ProxyServer

    return ProxyServer.get_instance()
