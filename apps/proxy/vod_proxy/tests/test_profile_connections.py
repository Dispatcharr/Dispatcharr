"""
Tests for VOD proxy profile connection counter fixes.

Covers:
  1. Atomic active_streams DECR+check via Redis Lua (no session-lock gating)
  2. Non-atomic GET-then-DECR in _decrement_profile_connections() (counter could go negative)
"""

from unittest.mock import MagicMock, patch, call
from django.test import TestCase


class FakeRedis:
    """Minimal in-memory Redis stand-in for counter tests."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        val = self._data.get(key)
        return str(val).encode() if val is not None else None

    def set(self, key, value, ex=None):
        self._data[key] = int(value)

    def incr(self, key):
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    def decr(self, key):
        self._data[key] = self._data.get(key, 0) - 1
        return self._data[key]

    def delete(self, key):
        self._data.pop(key, None)

    def exists(self, key):
        return key in self._data

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._cmds = []

    def incr(self, key):
        self._cmds.append(('incr', key))
        return self

    def decr(self, key):
        self._cmds.append(('decr', key))
        return self

    def execute(self):
        results = []
        for cmd, key in self._cmds:
            results.append(getattr(self._redis, cmd)(key))
        self._cmds = []
        return results


class MultiWorkerManagerImportMixin:
    """Mixin to import the manager class with patched Django/Redis deps."""

    @classmethod
    def get_manager_class(cls):
        import importlib
        import sys

        # Stub out heavy Django deps so we can import the module standalone
        for mod in ['apps.vod.models', 'apps.m3u.models', 'core.utils']:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
            RedisBackedVODConnection,
        )
        return MultiWorkerVODConnectionManager, RedisBackedVODConnection


class TestDecrementProfileConnectionsAtomic(TestCase):
    """Bug 2: _decrement_profile_connections must be atomic (no GET-then-DECR)."""

    def _make_manager(self, redis):
        _, _ = MultiWorkerManagerImportMixin.get_manager_class()
        from apps.proxy.vod_proxy.multi_worker_connection_manager import MultiWorkerVODConnectionManager
        mgr = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        mgr.redis_client = redis
        mgr.worker_id = 'test-worker'
        return mgr

    def test_decrement_does_not_go_negative(self):
        """Counter must be clamped to 0, never go negative."""
        redis = FakeRedis()
        redis.set('profile_connections:1', 0)
        mgr = self._make_manager(redis)

        result = mgr._decrement_profile_connections(1)

        self.assertEqual(result, 0)
        self.assertEqual(int(redis._data.get('profile_connections:1', 0)), 0)

    def test_decrement_from_one_reaches_zero(self):
        """Normal single decrement should reach 0."""
        redis = FakeRedis()
        redis.set('profile_connections:1', 1)
        mgr = self._make_manager(redis)

        result = mgr._decrement_profile_connections(1)

        self.assertEqual(result, 0)

    def test_concurrent_decrements_clamp_to_zero(self):
        """Two concurrent decrements of a counter at 1 must not leave it at -1."""
        redis = FakeRedis()
        redis.set('profile_connections:1', 1)
        mgr = self._make_manager(redis)

        # Simulate two concurrent decrements (both fire before either reads back)
        mgr._decrement_profile_connections(1)
        mgr._decrement_profile_connections(1)

        final = int(redis._data.get('profile_connections:1', 0))
        self.assertGreaterEqual(final, 0, "Counter must not go negative after concurrent decrements")


class TestDecrementActiveStreamsAndCheck(TestCase):
    """Atomic DECR+check via Redis Lua (no session lock)."""

    def test_returns_success_and_no_remaining_when_last_stream(self):
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _seed_session,
            _import_vod,
            _clear_script_cache,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        _seed_session(redis, "prof-last", active_streams=1)
        conn = RedisBackedVODConnection("prof-last", redis)

        result = conn.decrement_active_streams_and_check()

        self.assertEqual(result, (True, False))
        self.assertEqual(conn.get_active_streams_count(), 0)

    def test_returns_success_and_remaining_when_other_streams_active(self):
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _seed_session,
            _import_vod,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        _seed_session(redis, "prof-rem", active_streams=2)
        conn = RedisBackedVODConnection("prof-rem", redis)

        result = conn.decrement_active_streams_and_check()

        self.assertEqual(result, (True, True))
        self.assertEqual(conn.get_active_streams_count(), 1)

    def test_returns_failure_when_already_at_zero(self):
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _seed_session,
            _import_vod,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        _seed_session(redis, "prof-zero", active_streams=0)
        conn = RedisBackedVODConnection("prof-zero", redis)

        result = conn.decrement_active_streams_and_check()

        self.assertEqual(result, (False, False))
        self.assertEqual(conn.get_active_streams_count(), 0)

    def test_returns_failure_when_no_session(self):
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _clear_script_cache,
        )

        RedisBackedVODConnection, _ = _import_vod()
        _clear_script_cache()
        redis = LockAwareFakeRedis()
        conn = RedisBackedVODConnection("missing", redis)

        result = conn.decrement_active_streams_and_check()

        self.assertEqual(result, (False, False))


class TestCreateConnectionSeedsActiveStreams(TestCase):
    """New sessions must seed active_streams=1 with the profile reserve."""

    def test_create_seeds_active_streams_one_and_returns_created(self):
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _clear_script_cache,
        )

        RedisBackedVODConnection, _ = _import_vod()
        _clear_script_cache()
        redis = LockAwareFakeRedis()
        conn = RedisBackedVODConnection("vod_new_seed", redis)

        result = conn.create_connection(
            stream_url="http://example.com/movie.mp4",
            headers={"User-Agent": "test"},
            m3u_profile_id=42,
            content_obj_type="movie",
            content_uuid="uuid-1",
            content_name="Movie",
            client_ip="1.2.3.4",
            client_user_agent="ua",
            worker_id="worker-1",
        )

        self.assertEqual(result, "created")
        self.assertEqual(conn.get_active_streams_count(), 1)
        state = conn._get_connection_state()
        self.assertEqual(state.m3u_profile_id, 42)

    def test_create_returns_exists_without_changing_active_streams(self):
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _clear_script_cache,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        _clear_script_cache()
        redis = LockAwareFakeRedis()
        _seed_session(redis, "vod_exists", active_streams=2, profile_id=9)
        conn = RedisBackedVODConnection("vod_exists", redis)

        result = conn.create_connection(
            stream_url="http://example.com/other.mp4",
            headers={},
            m3u_profile_id=9,
        )

        self.assertEqual(result, "exists")
        self.assertEqual(conn.get_active_streams_count(), 2)

    def test_create_lock_miss_returns_exists_when_hash_already_written(self):
        """Creator writes the hash before releasing the lock. A lock miss after
        that write must join as exists, not return False / 500.
        """
        from unittest.mock import patch

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _clear_script_cache,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        _clear_script_cache()
        redis = LockAwareFakeRedis()
        _seed_session(redis, "vod_lock_miss", active_streams=1, profile_id=9)
        conn = RedisBackedVODConnection("vod_lock_miss", redis)

        with patch.object(conn, "_acquire_lock", return_value=False):
            result = conn.create_connection(
                stream_url="http://example.com/other.mp4",
                headers={},
                m3u_profile_id=9,
            )

        self.assertEqual(result, "exists")
        self.assertEqual(conn.get_active_streams_count(), 1)

    def test_create_lock_miss_returns_false_when_hash_absent(self):
        from unittest.mock import patch

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _clear_script_cache,
        )

        RedisBackedVODConnection, _ = _import_vod()
        _clear_script_cache()
        redis = LockAwareFakeRedis()
        conn = RedisBackedVODConnection("vod_lock_miss_empty", redis)

        with patch.object(conn, "_acquire_lock", return_value=False):
            result = conn.create_connection(
                stream_url="http://example.com/movie.mp4",
                headers={},
                m3u_profile_id=9,
            )

        self.assertIs(result, False)


class TestRollbackSetupReservations(TestCase):
    """Setup failure must DECR active_streams before releasing profile."""

    def _make_manager(self, redis):
        MultiWorkerManagerImportMixin.get_manager_class()
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        mgr = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        mgr.redis_client = redis
        mgr.worker_id = "test-worker"
        return mgr

    def test_rollback_releases_profile_when_last_stream(self):
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_last", active_streams=1, profile_id=7)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=True,
            active_reserved=True,
            client_id="vod_rb_last",
            cleanup_session=True,
        )

        self.assertTrue(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 0)
        # Profile released immediately; hash kept for the 1s settle window.
        self.assertIsNotNone(conn._get_connection_state())
        self.assertEqual(conn.get_active_streams_count(), 0)

    def test_rollback_keeps_profile_when_other_streams_remain(self):
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_rem", active_streams=2, profile_id=7)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=True,
            active_reserved=True,
            client_id="vod_rb_rem",
            cleanup_session=True,
        )

        self.assertFalse(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 1)
        self.assertEqual(conn.get_active_streams_count(), 1)
        self.assertIsNotNone(conn._get_connection_state())

    def test_rollback_closes_local_http_when_siblings_remain(self):
        """Provider HTTP is process-local and must close even when Redis stays."""
        from unittest.mock import MagicMock

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_http", active_streams=2, profile_id=7)
        local_response = MagicMock()
        local_session = MagicMock()
        conn.local_response = local_response
        conn.local_session = local_session
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=False,
            active_reserved=True,
            client_id="vod_rb_http",
            cleanup_session=True,
        )

        self.assertFalse(released)
        local_response.close.assert_called_once()
        local_session.close.assert_called_once()
        self.assertIsNone(conn.local_response)
        self.assertIsNone(conn.local_session)
        self.assertIsNotNone(conn._get_connection_state())

    def test_rollback_without_cleanup_leaves_idle_session(self):
        """416 path: release counters but keep hash for seek/retry reuse."""
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_416", active_streams=1, profile_id=7)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=True,
            active_reserved=True,
            client_id="vod_rb_416",
            cleanup_session=False,
        )

        self.assertTrue(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 0)
        self.assertEqual(conn.get_active_streams_count(), 0)
        self.assertIsNotNone(conn._get_connection_state())

    def test_rollback_416_closes_local_http_but_keeps_hash(self):
        """416 keeps the Redis hash for seek/retry, but this request's provider
        HTTP is still process-local and must be closed immediately.
        """
        from unittest.mock import MagicMock

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_416_http", active_streams=1, profile_id=7)
        local_response = MagicMock()
        local_session = MagicMock()
        conn.local_response = local_response
        conn.local_session = local_session
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=True,
            active_reserved=True,
            client_id="vod_rb_416_http",
            cleanup_session=False,
        )

        self.assertTrue(released)
        local_response.close.assert_called_once()
        local_session.close.assert_called_once()
        self.assertIsNone(conn.local_response)
        self.assertIsNone(conn.local_session)
        self.assertIsNotNone(conn._get_connection_state())
        self.assertEqual(conn.get_active_streams_count(), 0)

    def test_rollback_releases_profile_for_piggybacked_last_exit(self):
        """Last DECR releases the session's profile slot, even if this caller
        never reserved it (joined via new_count > 1).
        """
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_piggyback", active_streams=1, profile_id=7)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=False,
            active_reserved=True,
            client_id="vod_rb_piggyback",
            cleanup_session=True,
        )

        self.assertTrue(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 0)
        self.assertIsNotNone(conn._get_connection_state())
        self.assertEqual(conn.get_active_streams_count(), 0)

    def test_rollback_keeps_profile_for_piggybacked_non_last_exit(self):
        """Piggybacked caller must not release the slot while siblings remain."""
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_piggyback_rem", active_streams=2, profile_id=7)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=False,
            active_reserved=True,
            client_id="vod_rb_piggyback_rem",
            cleanup_session=True,
        )

        self.assertFalse(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 1)
        self.assertEqual(conn.get_active_streams_count(), 1)

    def test_rollback_releases_profile_when_never_reserved_active_streams(self):
        """No active_streams stake: a private profile reservation is released directly."""
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = RedisBackedVODConnection("vod_rb_never_created", redis)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=True,
            active_reserved=False,
            client_id="vod_rb_never_created",
            cleanup_session=True,
        )

        self.assertTrue(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 0)

    def test_rollback_noop_when_nothing_reserved(self):
        """Neither flag set: nothing to roll back, no Redis mutation."""
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = RedisBackedVODConnection("vod_rb_noop", redis)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=False,
            active_reserved=False,
            client_id="vod_rb_noop",
            cleanup_session=True,
        )

        self.assertFalse(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 1)

    def test_rollback_fails_closed_on_redis_error_during_decrement(self):
        """Raised DECR error must not release a slot that may still be in use."""
        from unittest.mock import MagicMock

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
        )

        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        mgr = self._make_manager(redis)

        broken_conn = MagicMock()
        broken_conn.decrement_active_streams_and_check.side_effect = ConnectionError("redis down")
        broken_conn.has_active_streams.side_effect = ConnectionError("still down")

        released = mgr._rollback_setup_reservations(
            broken_conn,
            profile_id=7,
            profile_reserved=True,
            active_reserved=True,
            client_id="vod_rb_error",
            cleanup_session=True,
        )

        self.assertFalse(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 1)
        broken_conn.cleanup.assert_not_called()

    def test_rollback_fails_closed_on_decr_unknown_remaining_sentinel(self):
        """decrement_active_streams_and_check returns (False, True) on Redis
        errors without raising. Must not release the profile slot.
        """
        from unittest.mock import MagicMock

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
        )

        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        mgr = self._make_manager(redis)

        broken_conn = MagicMock()
        broken_conn.decrement_active_streams_and_check.return_value = (False, True)

        released = mgr._rollback_setup_reservations(
            broken_conn,
            profile_id=7,
            profile_reserved=True,
            active_reserved=True,
            client_id="vod_rb_sentinel",
            cleanup_session=True,
        )

        self.assertFalse(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 1)
        broken_conn.cleanup.assert_not_called()

    def test_failed_decr_does_not_release_profile_for_piggyback(self):
        """Piggyback DECR no-op (already 0 / no hash) must not release the slot."""
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_decr_miss", active_streams=0, profile_id=7)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=False,
            active_reserved=True,
            client_id="vod_rb_decr_miss",
            cleanup_session=True,
        )

        self.assertFalse(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 1)
        self.assertIsNotNone(conn._get_connection_state())

    def test_failed_decr_releases_own_profile_reservation(self):
        """DECR no-op after this caller reserved a private profile slot."""
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_decr_own", active_streams=0, profile_id=7)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            conn,
            profile_id=7,
            profile_reserved=True,
            active_reserved=True,
            client_id="vod_rb_decr_own",
            cleanup_session=True,
        )

        self.assertTrue(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 0)

    def test_rollback_reconstructs_connection_when_handle_missing(self):
        """Idle-match can INCR before redis_connection is assigned."""
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        _seed_session(redis, "vod_rb_no_handle", active_streams=1, profile_id=7)
        mgr = self._make_manager(redis)

        released = mgr._rollback_setup_reservations(
            None,
            profile_id=7,
            profile_reserved=False,
            active_reserved=True,
            client_id="vod_rb_no_handle",
            cleanup_session=True,
        )

        self.assertTrue(released)
        self.assertEqual(int(redis._data.get("profile_connections:7", 0)), 0)
        conn = RedisBackedVODConnection("vod_rb_no_handle", redis)
        self.assertIsNotNone(conn._get_connection_state())
        self.assertEqual(conn.get_active_streams_count(), 0)

    def test_rollback_delayed_cleanup_deletes_idle_hash_after_settle(self):
        """After the settle window, an idle hash is deleted."""
        from unittest.mock import patch

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_delayed", active_streams=1, profile_id=7)
        mgr = self._make_manager(redis)

        run_targets = []

        class ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                run_targets.append(self._target)

        with patch("apps.proxy.vod_proxy.multi_worker_connection_manager.threading.Thread", ImmediateThread), \
             patch("apps.proxy.vod_proxy.multi_worker_connection_manager.time.sleep"):
            released = mgr._rollback_setup_reservations(
                conn,
                profile_id=7,
                profile_reserved=True,
                active_reserved=True,
                client_id="vod_rb_delayed",
                cleanup_session=True,
            )

        self.assertTrue(released)
        self.assertEqual(len(run_targets), 1)
        self.assertIsNotNone(conn._get_connection_state())
        run_targets[0]()
        self.assertIsNone(conn._get_connection_state())

    def test_rollback_delayed_cleanup_skips_when_reconnect_joins(self):
        """A reconnect INCR during the settle window keeps the session hash."""
        from unittest.mock import patch

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 1)
        conn = _seed_session(redis, "vod_rb_reconnect", active_streams=1, profile_id=7)
        mgr = self._make_manager(redis)

        run_targets = []

        class ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                run_targets.append(self._target)

        with patch("apps.proxy.vod_proxy.multi_worker_connection_manager.threading.Thread", ImmediateThread), \
             patch("apps.proxy.vod_proxy.multi_worker_connection_manager.time.sleep"):
            released = mgr._rollback_setup_reservations(
                conn,
                profile_id=7,
                profile_reserved=True,
                active_reserved=True,
                client_id="vod_rb_reconnect",
                cleanup_session=True,
            )

        self.assertTrue(released)
        self.assertEqual(conn.increment_active_streams(), 1)
        run_targets[0]()
        self.assertIsNotNone(conn._get_connection_state())
        self.assertEqual(conn.get_active_streams_count(), 1)


class TestGetStreamErrorDoesNotOrphanProfile(TestCase):
    """get_stream failures must not delete the session hash out from under setup."""

    def test_get_stream_error_preserves_session_hash(self):
        from unittest.mock import patch, MagicMock

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        conn = _seed_session(redis, "vod_gs_err", active_streams=1, profile_id=7)

        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("upstream down")

        with patch.object(conn, "local_session", mock_session):
            with self.assertRaises(ConnectionError):
                conn.get_stream()

        self.assertIsNotNone(conn._get_connection_state())
        self.assertEqual(conn.get_active_streams_count(), 1)
        self.assertIsNone(conn.local_session)
        mock_session.close.assert_called_once()

    def test_get_stream_error_closes_inflight_response(self):
        """raise_for_status can fail before local_response is assigned."""
        from unittest.mock import MagicMock

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        conn = _seed_session(redis, "vod_gs_inflight", active_streams=1, profile_id=7)

        inflight = MagicMock()
        inflight.status_code = 502
        inflight.raise_for_status.side_effect = ConnectionError("bad gateway")
        mock_session = MagicMock()
        mock_session.get.return_value = inflight
        conn.local_session = mock_session

        with self.assertRaises(ConnectionError):
            conn.get_stream()

        inflight.close.assert_called_once()
        mock_session.close.assert_called_once()
        self.assertIsNone(conn.local_response)
        self.assertIsNone(conn.local_session)
        self.assertIsNotNone(conn._get_connection_state())


class TestStreamSetupCreateRaceAndIdleGuard(TestCase):
    """stream_content_with_session setup edge cases around create/idle."""

    def _make_manager(self, redis):
        MultiWorkerManagerImportMixin.get_manager_class()
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        mgr = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        mgr.redis_client = redis
        mgr.worker_id = "test-worker"
        return mgr

    def _mock_content_and_profile(self):
        from unittest.mock import MagicMock

        content = MagicMock()
        content.uuid = "uuid-race"
        content.name = "Movie"
        # isinstance(content_obj, Movie) is False for MagicMock unless we patch;
        # stream_content uses that only for content_type labeling.
        profile = MagicMock()
        profile.id = 7
        profile.name = "prof"
        profile.m3u_account.get_user_agent_string.return_value = "ua"
        request = MagicMock()
        request.META = {}
        return content, profile, request

    def test_create_race_exists_does_not_emit_vod_started(self):
        """Joining an already-created hash must not look like a new session."""
        from unittest.mock import MagicMock, patch

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        redis.set("profile_connections:7", 0)
        # Hash appears after the initial existence check (create race).
        mgr = self._make_manager(redis)
        content, profile, request = self._mock_content_and_profile()

        events = []

        def capture_event(event_type, *args, **kwargs):
            events.append(event_type)

        upstream = MagicMock()
        upstream.iter_content.return_value = [b"x"]
        upstream.headers = {}

        with patch.object(mgr, "find_matching_idle_session", return_value=None), \
             patch.object(mgr, "_check_and_reserve_profile_slot", return_value=True), \
             patch.object(mgr, "_send_vod_event", side_effect=capture_event), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.create_connection",
                 return_value="exists",
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection._get_connection_state",
                 return_value=None,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.increment_active_streams",
                 return_value=2,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_stream",
                 return_value=upstream,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/mp4"},
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.decrement_active_streams_and_check",
                 return_value=(True, True),
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection._close_local_http",
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.Movie",
                 new=type(content),
             ):
            # Avoid decrementing a real profile key during duplicate-reserve drop.
            with patch.object(mgr, "_decrement_profile_connections"):
                response = mgr.stream_content_with_session(
                    session_id="vod_race",
                    content_obj=content,
                    stream_url="http://example.com/m.mp4",
                    m3u_profile=profile,
                    client_ip="1.2.3.4",
                    client_user_agent="ua",
                    request=request,
                )
                # Drive the generator so vod_started would fire if session_is_new.
                body = b"".join(response.streaming_content)

        self.assertEqual(body, b"x")
        self.assertNotIn("vod_started", events)

    def test_idle_reserved_missing_hash_decrements_and_returns_500(self):
        """Idle INCR must not fall through into create_connection."""
        from unittest.mock import MagicMock, patch

        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
        )

        RedisBackedVODConnection, _ = _import_vod()
        redis = LockAwareFakeRedis()
        mgr = self._make_manager(redis)
        content, profile, request = self._mock_content_and_profile()

        with patch.object(mgr, "find_matching_idle_session", return_value="vod_idle_gone"), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.increment_active_streams",
                 return_value=1,
             ) as incr, \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection._get_connection_state",
                 return_value=None,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.decrement_active_streams",
             ) as decr, \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.create_connection",
             ) as create, \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.Movie",
                 new=type(content),
             ):
            response = mgr.stream_content_with_session(
                session_id="vod_new",
                content_obj=content,
                stream_url="http://example.com/m.mp4",
                m3u_profile=profile,
                client_ip="1.2.3.4",
                client_user_agent="ua",
                request=request,
            )

        self.assertEqual(response.status_code, 500)
        incr.assert_called()
        decr.assert_called()
        create.assert_not_called()


class TestIdleMatchAcrossDifferentProfile(TestCase):
    """find_matching_idle_session doesn't filter by profile, and the view
    re-selects a profile per request based on current capacity/priority, so
    an idle-matched session can be joined under a different m3u_profile than
    the one already stored on its hash. Reservation and every teardown
    decrement must agree on the session's own profile in that case, not the
    view's freshly selected one, or one profile's counter leaks forever
    while another gets decremented for a reservation it never made.
    """

    def _make_manager(self, redis):
        MultiWorkerManagerImportMixin.get_manager_class()
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        mgr = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        mgr.redis_client = redis
        mgr.worker_id = "test-worker"
        return mgr

    def test_reuse_under_different_profile_reserves_and_decrements_same_counter(self):
        """An idle-matched session must keep using its own stored profile for
        the whole reservation lifecycle, not whatever profile the view
        freshly selected for this request (which reflects capacity at
        request time and may differ once a match is found).
        """
        from unittest.mock import MagicMock, patch

        from apps.m3u.models import M3UAccount, M3UAccountProfile
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()

        account = M3UAccount.objects.create(name="Provider")
        profile_a = account.profiles.get(is_default=True)
        profile_b = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="profile-b",
            search_pattern="^(.*)$",
            replace_pattern="$1",
            max_streams=5,
        )

        redis = LockAwareFakeRedis()
        # Idle session "vod_idle" was created under profile A.
        _seed_session(redis, "vod_idle", active_streams=0, profile_id=profile_a.id)
        redis.set(f"profile_connections:{profile_a.id}", 0)
        redis.set(f"profile_connections:{profile_b.id}", 0)

        mgr = self._make_manager(redis)

        content = MagicMock()
        content.uuid = "uuid-mismatch"
        content.name = "Movie"
        request = MagicMock()
        request.META = {}

        upstream = MagicMock()
        upstream.iter_content.return_value = [b"x"]
        upstream.headers = {}

        def fake_reserve(profile):
            redis.incr(f"profile_connections:{profile.id}")
            return True

        with patch.object(mgr, "find_matching_idle_session", return_value="vod_idle"), \
             patch.object(mgr, "_check_and_reserve_profile_slot", side_effect=fake_reserve), \
             patch.object(mgr, "_send_vod_event"), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_stream",
                 return_value=upstream,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/mp4"},
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.Movie",
                 new=type(content),
             ):
            # This request freshly selected profile B, e.g. due to
            # capacity/priority shifting since profile A's session went idle.
            response = mgr.stream_content_with_session(
                session_id="vod_new_session",
                content_obj=content,
                stream_url="http://example.com/m.mp4",
                m3u_profile=profile_b,
                client_ip="1.2.3.4",
                client_user_agent="ua",
                request=request,
            )
            # The reservation went to profile A (the session's own profile),
            # not profile B (the view's fresh, now-irrelevant pick).
            self.assertEqual(int(redis._data.get(f"profile_connections:{profile_a.id}", 0)), 1)
            self.assertEqual(int(redis._data.get(f"profile_connections:{profile_b.id}", 0)), 0)

            # Drain the generator to normal completion (last stream out).
            list(response.streaming_content)

        self.assertEqual(
            int(redis._data.get(f"profile_connections:{profile_a.id}", 0)), 0,
            "profile A was incremented for this reservation and must be "
            "decremented back to 0 on teardown"
        )
        self.assertEqual(
            int(redis._data.get(f"profile_connections:{profile_b.id}", 0)), 0,
            "profile B was never actually reserved for this reused session "
            "and must stay untouched"
        )

    def test_reuse_falls_back_to_view_profile_when_stored_profile_deleted(self):
        """If the session's stored profile no longer exists (deleted since
        the session was created), fall back to the view's freshly selected
        profile instead of raising.
        """
        from unittest.mock import MagicMock, patch

        from apps.m3u.models import M3UAccount, M3UAccountProfile
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()

        account = M3UAccount.objects.create(name="Provider")
        profile_b = account.profiles.get(is_default=True)
        deleted_profile_id = 999999  # Not present in the DB.

        redis = LockAwareFakeRedis()
        _seed_session(redis, "vod_idle_gone", active_streams=0, profile_id=deleted_profile_id)
        redis.set(f"profile_connections:{profile_b.id}", 0)

        mgr = self._make_manager(redis)

        content = MagicMock()
        content.uuid = "uuid-deleted-profile"
        content.name = "Movie"
        request = MagicMock()
        request.META = {}

        upstream = MagicMock()
        upstream.iter_content.return_value = [b"x"]
        upstream.headers = {}

        def fake_reserve(profile):
            redis.incr(f"profile_connections:{profile.id}")
            return True

        with patch.object(mgr, "find_matching_idle_session", return_value="vod_idle_gone"), \
             patch.object(mgr, "_check_and_reserve_profile_slot", side_effect=fake_reserve), \
             patch.object(mgr, "_send_vod_event"), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_stream",
                 return_value=upstream,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/mp4"},
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.Movie",
                 new=type(content),
             ):
            response = mgr.stream_content_with_session(
                session_id="vod_new_session_2",
                content_obj=content,
                stream_url="http://example.com/m.mp4",
                m3u_profile=profile_b,
                client_ip="1.2.3.4",
                client_user_agent="ua",
                request=request,
            )
            self.assertEqual(int(redis._data.get(f"profile_connections:{profile_b.id}", 0)), 1)
            # Dead stored profile must be rewritten so sibling joiners agree.
            rewritten = redis.hget(
                "vod_persistent_connection:vod_idle_gone", "m3u_profile_id"
            )
            self.assertEqual(int(rewritten), profile_b.id)
            list(response.streaming_content)

        self.assertEqual(int(redis._data.get(f"profile_connections:{profile_b.id}", 0)), 0)

    def test_concurrent_idle_match_only_first_incr_reserves_profile(self):
        """Two requests that both match the same idle session must not each
        reserve a profile slot. Only the 0→1 INCR takes the slot; the 1→2
        joiner is a sibling. Last-out releases once.
        """
        from unittest.mock import MagicMock, patch

        from apps.m3u.models import M3UAccount, M3UAccountProfile
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()

        account = M3UAccount.objects.create(name="Provider")
        profile_a = account.profiles.get(is_default=True)
        profile_b = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="profile-b",
            search_pattern="^(.*)$",
            replace_pattern="$1",
            max_streams=5,
        )

        redis = LockAwareFakeRedis()
        _seed_session(redis, "vod_idle", active_streams=0, profile_id=profile_a.id)
        redis.set(f"profile_connections:{profile_a.id}", 0)
        redis.set(f"profile_connections:{profile_b.id}", 0)

        mgr = self._make_manager(redis)

        content = MagicMock()
        content.uuid = "uuid-storm"
        content.name = "Movie"
        request = MagicMock()
        request.META = {}

        def _upstream():
            upstream = MagicMock()
            upstream.iter_content.return_value = [b"x"]
            upstream.headers = {}
            return upstream

        def fake_reserve(profile):
            redis.incr(f"profile_connections:{profile.id}")
            return True

        with patch.object(mgr, "find_matching_idle_session", return_value="vod_idle"), \
             patch.object(mgr, "_check_and_reserve_profile_slot", side_effect=fake_reserve), \
             patch.object(mgr, "_send_vod_event"), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_stream",
                 side_effect=lambda *a, **k: _upstream(),
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/mp4"},
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.Movie",
                 new=type(content),
             ):
            first = mgr.stream_content_with_session(
                session_id="vod_storm_1",
                content_obj=content,
                stream_url="http://example.com/m.mp4",
                m3u_profile=profile_b,
                client_ip="1.2.3.4",
                client_user_agent="ua",
                request=request,
            )
            self.assertEqual(int(redis._data.get(f"profile_connections:{profile_a.id}", 0)), 1)
            self.assertEqual(
                RedisBackedVODConnection("vod_idle", redis).get_active_streams_count(), 1
            )

            second = mgr.stream_content_with_session(
                session_id="vod_storm_2",
                content_obj=content,
                stream_url="http://example.com/m.mp4",
                m3u_profile=profile_b,
                client_ip="1.2.3.4",
                client_user_agent="ua",
                request=request,
            )
            self.assertEqual(
                int(redis._data.get(f"profile_connections:{profile_a.id}", 0)), 1,
                "second idle-match must not take another profile slot"
            )
            self.assertEqual(int(redis._data.get(f"profile_connections:{profile_b.id}", 0)), 0)
            self.assertEqual(
                RedisBackedVODConnection("vod_idle", redis).get_active_streams_count(), 2
            )

            list(second.streaming_content)
            self.assertEqual(int(redis._data.get(f"profile_connections:{profile_a.id}", 0)), 1)

            list(first.streaming_content)

        self.assertEqual(int(redis._data.get(f"profile_connections:{profile_a.id}", 0)), 0)
        self.assertEqual(int(redis._data.get(f"profile_connections:{profile_b.id}", 0)), 0)


class TestCreateRaceBindsStoredProfile(TestCase):
    """create_connection returning 'exists' must join the winner's stored
    profile, not keep tearing down against this request's view pick.
    """

    def _make_manager(self, redis):
        MultiWorkerManagerImportMixin.get_manager_class()
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        mgr = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        mgr.redis_client = redis
        mgr.worker_id = "test-worker"
        return mgr

    def test_create_exists_sibling_teardown_uses_winner_profile(self):
        """Loser of a create race already reserved its view profile, then
        drops that reserve when joining as a sibling. Last-out teardown must
        release the winner's stored profile, not the loser's view pick.
        """
        from unittest.mock import MagicMock, patch

        from apps.m3u.models import M3UAccount, M3UAccountProfile
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
            LockAwareFakeRedis,
            _import_vod,
            _seed_session,
        )

        RedisBackedVODConnection, _ = _import_vod()

        account = M3UAccount.objects.create(name="Provider")
        profile_winner = account.profiles.get(is_default=True)
        profile_loser = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="profile-loser",
            search_pattern="^(.*)$",
            replace_pattern="$1",
            max_streams=5,
        )

        redis = LockAwareFakeRedis()
        # Winner already created the hash under profile_winner with one stake.
        _seed_session(
            redis, "vod_race", active_streams=1, profile_id=profile_winner.id
        )
        redis.set(f"profile_connections:{profile_winner.id}", 1)
        redis.set(f"profile_connections:{profile_loser.id}", 0)

        mgr = self._make_manager(redis)

        content = MagicMock()
        content.uuid = "uuid-race"
        content.name = "Movie"
        request = MagicMock()
        request.META = {}

        upstream = MagicMock()
        upstream.iter_content.return_value = [b"x"]
        upstream.headers = {}

        reserved = []

        def fake_reserve(profile):
            redis.incr(f"profile_connections:{profile.id}")
            reserved.append(profile.id)
            return True

        real_get = RedisBackedVODConnection._get_connection_state
        call_count = {"n": 0}

        def get_state_once_none(self):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None
            return real_get(self)

        with patch.object(mgr, "find_matching_idle_session", return_value=None), \
             patch.object(mgr, "_check_and_reserve_profile_slot", side_effect=fake_reserve), \
             patch.object(mgr, "_send_vod_event"), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection._get_connection_state",
                 get_state_once_none,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.create_connection",
                 return_value="exists",
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_stream",
                 return_value=upstream,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/mp4"},
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.Movie",
                 new=type(content),
             ):
            response = mgr.stream_content_with_session(
                session_id="vod_race",
                content_obj=content,
                stream_url="http://example.com/m.mp4",
                m3u_profile=profile_loser,
                client_ip="1.2.3.4",
                client_user_agent="ua",
                request=request,
            )

            # Loser reserved then dropped its own view profile (sibling path).
            self.assertEqual(reserved, [profile_loser.id])
            self.assertEqual(
                int(redis._data.get(f"profile_connections:{profile_loser.id}", 0)), 0
            )
            # Winner's slot still held; loser joined as second stake.
            self.assertEqual(
                int(redis._data.get(f"profile_connections:{profile_winner.id}", 0)), 1
            )
            self.assertEqual(
                RedisBackedVODConnection("vod_race", redis).get_active_streams_count(), 2
            )

            # Winner exits first without releasing the profile (siblings remain).
            RedisBackedVODConnection(
                "vod_race", redis
            ).decrement_active_streams_and_check()

            # Loser drains last: must release winner's profile, not loser's.
            list(response.streaming_content)

        self.assertEqual(
            int(redis._data.get(f"profile_connections:{profile_winner.id}", 0)), 0
        )
        self.assertEqual(
            int(redis._data.get(f"profile_connections:{profile_loser.id}", 0)), 0
        )


class TestMidStreamUpstreamRetry(TestCase):
    """Transparent Range reopen when upstream stalls mid-body."""

    def _make_manager(self, redis):
        MultiWorkerManagerImportMixin.get_manager_class()
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        mgr = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        mgr.redis_client = redis
        mgr.worker_id = "test-worker"
        return mgr

    def _run_stream(self, mgr, redis, profile, content, request, get_stream_side_effect,
                    range_header="bytes=100-"):
        """Drive the full stream while get_stream stays patched (incl. reopens)."""
        from unittest.mock import patch

        def fake_reserve(p):
            redis.incr(f"profile_connections:{p.id}")
            return True

        with patch.object(mgr, "find_matching_idle_session", return_value=None), \
             patch.object(mgr, "_check_and_reserve_profile_slot", side_effect=fake_reserve), \
             patch.object(mgr, "_send_vod_event"), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_stream",
                 side_effect=get_stream_side_effect,
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/mp4", "content_length": "1000"},
             ), \
             patch(
                 "apps.proxy.vod_proxy.multi_worker_connection_manager.Movie",
                 new=type(content),
             ):
            response = mgr.stream_content_with_session(
                session_id="vod_retry",
                content_obj=content,
                stream_url="http://example.com/m.mp4",
                m3u_profile=profile,
                client_ip="1.2.3.4",
                client_user_agent="ua",
                request=request,
                range_header=range_header,
            )
            return b"".join(response.streaming_content)

    def test_resume_range_header_helpers(self):
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        self.assertEqual(MultiWorkerVODConnectionManager._range_start_byte("bytes=100-"), 100)
        self.assertEqual(MultiWorkerVODConnectionManager._range_start_byte("bytes=100-500"), 100)
        self.assertEqual(MultiWorkerVODConnectionManager._range_start_byte(None), 0)
        self.assertEqual(
            MultiWorkerVODConnectionManager._resume_range_header("bytes=100-", 250),
            "bytes=250-",
        )
        self.assertEqual(
            MultiWorkerVODConnectionManager._resume_range_header("bytes=100-500", 250),
            "bytes=250-500",
        )

    def test_read_timeout_reopens_and_continues(self):
        """One mid-stream ReadTimeout reopens at absolute offset and finishes."""
        import requests
        from unittest.mock import MagicMock

        from apps.m3u.models import M3UAccount
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import LockAwareFakeRedis

        account = M3UAccount.objects.create(name="Provider-retry")
        profile = account.profiles.get(is_default=True)
        redis = LockAwareFakeRedis()
        redis.set(f"profile_connections:{profile.id}", 0)
        mgr = self._make_manager(redis)

        content = MagicMock()
        content.uuid = "uuid-retry"
        content.name = "Movie"
        request = MagicMock()
        request.META = {}

        first = MagicMock()

        def first_iter(chunk_size=8192):
            yield b"aaa"
            raise requests.exceptions.ReadTimeout("stalled")

        first.iter_content.side_effect = first_iter

        second = MagicMock()
        second.iter_content.return_value = [b"bbb", b"ccc"]

        ranges_requested = []

        def get_stream(*args, **kwargs):
            rh = kwargs.get("range_header")
            if rh is None:
                for a in reversed(args):
                    if isinstance(a, (str, type(None))):
                        rh = a
                        break
            ranges_requested.append(rh)
            if len(ranges_requested) == 1:
                return first
            return second

        body = self._run_stream(mgr, redis, profile, content, request, get_stream)

        self.assertEqual(body, b"aaabbbccc")
        self.assertEqual(ranges_requested[0], "bytes=100-")
        # 100 start + 3 bytes already sent
        self.assertEqual(ranges_requested[1], "bytes=103-")
        self.assertEqual(int(redis._data.get(f"profile_connections:{profile.id}", 0)), 0)

    def test_three_consecutive_failures_then_give_up(self):
        """Four upstream failures in a row (initial + 3 retries) abort the stream."""
        import requests
        from unittest.mock import MagicMock

        from apps.m3u.models import M3UAccount
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            _MAX_CONSECUTIVE_UPSTREAM_RETRIES,
        )
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import LockAwareFakeRedis

        account = M3UAccount.objects.create(name="Provider-retry-fail")
        profile = account.profiles.get(is_default=True)
        redis = LockAwareFakeRedis()
        redis.set(f"profile_connections:{profile.id}", 0)
        mgr = self._make_manager(redis)

        content = MagicMock()
        content.uuid = "uuid-retry-fail"
        content.name = "Movie"
        request = MagicMock()
        request.META = {}

        opens = []

        def get_stream(*args, **kwargs):
            rh = kwargs.get("range_header")
            if rh is None:
                for a in reversed(args):
                    if isinstance(a, (str, type(None))):
                        rh = a
                        break
            opens.append(rh)
            upstream = MagicMock()

            def boom(chunk_size=8192):
                yield b"x"
                raise requests.exceptions.ReadTimeout("still down")

            if len(opens) == 1:
                upstream.iter_content.side_effect = boom
            else:
                def fail_now(chunk_size=8192):
                    raise requests.exceptions.ReadTimeout("still down")
                    yield  # pragma: no cover

                upstream.iter_content.side_effect = fail_now
            return upstream

        body = self._run_stream(mgr, redis, profile, content, request, get_stream)

        self.assertEqual(body, b"x")
        self.assertEqual(len(opens), 1 + _MAX_CONSECUTIVE_UPSTREAM_RETRIES)
        self.assertEqual(int(redis._data.get(f"profile_connections:{profile.id}", 0)), 0)

    def test_successful_chunk_resets_consecutive_retry_budget(self):
        """After data flows again, a later stall gets a fresh 3-retry budget."""
        import requests
        from unittest.mock import MagicMock

        from apps.m3u.models import M3UAccount
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            _MAX_CONSECUTIVE_UPSTREAM_RETRIES,
        )
        from apps.proxy.vod_proxy.tests.test_vod_lock_contention import LockAwareFakeRedis

        account = M3UAccount.objects.create(name="Provider-retry-reset")
        profile = account.profiles.get(is_default=True)
        redis = LockAwareFakeRedis()
        redis.set(f"profile_connections:{profile.id}", 0)
        mgr = self._make_manager(redis)

        content = MagicMock()
        content.uuid = "uuid-retry-reset"
        content.name = "Movie"
        request = MagicMock()
        request.META = {}

        opens = []

        def get_stream(*args, **kwargs):
            rh = kwargs.get("range_header")
            if rh is None:
                for a in reversed(args):
                    if isinstance(a, (str, type(None))):
                        rh = a
                        break
            opens.append(rh)
            upstream = MagicMock()
            n = len(opens)

            if n == 1:
                def phase1(chunk_size=8192):
                    yield b"a"
                    raise requests.exceptions.ReadTimeout("stall 1")

                upstream.iter_content.side_effect = phase1
            elif n == 2:
                def phase2(chunk_size=8192):
                    yield b"b"
                    raise requests.exceptions.ReadTimeout("stall 2")

                upstream.iter_content.side_effect = phase2
            elif n < 2 + _MAX_CONSECUTIVE_UPSTREAM_RETRIES:
                def fail_now(chunk_size=8192):
                    raise requests.exceptions.ReadTimeout("stall streak")
                    yield  # pragma: no cover

                upstream.iter_content.side_effect = fail_now
            else:
                upstream.iter_content.return_value = [b"c"]
            return upstream

        body = self._run_stream(mgr, redis, profile, content, request, get_stream)

        self.assertEqual(body, b"abc")
        self.assertEqual(len(opens), 2 + _MAX_CONSECUTIVE_UPSTREAM_RETRIES)
        self.assertEqual(int(redis._data.get(f"profile_connections:{profile.id}", 0)), 0)
