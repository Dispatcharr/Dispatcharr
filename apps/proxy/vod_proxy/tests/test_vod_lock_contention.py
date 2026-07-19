"""
Tests for atomic VOD active_streams accounting.

active_streams is mutated via Redis Lua (HINCRBY / conditional DECR), not the
session metadata lock. These tests simulate multi-worker Jellyfin-style range
request churn: metadata lock held while another worker tears down, concurrent
DECRs, and metadata saves that must not clobber the counter.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from django.test import SimpleTestCase


class LockAwareFakeRedis:
    """In-memory Redis with SET NX, hashes, and VOD Lua script shims."""

    def __init__(self):
        self._data = {}
        self._hashes = {}
        self._lock = threading.Lock()

    def set(self, key, value, nx=False, ex=None):
        with self._lock:
            if nx and key in self._data:
                return False
            self._data[key] = value
            return True

    def get(self, key):
        with self._lock:
            val = self._data.get(key)
            if val is None:
                return None
            return str(val)

    def delete(self, *keys):
        with self._lock:
            deleted = 0
            for key in keys:
                if key in self._data:
                    del self._data[key]
                    deleted += 1
                if key in self._hashes:
                    del self._hashes[key]
                    deleted += 1
            return deleted

    def exists(self, key):
        with self._lock:
            return int(key in self._data or key in self._hashes)

    def incr(self, key):
        with self._lock:
            self._data[key] = int(self._data.get(key, 0)) + 1
            return self._data[key]

    def decr(self, key):
        with self._lock:
            self._data[key] = int(self._data.get(key, 0)) - 1
            return self._data[key]

    def hset(self, key, mapping=None, **kwargs):
        with self._lock:
            if key not in self._hashes:
                self._hashes[key] = {}
            if mapping:
                for k, v in mapping.items():
                    self._hashes[key][str(k)] = str(v)
            # field/value form: hset(key, field, value) via redis-py kwargs uncommon;
            # support positional through mapping only.
            return True

    def hget(self, key, field):
        with self._lock:
            return self._hashes.get(key, {}).get(str(field))

    def hgetall(self, key):
        with self._lock:
            return dict(self._hashes.get(key, {}))

    def hincrby(self, key, field, amount=1):
        with self._lock:
            if key not in self._hashes:
                self._hashes[key] = {}
            cur = int(self._hashes[key].get(str(field), 0))
            cur += int(amount)
            self._hashes[key][str(field)] = str(cur)
            return cur

    def expire(self, key, seconds):
        return True

    def pipeline(self):
        return _FakePipeline(self)

    def register_script(self, script):
        return _FakeVodScript(self, script)


class _FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._cmds = []

    def delete(self, *keys):
        self._cmds.append(("delete", keys))
        return self

    def execute(self):
        results = []
        for cmd, args in self._cmds:
            if cmd == "delete":
                results.append(self._redis.delete(*args))
        self._cmds = []
        return results


class _FakeVodScript:
    """Python stand-in for VOD Lua scripts (atomic under threading.Lock)."""

    def __init__(self, redis: LockAwareFakeRedis, script: str):
        self._redis = redis
        self._script = script

    def __call__(self, keys=None, args=None):
        keys = keys or []
        args = args or []
        with self._redis._lock:
            if "vod_incr_as" in self._script:
                return self._incr(keys[0], args[0])
            if "vod_decr_as" in self._script:
                return self._decr(keys[0], args[0])
            if "vod_cleanup_idle" in self._script:
                return self._cleanup(keys[0])
            if "vod_meta_save_if_exists" in self._script:
                return self._meta_save(keys[0], args)
            raise AssertionError(f"Unknown VOD script: {self._script[:80]}")

    def _incr(self, key, activity):
        if key not in self._redis._hashes:
            return 0
        h = self._redis._hashes[key]
        new_count = int(h.get("active_streams", 0)) + 1
        h["active_streams"] = str(new_count)
        h["last_activity"] = str(activity)
        return new_count

    def _decr(self, key, activity):
        if key not in self._redis._hashes:
            return [-1, 0]
        h = self._redis._hashes[key]
        current = int(h.get("active_streams", 0))
        if current <= 0:
            return [0, 0]
        new_count = current - 1
        h["active_streams"] = str(new_count)
        h["last_activity"] = str(activity)
        return [1, new_count]

    def _cleanup(self, conn_key, lock_key=None):
        if conn_key not in self._redis._hashes:
            return 1
        current = int(self._redis._hashes[conn_key].get("active_streams", 0))
        if current > 0:
            return 0
        del self._redis._hashes[conn_key]
        return 1

    def _meta_save(self, key, args):
        if key not in self._redis._hashes:
            return 0
        # args[0] = ttl; args[1..] = field, value pairs
        h = self._redis._hashes[key]
        for i in range(1, len(args), 2):
            if i + 1 >= len(args):
                break
            h[str(args[i])] = str(args[i + 1])
        return 1


def _clear_script_cache():
    from apps.proxy.vod_proxy import multi_worker_connection_manager as mod

    mod._vod_script_cache.clear()


def _import_vod():
    import sys

    for mod in ["apps.vod.models", "apps.m3u.models", "core.utils"]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    from apps.proxy.vod_proxy.multi_worker_connection_manager import (
        RedisBackedVODConnection,
        SerializableConnectionState,
    )

    return RedisBackedVODConnection, SerializableConnectionState


def _seed_session(redis, session_id, active_streams=1, profile_id=7):
    RedisBackedVODConnection, SerializableConnectionState = _import_vod()
    _clear_script_cache()
    conn = RedisBackedVODConnection(session_id, redis)
    state = SerializableConnectionState(
        session_id=session_id,
        stream_url="http://example.com/movie.mkv",
        headers={},
        m3u_profile_id=profile_id,
    )
    state.active_streams = active_streams
    state.content_obj_type = "movie"
    state.content_uuid = "abc-123"
    state.content_name = "Test Movie"
    state.worker_id = "worker-a"
    assert conn._save_connection_state(state, include_active_streams=True)
    return conn


class TestAtomicActiveStreams(SimpleTestCase):
    def test_incr_decr_round_trip(self):
        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        _seed_session(redis, "vod_sym", active_streams=0)
        a = RedisBackedVODConnection("vod_sym", redis)
        b = RedisBackedVODConnection("vod_sym", redis)

        self.assertEqual(a.increment_active_streams(), 1)
        self.assertEqual(b.increment_active_streams(), 2)

        ok_b, rem_b = b.decrement_active_streams_and_check()
        ok_a, rem_a = a.decrement_active_streams_and_check()
        self.assertTrue(ok_b and rem_b)
        self.assertTrue(ok_a and not rem_a)
        self.assertEqual(a.get_active_streams_count(), 0)

    def test_decr_succeeds_while_session_metadata_lock_held(self):
        """Teardown must not depend on the session metadata lock."""
        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        holder = _seed_session(redis, "vod_lock_held", active_streams=1)
        waiter = RedisBackedVODConnection("vod_lock_held", redis)

        self.assertTrue(holder._acquire_lock())
        try:
            success, has_remaining = waiter.decrement_active_streams_and_check()
            self.assertEqual((success, has_remaining), (True, False))
            self.assertEqual(waiter.get_active_streams_count(), 0)
        finally:
            holder._release_lock()

    def test_metadata_save_does_not_clobber_active_streams(self):
        RedisBackedVODConnection, SerializableConnectionState = _import_vod()
        redis = LockAwareFakeRedis()
        conn = _seed_session(redis, "vod_clobber", active_streams=0)
        self.assertEqual(conn.increment_active_streams(), 1)
        self.assertEqual(conn.increment_active_streams(), 2)

        # Stale in-memory state still has active_streams=0 from seed
        stale = conn._get_connection_state()
        stale.active_streams = 0
        stale.worker_id = "worker-b"
        conn._save_connection_state(stale)  # include_active_streams=False

        self.assertEqual(conn.get_active_streams_count(), 2)
        reloaded = conn._get_connection_state()
        self.assertEqual(reloaded.worker_id, "worker-b")
        self.assertEqual(reloaded.active_streams, 2)

    def test_decr_at_zero_does_not_go_negative(self):
        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        conn = _seed_session(redis, "vod_zero", active_streams=0)

        success, has_remaining = conn.decrement_active_streams_and_check()
        self.assertEqual((success, has_remaining), (False, False))
        self.assertEqual(conn.get_active_streams_count(), 0)

    def test_multi_worker_concurrent_teardown_balances_to_zero(self):
        """Jellyfin-style: AS=2, two workers DECR concurrently under lock churn."""
        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        _seed_session(redis, "vod_multi", active_streams=2)

        worker_a = RedisBackedVODConnection("vod_multi", redis)
        worker_b = RedisBackedVODConnection("vod_multi", redis)
        interferer = RedisBackedVODConnection("vod_multi", redis)

        results = []
        barrier = threading.Barrier(2)

        def churn_metadata_lock():
            for _ in range(8):
                if interferer._acquire_lock():
                    # Simulate ownership transfer / seek metadata write
                    state = interferer._get_connection_state()
                    if state:
                        state.last_activity = time.time()
                        interferer._save_connection_state(state)
                    interferer._release_lock()
                time.sleep(0.001)

        def teardown(worker):
            barrier.wait()
            results.append(worker.decrement_active_streams_and_check())

        t_churn = threading.Thread(target=churn_metadata_lock, daemon=True)
        t_a = threading.Thread(target=teardown, args=(worker_a,))
        t_b = threading.Thread(target=teardown, args=(worker_b,))
        t_churn.start()
        t_a.start()
        t_b.start()
        t_a.join(timeout=5)
        t_b.join(timeout=5)
        t_churn.join(timeout=5)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(success for success, _ in results))
        self.assertEqual(sorted(has for _, has in results), [False, True])
        self.assertEqual(worker_a.get_active_streams_count(), 0)

    def test_cleanup_skips_when_active_streams_present(self):
        redis = LockAwareFakeRedis()
        conn = _seed_session(redis, "vod_clean_busy", active_streams=1)
        conn.cleanup()
        self.assertIsNotNone(conn._get_connection_state())
        self.assertEqual(conn.get_active_streams_count(), 1)

    def test_cleanup_deletes_when_idle(self):
        redis = LockAwareFakeRedis()
        conn = _seed_session(redis, "vod_clean_idle", active_streams=0)
        conn.cleanup()
        self.assertIsNone(conn._get_connection_state())

    def test_cleanup_does_not_delete_metadata_lock(self):
        """Idle cleanup must not steal the metadata lock from a holder."""
        redis = LockAwareFakeRedis()
        holder = _seed_session(redis, "vod_lock_keep", active_streams=0)
        self.assertTrue(holder._acquire_lock())
        try:
            holder.cleanup()
            # Session hash gone, but lock still held by this worker
            self.assertIsNone(holder._get_connection_state())
            self.assertTrue(redis.exists(holder.lock_key))
            # Holder can still release cleanly
        finally:
            holder._release_lock()
        self.assertFalse(redis.exists(holder.lock_key))

    def test_unconditional_hset_after_cleanup_recreates_zombie(self):
        """Reproduce: plain HSET after idle cleanup recreates a session hash."""
        redis = LockAwareFakeRedis()
        holder = _seed_session(redis, "vod_zombie_raw", active_streams=0)
        stale = holder._get_connection_state()
        self.assertTrue(holder._acquire_lock())
        try:
            holder.cleanup()
            self.assertIsNone(holder._get_connection_state())

            # Bypass the exists-guard (old metadata save behavior)
            data = stale.to_dict()
            data.pop("active_streams", None)
            redis.hset(holder.connection_key, mapping=data)

            zombie = holder._get_connection_state()
            self.assertIsNotNone(zombie)
            # Recreated without a reliable counter field from Lua INCR/DECR era
            self.assertFalse(holder.has_active_streams())
        finally:
            holder._release_lock()

    def test_metadata_save_after_cleanup_does_not_recreate_zombie(self):
        """Fixed path: metadata save is a no-op if cleanup already deleted the hash."""
        redis = LockAwareFakeRedis()
        holder = _seed_session(redis, "vod_zombie_fix", active_streams=0)
        stale = holder._get_connection_state()
        stale.worker_id = "worker-late"
        stale.last_activity = time.time()

        self.assertTrue(holder._acquire_lock())
        try:
            holder.cleanup()
            self.assertIsNone(holder._get_connection_state())

            saved = holder._save_connection_state(stale)
            self.assertFalse(saved)
            self.assertIsNone(holder._get_connection_state())
            self.assertNotIn(holder.connection_key, redis._hashes)
        finally:
            holder._release_lock()

    def test_create_save_still_creates_new_session(self):
        """include_active_streams=True must still be able to create a missing key."""
        RedisBackedVODConnection, SerializableConnectionState = _import_vod()
        _clear_script_cache()
        redis = LockAwareFakeRedis()
        conn = RedisBackedVODConnection("vod_create_new", redis)
        state = SerializableConnectionState(
            session_id="vod_create_new",
            stream_url="http://example.com/movie.mkv",
            headers={},
            m3u_profile_id=7,
        )
        self.assertTrue(conn._save_connection_state(state, include_active_streams=True))
        self.assertIsNotNone(conn._get_connection_state())
        self.assertEqual(conn.get_active_streams_count(), 0)

    def test_cleanup_atomic_vs_reconnect_incr(self):
        """If INCR wins the race, cleanup must not delete the session."""
        redis = LockAwareFakeRedis()
        conn = _seed_session(redis, "vod_race", active_streams=0)

        # Reconnect increments before cleanup Lua runs
        self.assertEqual(conn.increment_active_streams(), 1)
        conn.cleanup()
        self.assertEqual(conn.get_active_streams_count(), 1)
        self.assertIsNotNone(conn._get_connection_state())


class TestLegacyLockContentionBehaviorGone(SimpleTestCase):
    """Document that the old lock-gated DECR orphan path no longer exists."""

    def test_old_no_retry_orphan_scenario_no_longer_orphans(self):
        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        holder = _seed_session(redis, "vod_orphan_old", active_streams=1)
        other = RedisBackedVODConnection("vod_orphan_old", redis)

        self.assertTrue(holder._acquire_lock())
        success, has_remaining = other.decrement_active_streams_and_check()
        holder._release_lock()

        # Previously: (False, True) with active_streams left at 1
        self.assertEqual((success, has_remaining), (True, False))
        self.assertEqual(other.get_active_streams_count(), 0)


class TestVodActiveStreamsRealRedis(SimpleTestCase):
    """Integration tests against a live Redis (real Lua EVALSHA).

    FakeRedis covers fast unit cases; this class verifies the registered
    scripts behave correctly on the Redis server used in CI/dev.
    """

    redis = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            from core.utils import RedisClient

            client = RedisClient.get_client(max_retries=1, retry_interval=0)
            if client is not None and client.ping():
                cls.redis = client
        except Exception:
            cls.redis = None

    def setUp(self):
        if self.redis is None:
            self.skipTest("Redis not available")
        import uuid

        from apps.proxy.vod_proxy import multi_worker_connection_manager as mod

        mod._vod_script_cache.clear()
        self.session_id = f"test_vod_lua_{uuid.uuid4().hex}"
        self._keys_to_delete = []

    def tearDown(self):
        if self.redis is None:
            return
        RedisBackedVODConnection, _ = _import_vod()
        conn = RedisBackedVODConnection(self.session_id, self.redis)
        keys = [conn.connection_key, conn.lock_key, *self._keys_to_delete]
        if keys:
            self.redis.delete(*keys)
        from apps.proxy.vod_proxy import multi_worker_connection_manager as mod

        mod._vod_script_cache.clear()

    def _seed(self, active_streams=1):
        RedisBackedVODConnection, SerializableConnectionState = _import_vod()
        conn = RedisBackedVODConnection(self.session_id, self.redis)
        state = SerializableConnectionState(
            session_id=self.session_id,
            stream_url="http://example.com/movie.mkv",
            headers={"User-Agent": "test"},
            m3u_profile_id=7,
        )
        state.active_streams = active_streams
        state.worker_id = "real-redis-worker"
        self.assertTrue(conn._save_connection_state(state, include_active_streams=True))
        return conn

    def test_real_lua_incr_decr_round_trip(self):
        RedisBackedVODConnection, _ = _import_vod()
        a = self._seed(active_streams=0)
        b = RedisBackedVODConnection(self.session_id, self.redis)

        self.assertEqual(a.increment_active_streams(), 1)
        self.assertEqual(b.increment_active_streams(), 2)
        self.assertEqual(int(self.redis.hget(a.connection_key, "active_streams")), 2)

        ok_b, rem_b = b.decrement_active_streams_and_check()
        ok_a, rem_a = a.decrement_active_streams_and_check()
        self.assertTrue(ok_b and rem_b)
        self.assertTrue(ok_a and not rem_a)
        self.assertEqual(int(self.redis.hget(a.connection_key, "active_streams")), 0)

    def test_real_lua_decr_while_metadata_lock_held(self):
        RedisBackedVODConnection, _ = _import_vod()
        holder = self._seed(active_streams=1)
        waiter = RedisBackedVODConnection(self.session_id, self.redis)

        self.assertTrue(holder._acquire_lock())
        try:
            success, has_remaining = waiter.decrement_active_streams_and_check()
            self.assertEqual((success, has_remaining), (True, False))
            self.assertEqual(int(self.redis.hget(holder.connection_key, "active_streams")), 0)
        finally:
            holder._release_lock()

    def test_real_lua_metadata_save_does_not_recreate_after_cleanup(self):
        holder = self._seed(active_streams=0)
        stale = holder._get_connection_state()
        stale.worker_id = "late-writer"

        self.assertTrue(holder._acquire_lock())
        try:
            holder.cleanup()
            self.assertFalse(bool(self.redis.exists(holder.connection_key)))

            saved = holder._save_connection_state(stale)
            self.assertFalse(saved)
            self.assertFalse(bool(self.redis.exists(holder.connection_key)))
        finally:
            holder._release_lock()

    def test_real_lua_cleanup_skips_when_active(self):
        conn = self._seed(active_streams=1)
        conn.cleanup()
        self.assertTrue(bool(self.redis.exists(conn.connection_key)))
        self.assertEqual(int(self.redis.hget(conn.connection_key, "active_streams")), 1)

    def test_real_lua_concurrent_decr_under_metadata_churn(self):
        RedisBackedVODConnection, _ = _import_vod()
        self._seed(active_streams=2)
        worker_a = RedisBackedVODConnection(self.session_id, self.redis)
        worker_b = RedisBackedVODConnection(self.session_id, self.redis)
        interferer = RedisBackedVODConnection(self.session_id, self.redis)

        results = []
        barrier = threading.Barrier(2)

        def churn():
            for _ in range(10):
                if interferer._acquire_lock():
                    state = interferer._get_connection_state()
                    if state:
                        state.last_activity = time.time()
                        interferer._save_connection_state(state)
                    interferer._release_lock()
                time.sleep(0.001)

        def teardown(worker):
            barrier.wait()
            results.append(worker.decrement_active_streams_and_check())

        threads = [
            threading.Thread(target=churn, daemon=True),
            threading.Thread(target=teardown, args=(worker_a,)),
            threading.Thread(target=teardown, args=(worker_b,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(success for success, _ in results))
        self.assertEqual(sorted(has for _, has in results), [False, True])
        self.assertEqual(int(self.redis.hget(worker_a.connection_key, "active_streams")), 0)

    def test_real_lua_scripts_are_registered_as_evalsha(self):
        """Smoke-check redis-py Script objects hit the live server."""
        conn = self._seed(active_streams=0)
        scripts = conn._vod_scripts()
        for name in ("incr", "decr", "cleanup", "meta_save"):
            self.assertIn(name, scripts)
            # Calling Script triggers SCRIPT LOAD / EVALSHA on first use
            self.assertTrue(hasattr(scripts[name], "sha") or callable(scripts[name]))

        self.assertEqual(conn.increment_active_streams(), 1)
        # After first call, sha should be populated on redis-py Script
        incr_script = scripts["incr"]
        sha = getattr(incr_script, "sha", None)
        self.assertTrue(sha, "Expected redis-py Script.sha after EVALSHA")
