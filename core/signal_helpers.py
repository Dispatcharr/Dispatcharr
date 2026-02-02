# core/signal_helpers.py
"""
Thread-local storage utilities for tracking state changes between pre_save and post_save signals.

This module provides a way to pass data from pre_save to post_save signal handlers
without mutating the model instance itself.

Usage:
    In pre_save handler:
        _set_context('MyModel', instance.pk, {'field_changed': True})

    In post_save handler:
        ctx = _get_instance_context('MyModel', instance.pk)
        if 'field_changed' in ctx:
            # do something
            _clear_context('MyModel', instance.pk)
"""
import threading
import time
import logging

logger = logging.getLogger(__name__)

# Thread-local storage for tracking state changes between pre_save and post_save
_signal_context = threading.local()

# Context entries older than this (in seconds) are considered stale and can be cleaned up
_CONTEXT_STALE_THRESHOLD = 60


def _get_context():
    """Get the thread-local context dict, creating if needed."""
    if not hasattr(_signal_context, 'changes'):
        _signal_context.changes = {}
    return _signal_context.changes


def _clear_context(model_name, pk):
    """Clear context for a specific model instance."""
    ctx = _get_context()
    key = f"{model_name}:{pk}"
    if key in ctx:
        del ctx[key]


def _set_context(model_name, pk, data):
    """
    Set context for a specific model instance.

    Includes a timestamp for stale entry detection.
    """
    ctx = _get_context()
    key = f"{model_name}:{pk}"
    ctx[key] = {
        'data': data,
        'timestamp': time.time(),
    }


def _get_instance_context(model_name, pk):
    """Get context data for a specific model instance."""
    ctx = _get_context()
    key = f"{model_name}:{pk}"
    entry = ctx.get(key, {})
    # Return just the data portion, not the metadata
    return entry.get('data', {}) if isinstance(entry, dict) and 'data' in entry else entry


def clear_all_context():
    """
    Clear all thread-local context.

    Call this at the end of each request to prevent data leakage
    between requests in thread-pooled servers.
    """
    if hasattr(_signal_context, 'changes'):
        _signal_context.changes.clear()


def clear_stale_context():
    """
    Clear context entries older than the stale threshold.

    This can be called periodically to clean up orphaned entries
    that were never cleared due to exceptions or other issues.

    Returns the number of entries cleared.
    """
    ctx = _get_context()
    current_time = time.time()
    stale_keys = []

    for key, entry in ctx.items():
        if isinstance(entry, dict) and 'timestamp' in entry:
            if current_time - entry['timestamp'] > _CONTEXT_STALE_THRESHOLD:
                stale_keys.append(key)
        elif isinstance(entry, dict):
            # Legacy entry without timestamp - consider it stale
            stale_keys.append(key)

    for key in stale_keys:
        logger.debug(f"Clearing stale signal context: {key}")
        del ctx[key]

    return len(stale_keys)


def get_context_stats():
    """
    Get statistics about current thread-local context.

    Useful for debugging and monitoring.
    """
    ctx = _get_context()
    current_time = time.time()

    stats = {
        'total_entries': len(ctx),
        'entries_by_model': {},
        'stale_entries': 0,
    }

    for key, entry in ctx.items():
        model_name = key.split(':')[0] if ':' in key else 'unknown'
        stats['entries_by_model'][model_name] = stats['entries_by_model'].get(model_name, 0) + 1

        if isinstance(entry, dict) and 'timestamp' in entry:
            if current_time - entry['timestamp'] > _CONTEXT_STALE_THRESHOLD:
                stats['stale_entries'] += 1

    return stats
