"""Conditional gevent monkey-patching for uWSGI gevent mode.

Call patch_if_needed() before any stdlib imports that need patching
(socket, ssl, threading, etc.). Safe to call multiple times — skips
if already patched or if not running under uWSGI with gevent.
"""


def patch_if_needed():
    """Apply gevent monkey-patching only when uWSGI is running in gevent mode.

    Uses thread=False to avoid replacing _thread.get_ident(), which would
    corrupt importlib's per-module locks when patch_all() is called from
    within a module import (as uWSGI always does). The uWSGI gevent loop
    engine handles green-thread scheduling directly, so thread patching
    is not needed.
    """
    try:
        import uwsgi
        if uwsgi.opt.get(b'gevent') or uwsgi.opt.get('gevent'):
            from gevent import monkey
            if not monkey.is_module_patched('socket'):
                monkey.patch_all(thread=False)
    except (ImportError, AttributeError):
        pass
