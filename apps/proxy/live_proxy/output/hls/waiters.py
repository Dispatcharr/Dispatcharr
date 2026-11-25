"""In-process waiters for the first HLS playlist publish.

Cold-start playlist requests block until the segmenter has enough media.
Polling Redis on a fixed interval would add up to that interval after the
gate clears. Instead, each waiter holds a gevent Event that is set when
the playlist is published: locally on the worker that wrote it, and on
other workers via the existing ``live:events:*`` pubsub bus.
"""

import threading

import gevent.event

_lock = threading.Lock()
# (channel_id, fmt) -> set of Events for held cold-start requests on this worker.
_waiters = {}


def register_playlist_waiter(channel_id, fmt):
    """Return a new Event that will be set when this channel's playlist is ready."""
    event = gevent.event.Event()
    key = (str(channel_id), str(fmt))
    with _lock:
        _waiters.setdefault(key, set()).add(event)
    return event


def unregister_playlist_waiter(channel_id, fmt, event):
    """Drop a waiter Event once its cold-start request is finished."""
    key = (str(channel_id), str(fmt))
    with _lock:
        group = _waiters.get(key)
        if not group:
            return
        group.discard(event)
        if not group:
            _waiters.pop(key, None)


def notify_playlist_ready(channel_id, fmt):
    """Wake every cold-start waiter on this worker for ``channel_id``/``fmt``."""
    key = (str(channel_id), str(fmt))
    with _lock:
        group = list(_waiters.get(key, ()))
    for event in group:
        event.set()
