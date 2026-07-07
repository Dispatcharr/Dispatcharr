"""
Django settings for running the backend test suite in isolation.

Always use this module instead of dispatcharr.settings when running tests:

    python manage.py test

`manage.py` selects this module automatically for the ``test`` command.

Django creates a separate empty database (``test_<POSTGRES_DB>``) and runs
migrations — your live data under /data/db is not used.

Why not dispatcharr.settings?
- Production/AIO points at the live ``dispatcharr`` database.
- django-db-geventpool breaks TestCase transaction isolation on pooled connections.

SQLite (``TEST_USE_SQLITE=1``) is an optional fallback for machines without
Postgres; production and CI should use the default Postgres test database.
"""
import os

from dispatcharr.settings import *  # noqa: F401,F403

# Fast password hashing for tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Do NOT run Celery tasks inline during tests. post_save signals on M3UAccount and
# EPGSource call .delay(); eager mode runs them inside TestCase transactions and
# closes/poisons the DB connection for subsequent queries in the same test.
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = False

_use_sqlite = os.environ.get("TEST_USE_SQLITE", "").lower() in ("1", "true", "yes")

if _use_sqlite:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    # Default: PostgreSQL with Django-managed test_dispatcharr (matches production).
    # Uses the standard backend (not geventpool) so TestCase transactions isolate.
    _pg_name = os.environ.get("POSTGRES_DB", "dispatcharr")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _pg_name,
            "USER": os.environ.get("POSTGRES_USER", "dispatch"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "secret"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": int(os.environ.get("POSTGRES_PORT", 5432)),
            "TEST": {
                "NAME": "test_" + _pg_name,
                # Match production UTF-8 so JSON programme indexes and EPG text
                # with non-ASCII characters can be stored in tests.
                "CHARSET": "UTF8",
                "TEMPLATE": "template0",
            },
        }
    }
