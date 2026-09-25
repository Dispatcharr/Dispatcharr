"""Redis client pools must stay bounded under concurrent waiters."""

import os
import threading
import time

from django.test import SimpleTestCase, override_settings
from redis.connection import BlockingConnectionPool

from core.utils import RedisClient
from unittest.mock import patch, MagicMock


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
    def test_init_client_uses_bounded_blocking_pool(self):

        client = RedisClient._init_client(decode_responses=True)
        pool = client.connection_pool
        self.assertIsInstance(pool, BlockingConnectionPool)
        self.assertEqual(pool.max_connections, 7)

        # Test REDIS_URL path too
        with patch.dict(os.environ, {"REDIS_URL":"redis://localhost:6379/0"}, clear=False):

            client = RedisClient._init_client(decode_responses=True)
            pool = client.connection_pool
            self.assertIsInstance(pool, BlockingConnectionPool)
            self.assertEqual(pool.max_connections, 7)

    @override_settings(REDIS_MAX_CONNECTIONS=5, REDIS_POOL_TIMEOUT=5.0)
    def test_burst_does_not_exceed_max_connections(self):
        """Hold pool slots concurrently; warm sockets must stay at or under the cap."""
        client = RedisClient._init_client(decode_responses=True)
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

    def test_client_instances_are_cached_singletons(self):
        """get_client, get_buffer, and get_pubsub_client must cache their instances."""
        with patch.object(RedisClient, '_init_client') as mock_init:
            mock_init.side_effect = [MagicMock(), MagicMock(), MagicMock()]

            c1 = RedisClient.get_client()
            c2 = RedisClient.get_client()
            self.assertIs(c1, c2)

            b1 = RedisClient.get_buffer()
            b2 = RedisClient.get_buffer()
            self.assertIs(b1, b2)

            p1 = RedisClient.get_pubsub_client()
            p2 = RedisClient.get_pubsub_client()
            self.assertIs(p1, p2)

            self.assertEqual(mock_init.call_count, 3)

    def test_malformed_redis_url_returns_none(self):
        """An unparseable query string in REDIS_URL must log and return None."""
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0?invalid_query=%%"}, clear=False):
            client = RedisClient._init_client(decode_responses=True)
            self.assertIsNone(client)
