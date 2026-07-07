"""geventpool with bounded connection lifetime.

django-db-geventpool keeps warm connections open indefinitely. psycopg3 accumulates
cache on long-lived handles. We close and replace after
CONN_MAX_LIFETIME rather than recycling uWSGI workers, which would interrupt
live stream backends.

Leak reaper
-----------
The upstream pool only evaluates connection age inside ``get()``/``put()``. A
connection checked out by a greenlet that dies without returning it (e.g. a live
stream / channel-switch teardown path that never calls ``close_old_connections()``)
is therefore never aged out: it stays counted against ``maxsize`` but is no longer
in the free queue, so once ``maxsize`` connections leak the pool blocks forever in
``get()`` and every DB-backed request on that worker hangs (Dispatcharr #1418).

To close that gap we run a background greenlet that periodically closes connections
which are both **expired** (older than ``max_lifetime``) **and IDLE** (no in-flight
transaction). An IDLE+expired connection that is not being handed back is a leaked
one; reaping it discards it from the (weak) connection set, which frees the slot.
The IDLE guard guarantees we never close a connection that is mid-query, so an
active stream or in-flight request is never disrupted. This also makes
``DATABASE_POOL_CONN_MAX_LIFETIME`` actually effective against leaked connections
(lower it to reclaim leaked slots faster).
"""
import logging
import os
import time

try:
    from gevent import queue
except ImportError:
    from eventlet import queue

try:
    from psycopg.pq import TransactionStatus as _TxnStatus
    _IDLE = _TxnStatus.IDLE
except Exception:  # pragma: no cover - psycopg always present in prod
    _IDLE = None

from django_db_geventpool.backends.pool import DatabaseConnectionPool as BasePool

logger = logging.getLogger("django.geventpool")

# How often the leak reaper runs, in seconds. Reaping only closes connections
# already older than max_lifetime, so a leaked slot is reclaimed within
# ~(max_lifetime + this interval). Set 0 to disable the reaper.
_REAP_INTERVAL = int(os.environ.get("DATABASE_POOL_REAP_INTERVAL", "30"))


class DatabaseConnectionPool(BasePool):
    def __init__(self, maxsize: int = 100, reuse: int = 100, max_lifetime: float | None = None):
        super().__init__(maxsize, reuse)
        self.max_lifetime = max_lifetime
        self._reaper_started = False

    def _ensure_reaper(self) -> None:
        """Start the background leak reaper once, lazily (so the gevent hub is up)."""
        if self._reaper_started or not self.max_lifetime or not _REAP_INTERVAL or _IDLE is None:
            return
        try:
            import gevent
        except ImportError:
            self._reaper_started = True  # not running under gevent; nothing to do
            return
        self._reaper_started = True
        gevent.spawn(self._reaper_loop)
        logger.info(
            "DB pool leak reaper started (interval=%ss, max_lifetime=%ss)",
            _REAP_INTERVAL,
            int(self.max_lifetime),
        )

    def _reaper_loop(self) -> None:
        import gevent

        while True:
            try:
                gevent.sleep(_REAP_INTERVAL)
                self._reap_leaked_connections()
            except Exception:  # never let the reaper greenlet die
                logger.debug("DB pool reaper iteration failed", exc_info=True)

    def _reap_leaked_connections(self) -> None:
        """Close expired connections that are sitting IDLE (leaked, never returned).

        Never closes a connection with an active transaction, so an in-flight
        request or stream is never disrupted. ``get()`` already refuses to hand
        out an expired connection, so an expired IDLE connection cannot be in
        active use by a live greenlet.
        """
        if not self.max_lifetime or _IDLE is None:
            return
        reaped = 0
        for conn in list(self._conns):
            try:
                if not self._connection_expired(conn):
                    continue
                if conn.info.transaction_status != _IDLE:
                    continue  # mid-transaction: in use, leave it alone
                self._close_connection(conn)
                reaped += 1
            except Exception:
                logger.debug("Error reaping DB connection", exc_info=True)
        if reaped:
            logger.info(
                "DB pool reaper closed %d expired/leaked idle connection(s); "
                "size now %d/%d",
                reaped,
                self.size,
                self.maxsize,
            )

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
        self._ensure_reaper()
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
