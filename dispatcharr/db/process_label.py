"""Label Postgres connections by Dispatcharr process role (for pg_stat_activity)."""

from __future__ import annotations

import os
import sys


def _is_uwsgi_worker() -> bool:
    """True when running inside a uWSGI worker (not master or a non-uWSGI process)."""
    try:
        import uwsgi
    except ImportError:
        return False
    return uwsgi.worker_id() > 0


def get_process_role(argv: list[str] | None = None) -> str:
    argv = argv if argv is not None else sys.argv
    argv0 = os.path.basename(argv[0]) if argv else ""
    cmdline = " ".join(argv)

    if "celery" in argv0 or any("celery" in arg for arg in argv):
        if "beat" in cmdline:
            return "celery-beat"
        if "-Q" in argv:
            try:
                if "dvr" in argv[argv.index("-Q") + 1]:
                    return "celery-dvr"
            except (IndexError, ValueError):
                pass
        return "celery-worker"
    if "daphne" in argv0:
        return "daphne"
    if argv0 == "manage.py" and len(argv) > 1:
        return f"manage-{argv[1]}"
    if _is_uwsgi_worker() or argv0 == "uwsgi":
        return "uwsgi"
    return "django"


def uses_geventpool_database_backend(argv: list[str] | None = None) -> bool:
    """
    True for uWSGI/Daphne/manage (gevent or request-scoped pooling).

    Celery prefork/thread workers must use Django's standard PostgreSQL backend:
    django-db-geventpool keeps a process-wide warm-connection pool that fork()
    duplicates across autoscale children, which corrupts Postgres session state.
    """
    return get_process_role(argv) not in ("celery-worker", "celery-dvr", "celery-beat")


def db_application_name() -> str:
    return f"Dispatcharr-{get_process_role()}-{os.getpid()}"
