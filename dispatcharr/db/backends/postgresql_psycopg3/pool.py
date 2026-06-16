"""geventpool with bounded connection lifetime.

django-db-geventpool keeps warm connections open indefinitely. psycopg3 accumulates
cache on long-lived handles. We close and replace after
CONN_MAX_LIFETIME rather than recycling uWSGI workers, which would interrupt
live stream backends.
"""
import logging
import time

try:
    from gevent import queue
except ImportError:
    from eventlet import queue

from django_db_geventpool.backends.pool import DatabaseConnectionPool as BasePool

logger = logging.getLogger("django.geventpool")


class DatabaseConnectionPool(BasePool):
    def __init__(self, maxsize: int = 100, reuse: int = 100, max_lifetime: float | None = None):
        super().__init__(maxsize, reuse)
        self.max_lifetime = max_lifetime

    def _stamp_connection(self, conn) -> None:
        conn._dispatcharr_pool_created_at = time.monotonic()

    def _connection_expired(self, conn) -> bool:
        if not self.max_lifetime:
            return False
        created_at = getattr(conn, "_dispatcharr_pool_created_at", None)
        if created_at is None:
            return False
        return (time.monotonic() - created_at) >= self.max_lifetime

    def _close_connection(self, conn) -> None:
        try:
            conn.close()
        except Exception:
            logger.debug("Error closing pool connection", exc_info=True)
        finally:
            self._conns.discard(conn)

    def get(self):
        conn = None
        try:
            if self.size >= self.maxsize or self.pool.qsize():
                conn = self.pool.get()
            else:
                conn = self.pool.get_nowait()

            if conn is not None and self._connection_expired(conn):
                logger.debug(
                    "DB connection expired after %ss, replacing",
                    int(self.max_lifetime),
                )
                self._close_connection(conn)
                conn = None
            elif conn is not None:
                try:
                    self.check_usable(conn)
                    logger.trace("DB connection reused")
                except self.DBERROR:
                    logger.debug("DB connection was closed, creating a new one")
                    self._close_connection(conn)
                    conn = None
        except queue.Empty:
            conn = None
            logger.trace("DB connection queue empty, creating a new one")

        if conn is None:
            conn = self.create_connection()
            self._stamp_connection(conn)
            self._conns.add(conn)

        return conn

    def put(self, item):
        if self._connection_expired(item):
            logger.debug(
                "DB connection expired after %ss on return, closing",
                int(self.max_lifetime),
            )
            self._close_connection(item)
            return

        try:
            self.pool.put_nowait(item)
            logger.trace("DB connection returned to the pool")
        except queue.Full:
            self._close_connection(item)
