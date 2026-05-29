"""
Loaded via uWSGI's `import = dispatcharr.gevent_patch` directive.

gevent stdlib monkey-patching - replaces blocking socket/threading/os
primitives with gevent-cooperative versions. `gevent-early-monkey-patch = true`
in the ini should already have done this; calling it again is a safe no-op if
it did, and a necessary fallback if it didn't (e.g. older uWSGI build).

Without this, `async_to_sync(channel_layer.group_send)` in send_websocket_update
calls epoll_wait() directly, which blocks the OS thread and freezes all greenlets
on the worker until the call returns. With monkey-patching, select.epoll is
replaced, which breaks asyncio event loop creation in threadpool threads.
send_websocket_update therefore uses a synchronous Redis path in gevent workers
instead of asyncio - see _gevent_ws_send() in core/utils.py.

psycopg3 uses Python's socket layer for I/O, so monkey.patch_all() provides
gevent compatibility without any additional driver patching.

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


