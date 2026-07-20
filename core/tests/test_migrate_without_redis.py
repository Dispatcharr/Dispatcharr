"""Fresh-install migrate must not require Redis (AIO boot order).

In AIO, ``manage.py migrate`` runs in the entrypoint before uWSGI starts
Redis via ``attach-daemon``. Any data migration that hard-requires Redis
leaves a partially migrated DB and a boot loop (see m3u.0003 / CoreSettings
group cache).

This test creates a throwaway empty database and runs the full migration
graph with the Django cache pointed at an unreachable Redis port. That is
stronger than unit-testing a single settings helper: it catches any
migration that starts depending on Redis.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management import call_command
from django.db import connection, connections
from django.test import SimpleTestCase, override_settings

# Port 1 is never a Redis listener; Connection refused matches AIO first boot.
_UNREACHABLE_REDIS_CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:1/0",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "TIMEOUT": 3600,
    }
}

_TEMP_DB_NAME = "test_dispatcharr_migrate_noredis"


def _admin_connect():
    import psycopg

    db = settings.DATABASES["default"]
    return psycopg.connect(
        host=db["HOST"],
        port=db["PORT"],
        user=db["USER"],
        password=db["PASSWORD"],
        dbname="postgres",
        autocommit=True,
    )


def _drop_database(name: str) -> None:
    admin = _admin_connect()
    try:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        admin.close()


def _create_empty_database(name: str) -> None:
    _drop_database(name)
    admin = _admin_connect()
    try:
        admin.execute(
            f'CREATE DATABASE "{name}" ENCODING \'UTF8\' TEMPLATE template0'
        )
    finally:
        admin.close()


def _point_default_connection_at(name: str) -> None:
    """Retarget the default DB alias without replacing settings.DATABASES.

    ``override_settings(DATABASES=...)`` leaves ConnectionHandler's cached
    settings pointing at the old dict, so migrate would silently keep using
    the already-migrated test database.
    """
    connections.close_all()
    settings.DATABASES["default"]["NAME"] = name
    # connections.settings is the same dict after first configure; keep NAME
    # in sync if a copy was ever taken.
    connections.settings["default"]["NAME"] = name


class FreshMigrateWithoutRedisTests(SimpleTestCase):
    """Full migration suite against an empty DB while Redis is unreachable."""

    databases = {"default"}

    def test_full_migrate_succeeds_when_redis_is_unreachable(self):
        engine = settings.DATABASES["default"]["ENGINE"]
        if engine.endswith("sqlite3"):
            self.skipTest("Requires PostgreSQL (matches AIO fresh install)")

        original_name = settings.DATABASES["default"]["NAME"]
        _create_empty_database(_TEMP_DB_NAME)

        try:
            _point_default_connection_at(_TEMP_DB_NAME)
            with override_settings(CACHES=_UNREACHABLE_REDIS_CACHES):
                self.assertEqual(connection.settings_dict["NAME"], _TEMP_DB_NAME)
                # interactive=False: same as entrypoint ``migrate --noinput``.
                call_command("migrate", verbosity=0, interactive=False)

                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM django_migrations")
                    applied = cursor.fetchone()[0]
                # Sanity check: we actually migrated the empty DB, not a no-op
                # against the shared test database.
                self.assertGreater(applied, 50)
        finally:
            connections.close_all()
            _drop_database(_TEMP_DB_NAME)
            _point_default_connection_at(original_name)
