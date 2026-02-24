"""Utilities for managing app initialization across multiple processes."""

import sys
import os
import psutil
import logging

logger = logging.getLogger(__name__)


def _is_worker_process():
    """Check if this process is a worker spawned by uwsgi/gunicorn."""
    try:
        parent = psutil.Process(os.getppid())
        parent_name = parent.name()
        return parent_name in ['uwsgi', 'gunicorn']
    except Exception:
        # If we can't determine, assume it's not a worker (safe default)
        return False


def should_skip_initialization():
    """
    Determine if app initialization should be skipped in this process.

    Returns True if:
    - A management command is being run (migrate, celery, shell, etc.)
    - The development server (daphne) is running
    - This is a worker process (not the master)

    This prevents redundant initialization across multiple worker processes.
    """
    # Skip management commands and background services
    skip_commands = [
        'celery', 'beat', 'migrate', 'makemigrations', 'shell', 'dbshell',
        'collectstatic', 'loaddata'
    ]
    if any(cmd in sys.argv for cmd in skip_commands):
        logger.debug(f"Skipping initialization due to command: {sys.argv}")
        return True

    # Skip daphne development server (single process, no need to guard)
    if 'daphne' in sys.argv[0] if sys.argv else False:
        logger.debug(f"Skipping initialization in daphne development server. Command: {sys.argv}")
        return True

    # Skip if this is a worker process spawned by uwsgi/gunicorn
    if _is_worker_process():
        logger.debug(f"Skipping initialization in worker process. Command: {sys.argv}")
        return True

    return False
