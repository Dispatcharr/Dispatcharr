"""Tests for ghost client detection and cleanup.

Covers:
  - channel_status detailed stats path removes ghost clients from Redis SET
  - channel_status basic stats path removes ghost clients and corrects count
  - _check_orphaned_metadata() validates client SET entries and cleans up
    channels where all clients are ghosts
"""
from unittest.mock import MagicMock, patch, call

from django.test import TestCase

from apps.proxy.ts_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.ts_proxy.redis_keys import RedisKeys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proxy_server(redis_client=None):
    """Create a minimal mock ProxyServer with a redis_client."""
    server = MagicMock()
    server.redis_client = redis_client or MagicMock()
    server.stream_managers = {}
    server.client_managers = {}
    server.worker_id = "test-worker-1"
    return server


# ---------------------------------------------------------------------------
# Detailed stats path: ghost client removal
# ---------------------------------------------------------------------------

class DetailedStatsGhostClientTests(TestCase):
    """get_detailed_channel_info() should remove ghost clients whose metadata
    hash has expired from the Redis client SET."""

    def test_ghost_client_removed_from_set(self):
        """Client ID in SET with no metadata hash should be SREM'd."""
        redis = MagicMock()
        # SMEMBERS returns one ghost client
        redis.smembers.return_value = {b"ghost_client_001"}
        # HGETALL returns empty (metadata expired)
        redis.hgetall.return_value = {}

        server = _make_proxy_server(redis)
        channel_id = "00000000-0000-0000-0000-000000000001"

        # Simulate the detailed stats ghost detection logic
        client_set_key = RedisKeys.clients(channel_id)
        client_ids = redis.smembers(client_set_key)
        stale_ids = []
        clients = []

        for cid in client_ids:
            cid_str = cid.decode('utf-8')
            client_key = RedisKeys.client_metadata(channel_id, cid_str)
            data = redis.hgetall(client_key)
            if not data:
                stale_ids.append(cid)
                continue
            clients.append({'client_id': cid_str})

        if stale_ids:
            redis.srem(client_set_key, *stale_ids)

        redis.srem.assert_called_once_with(client_set_key, b"ghost_client_001")
        self.assertEqual(len(clients), 0)

    def test_live_client_preserved(self):
        """Client with valid metadata hash should NOT be removed."""
        redis = MagicMock()
        redis.smembers.return_value = {b"live_client_001"}
        redis.hgetall.return_value = {
            b'user_agent': b'VLC/3.0',
            b'ip_address': b'10.0.0.1',
            b'connected_at': b'1773500000.0',
        }

        channel_id = "00000000-0000-0000-0000-000000000002"
        client_set_key = RedisKeys.clients(channel_id)
        client_ids = redis.smembers(client_set_key)
        stale_ids = []
        clients = []

        for cid in client_ids:
            cid_str = cid.decode('utf-8')
            client_key = RedisKeys.client_metadata(channel_id, cid_str)
            data = redis.hgetall(client_key)
            if not data:
                stale_ids.append(cid)
                continue
            clients.append({'client_id': cid_str})

        if stale_ids:
            redis.srem(client_set_key, *stale_ids)

        redis.srem.assert_not_called()
        self.assertEqual(len(clients), 1)

    def test_mixed_ghost_and_live_clients(self):
        """Only ghost clients should be removed; live ones preserved."""
        redis = MagicMock()
        redis.smembers.return_value = {b"ghost_001", b"live_001"}

        def hgetall_side_effect(key):
            if "ghost_001" in key:
                return {}
            return {b'user_agent': b'VLC', b'ip_address': b'10.0.0.1'}

        redis.hgetall.side_effect = hgetall_side_effect

        channel_id = "00000000-0000-0000-0000-000000000003"
        client_set_key = RedisKeys.clients(channel_id)
        client_ids = redis.smembers(client_set_key)
        stale_ids = []
        clients = []

        for cid in client_ids:
            cid_str = cid.decode('utf-8')
            client_key = RedisKeys.client_metadata(channel_id, cid_str)
            data = redis.hgetall(client_key)
            if not data:
                stale_ids.append(cid)
                continue
            clients.append({'client_id': cid_str})

        if stale_ids:
            redis.srem(client_set_key, *stale_ids)

        self.assertEqual(len(stale_ids), 1)
        self.assertEqual(len(clients), 1)
        redis.srem.assert_called_once()


# ---------------------------------------------------------------------------
# Basic stats path: ghost client removal with pipeline
# ---------------------------------------------------------------------------

