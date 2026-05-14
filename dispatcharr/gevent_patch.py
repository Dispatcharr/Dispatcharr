"""
Loaded via uWSGI's `import = dispatcharr.gevent_patch` directive.

Two things happen here:

1. gevent stdlib monkey-patching - replaces blocking socket/threading/os
   primitives with gevent-cooperative versions. `gevent-early-monkey-patch = true`
   in the ini should already have done this; calling it again is a safe no-op if
   it did, and a necessary fallback if it didn't (e.g. older uWSGI build).

2. psycogreen - installs a wait callback on psycopg2 so libpq yields to the
   gevent hub during I/O instead of blocking the OS thread.

Without (1), `async_to_sync(channel_layer.group_send)` in send_websocket_update
would call epoll_wait() directly, freezing every greenlet on the worker (the
90s pile-up observed on Worker 9). With (1), select.epoll is removed by
monkey-patching, which breaks asyncio event loop creation in threadpool threads.
send_websocket_update therefore uses a synchronous Redis path in gevent workers
instead of asyncio - see _gevent_ws_send() in core/utils.py.

Without (2), psycopg2 network calls pin the worker during slow/stalled queries.

Celery and Daphne run in separate daemon processes and do not load this module.

Note: this module runs before Django configures logging, so print() is used
instead of logger so output reaches uWSGI's stdout.
"""
import sys

from gevent import monkey

if not monkey.is_module_patched("socket"):
    print(
        "[gevent_patch] WARNING: gevent-early-monkey-patch did not run - "
        "applying monkey.patch_all() now.",
        file=sys.stderr,
        flush=True,
    )
    monkey.patch_all()
else:
    print("[gevent_patch] gevent stdlib monkey-patching already active.", flush=True)

try:
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
    print("[gevent_patch] psycogreen: psycopg2 patched for gevent.", flush=True)
except ImportError:
    print(
        "[gevent_patch] WARNING: psycogreen not installed - "
        "psycopg2 will block the gevent hub during DB I/O. "
        "Run: uv pip install psycogreen",
        file=sys.stderr,
        flush=True,
    )
