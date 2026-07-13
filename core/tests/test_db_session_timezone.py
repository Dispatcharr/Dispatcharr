"""DB sessions must run in UTC regardless of the server default timezone."""

import copy
import unittest

from django.db import connection, connections
from django.test import TestCase


@unittest.skipUnless(
    connection.vendor == "postgresql",
    "PostgreSQL-only: exercises the psycopg3 gevent pool backend",
)
class DatabaseSessionTimezoneTests(TestCase):
    def _pool_backend_wrapper(self):
        from dispatcharr.db.backends.postgresql_psycopg3.base import DatabaseWrapper

        settings_dict = copy.deepcopy(connections.databases["default"])
        settings_dict["ENGINE"] = "dispatcharr.db.backends.postgresql_psycopg3"
        settings_dict.setdefault("OPTIONS", {})
        return DatabaseWrapper(settings_dict, alias="tz_probe")

    @staticmethod
    def _teardown_wrapper(wrapper):
        wrapper.close()
        pool = wrapper._connection_pools.pop("tz_probe", None)
        if pool is not None:
            pool.close()

    def test_pool_session_timezone_pinned_to_utc(self):
        wrapper = self._pool_backend_wrapper()
        try:
            wrapper.connect()
            with wrapper.connection.cursor() as cursor:
                cursor.execute("SHOW TimeZone")
                self.assertEqual(cursor.fetchone()[0], "UTC")
        finally:
            self._teardown_wrapper(wrapper)

    def test_pool_session_timezone_is_session_default(self):
        wrapper = self._pool_backend_wrapper()
        try:
            wrapper.connect()
            with wrapper.connection.cursor() as cursor:
                cursor.execute("RESET TimeZone")
                cursor.execute("SHOW TimeZone")
                self.assertEqual(cursor.fetchone()[0], "UTC")
        finally:
            self._teardown_wrapper(wrapper)
