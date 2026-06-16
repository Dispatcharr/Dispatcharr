"""Tests for dispatcharr geventpool connection max lifetime."""
from unittest import TestCase
from unittest.mock import MagicMock, patch

from dispatcharr.db.backends.postgresql_psycopg3.pool import DatabaseConnectionPool


class _TestPool(DatabaseConnectionPool):
    DBERROR = Exception

    def create_connection(self):
        return MagicMock(name="connection", closed=False)

    def check_usable(self, connection):
        return None


class GeventPoolConnLifetimeTests(TestCase):
    def test_fresh_connection_is_stamped_on_create(self):
        pool = _TestPool(maxsize=2, reuse=2, max_lifetime=3600)
        conn = pool.get()
        self.assertIsNotNone(getattr(conn, "_dispatcharr_pool_created_at", None))

    def test_expired_connection_on_get_is_replaced(self):
        pool = _TestPool(maxsize=2, reuse=2, max_lifetime=60)
        conn = pool.create_connection()
        pool._stamp_connection(conn)
        conn._dispatcharr_pool_created_at = 0
        conn.close = MagicMock()
        pool._conns.add(conn)
        pool.pool.put_nowait(conn)

        with patch("dispatcharr.db.backends.postgresql_psycopg3.pool.time.monotonic", return_value=120):
            new_conn = pool.get()

        conn.close.assert_called_once()
        self.assertIsNot(new_conn, conn)

    def test_expired_connection_on_put_is_closed_not_pooled(self):
        pool = _TestPool(maxsize=2, reuse=2, max_lifetime=60)
        conn = pool.get()
        conn.close = MagicMock()
        conn._dispatcharr_pool_created_at = 0

        with patch("dispatcharr.db.backends.postgresql_psycopg3.pool.time.monotonic", return_value=120):
            pool.put(conn)

        conn.close.assert_called_once()
        self.assertEqual(pool.pool.qsize(), 0)

    def test_non_expired_connection_is_returned_to_pool(self):
        pool = _TestPool(maxsize=2, reuse=2, max_lifetime=3600)
        conn = pool.get()
        pool.put(conn)
        self.assertEqual(pool.pool.qsize(), 1)

    def test_max_lifetime_disabled_when_none(self):
        pool = _TestPool(maxsize=2, reuse=2, max_lifetime=None)
        conn = pool.get()
        conn._dispatcharr_pool_created_at = 0

        with patch("dispatcharr.db.backends.postgresql_psycopg3.pool.time.monotonic", return_value=999999):
            pool.put(conn)

        self.assertEqual(pool.pool.qsize(), 1)