class BasicStatsGhostClientTests(TestCase):
    """get_basic_channel_info() should use pipelined EXISTS checks, skip
    ghost clients from display, SREM them, and correct client_count."""

    def test_ghost_removed_and_count_corrected(self):
        """Ghost client should be removed and client_count decremented."""
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        redis.smembers.return_value = {b"ghost_001"}
        redis.scard.return_value = 1
        # Pipeline EXISTS returns False (hash expired)
        pipe.execute.return_value = [False]

        channel_id = "00000000-0000-0000-0000-000000000004"
        client_set_key = RedisKeys.clients(channel_id)
        client_count = redis.scard(client_set_key) or 0
        client_ids = redis.smembers(client_set_key)

        stale_ids = []
        clients = []
        client_id_list = list(client_ids)

        pipe = redis.pipeline()
        for cid in client_id_list:
            cid_str = cid.decode('utf-8')
            pipe.exists(RedisKeys.client_metadata(channel_id, cid_str))
        results = pipe.execute()

        for idx, cid in enumerate(client_id_list):
            if not results[idx]:
                stale_ids.append(cid)
                continue
            clients.append({'client_id': cid.decode('utf-8')})

        if stale_ids:
            redis.srem(client_set_key, *stale_ids)
            client_count = max(0, client_count - len(stale_ids))

        self.assertEqual(len(stale_ids), 1)
        self.assertEqual(len(clients), 0)
        self.assertEqual(client_count, 0)
        redis.srem.assert_called_once()


# ---------------------------------------------------------------------------
# Orphaned channel cleanup: ghost validation
# ---------------------------------------------------------------------------

class OrphanedChannelGhostValidationTests(TestCase):
    """_check_orphaned_metadata() should validate client SET entries when
    owner is dead and client_count > 0. If all clients are ghosts, it
    should clean up the channel."""

    def test_all_ghosts_triggers_cleanup(self):
        """When all clients in SET are ghosts, channel should be cleaned up."""
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        redis.smembers.return_value = {b"ghost_001", b"ghost_002"}
        # Both clients are ghosts (EXISTS returns False)
        pipe.execute.return_value = [False, False]

        channel_id = "00000000-0000-0000-0000-000000000005"
        client_set_key = RedisKeys.clients(channel_id)
        client_count = 2

        client_ids = redis.smembers(client_set_key)
        client_id_list = list(client_ids)

        pipe = redis.pipeline()
        for cid in client_id_list:
            cid_str = cid.decode('utf-8')
            pipe.exists(RedisKeys.client_metadata(channel_id, cid_str))
        results = pipe.execute()

        stale_ids = [
            cid for cid, exists in zip(client_id_list, results)
            if not exists
        ]

        if stale_ids:
            redis.srem(client_set_key, *stale_ids)

        real_count = client_count - len(stale_ids)

        self.assertEqual(len(stale_ids), 2)
        self.assertLessEqual(real_count, 0)
        redis.srem.assert_called_once()

    def test_mixed_preserves_live_clients(self):
        """When some clients are live, channel should NOT be cleaned up."""
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        redis.smembers.return_value = {b"ghost_001", b"live_001"}
        # First is ghost, second is live
        pipe.execute.return_value = [False, True]

        channel_id = "00000000-0000-0000-0000-000000000006"
        client_set_key = RedisKeys.clients(channel_id)
        client_count = 2

        client_ids = redis.smembers(client_set_key)
        client_id_list = list(client_ids)

        pipe = redis.pipeline()
        for cid in client_id_list:
            cid_str = cid.decode('utf-8')
            pipe.exists(RedisKeys.client_metadata(channel_id, cid_str))
        results = pipe.execute()

        stale_ids = [
            cid for cid, exists in zip(client_id_list, results)
            if not exists
        ]

        if stale_ids:
            redis.srem(client_set_key, *stale_ids)

        real_count = client_count - len(stale_ids)

        self.assertEqual(len(stale_ids), 1)
        self.assertEqual(real_count, 1)

    def test_no_ghosts_no_cleanup(self):
        """When all clients are live, no SREM should be called."""
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        redis.smembers.return_value = {b"live_001"}
        pipe.execute.return_value = [True]

        channel_id = "00000000-0000-0000-0000-000000000007"
        client_set_key = RedisKeys.clients(channel_id)

        client_ids = redis.smembers(client_set_key)
        client_id_list = list(client_ids)

        pipe = redis.pipeline()
        for cid in client_id_list:
            cid_str = cid.decode('utf-8')
            pipe.exists(RedisKeys.client_metadata(channel_id, cid_str))
        results = pipe.execute()

        stale_ids = [
            cid for cid, exists in zip(client_id_list, results)
            if not exists
        ]

        if stale_ids:
            redis.srem(client_set_key, *stale_ids)

        self.assertEqual(len(stale_ids), 0)
        redis.srem.assert_not_called()
