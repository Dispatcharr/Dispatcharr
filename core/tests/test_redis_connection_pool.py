"""Redis client pools must stay bounded under concurrent waiters."""

import threading
import time

from django.test import SimpleTestCase, override_settings
from redis.connection import BlockingConnectionPool

from core.utils import RedisClient


def _live_sock_count(pool):
    n = 0
    for conn in getattr(pool, "_connections", []) or []:
        if getattr(conn, "_sock", None) is not None:
            n += 1
    return n


class RedisConnectionPoolTests(SimpleTestCase):
    def tearDown(self):
        RedisClient._client = None
        RedisClient._buffer = None
        RedisClient._pubsub_client = None

    @override_settings(REDIS_MAX_CONNECTIONS=7, REDIS_POOL_TIMEOUT=2.0)
    def test_make_client_uses_bounded_blocking_pool(self):
        client = RedisClient._make_client(decode_responses=True)
        pool = client.connection_pool
        self.assertIsInstance(pool, BlockingConnectionPool)
        self.assertEqual(pool.max_connections, 7)

    @override_settings(REDIS_MAX_CONNECTIONS=5, REDIS_POOL_TIMEOUT=5.0)
    def test_burst_does_not_exceed_max_connections(self):
        """Hold pool slots concurrently; warm sockets must stay at or under the cap."""
        client = RedisClient._make_client(decode_responses=True)
        pool = client.connection_pool
        self.assertEqual(pool.max_connections, 5)

        errors = []
        in_use_peak = [0]
        lock = threading.Lock()
        active = [0]

        def hold(_i):
            try:
                conn = pool.get_connection()
                with lock:
                    active[0] += 1
                    if active[0] > in_use_peak[0]:
                        in_use_peak[0] = active[0]
                try:
                    conn.send_command("PING")
                    conn.read_response()
                    time.sleep(0.05)
                finally:
                    with lock:
                        active[0] -= 1
                    pool.release(conn)
            except Exception as exc:  # pragma: no cover - surfaced via errors
                errors.append(exc)

        threads = [threading.Thread(target=hold, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertLessEqual(in_use_peak[0], 5)
        self.assertLessEqual(_live_sock_count(pool), 5)
