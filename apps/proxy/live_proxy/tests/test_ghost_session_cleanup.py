"""
Ghost session cleanup: a channel stuck in a pre-active state (initializing/
connecting) with no ownership lock must be detected as dead, reaped by the
orphan watchdog, and never attached to by new clients.

Regression tests for the failure mode where an initialization that dies
between the early metadata write and stream manager creation leaves immortal
'initializing' metadata that all future play requests attach to and stall on.
"""

import time
from unittest.mock import MagicMock, patch

from django.http import StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase


def make_proxy_server(redis_client):
    """Build a ProxyServer without running __init__ (no threads, no Redis)."""
    from apps.proxy.live_proxy.server import ProxyServer

    server = ProxyServer.__new__(ProxyServer)
    server.redis_client = redis_client
    server.stream_managers = {}
    server.stream_buffers = {}
    server.client_managers = {}
    server.output_managers = {}
    server.profile_managers = {}
    server.profile_buffers = {}
    server._channel_names = {}
    server._stopping_channels = set()
    server._stopping_since = {}
    server._local_stop_locks = {}
    server._live_stream_managers = {}
    server.worker_id = "test-host:1"
    return server


GRACE_PATCH = patch(
    "apps.proxy.live_proxy.server.ConfigHelper.channel_init_grace_period",
    return_value=60,
)

CHANNEL_ID = "11111111-2222-3333-4444-555555555555"


class IsStalePreActiveTests(SimpleTestCase):
    def setUp(self):
        self.grace = GRACE_PATCH.start()
        self.addCleanup(GRACE_PATCH.stop)

    def _ghost_metadata(self, state="initializing", age=3600):
        return {"state": state, "init_time": str(time.time() - age)}

    def test_stale_when_no_owner_lock_and_old(self):
        redis = MagicMock()
        redis.exists.return_value = False  # no ownership lock
        server = make_proxy_server(redis)

        self.assertTrue(server.is_stale_pre_active(CHANNEL_ID, self._ghost_metadata()))

    def test_not_stale_when_owner_lock_exists(self):
        redis = MagicMock()
        redis.exists.return_value = True  # ownership lock present
        server = make_proxy_server(redis)

        self.assertFalse(server.is_stale_pre_active(CHANNEL_ID, self._ghost_metadata()))

    def test_not_stale_for_active_state(self):
        redis = MagicMock()
        redis.exists.return_value = False
        server = make_proxy_server(redis)

        self.assertFalse(
            server.is_stale_pre_active(CHANNEL_ID, self._ghost_metadata(state="active"))
        )

    def test_not_stale_when_init_is_recent(self):
        redis = MagicMock()
        redis.exists.return_value = False
        server = make_proxy_server(redis)

        self.assertFalse(
            server.is_stale_pre_active(CHANNEL_ID, self._ghost_metadata(age=5))
        )

    def test_not_stale_with_local_stream_manager(self):
        redis = MagicMock()
        redis.exists.return_value = False
        server = make_proxy_server(redis)
        server.stream_managers[CHANNEL_ID] = object()

        self.assertFalse(
            server.is_stale_pre_active(CHANNEL_ID, self._ghost_metadata())
        )

    def test_stale_when_no_timestamps_at_all(self):
        redis = MagicMock()
        redis.exists.return_value = False
        server = make_proxy_server(redis)

        self.assertTrue(server.is_stale_pre_active(CHANNEL_ID, {"state": "connecting"}))

    def test_respects_custom_max_age(self):
        redis = MagicMock()
        redis.exists.return_value = False
        server = make_proxy_server(redis)
        metadata = self._ghost_metadata(age=90)

        self.assertTrue(server.is_stale_pre_active(CHANNEL_ID, metadata, max_age=60))
        self.assertFalse(server.is_stale_pre_active(CHANNEL_ID, metadata, max_age=120))


class MarkInitFailureTests(SimpleTestCase):
    def test_marks_error_state_and_sets_ttl(self):
        redis = MagicMock()
        redis.get.return_value = None  # no owner
        redis.exists.return_value = True
        redis.hget.return_value = "initializing"
        redis.ttl.return_value = -1
        server = make_proxy_server(redis)

        server._mark_init_failure(CHANNEL_ID, "boom")

        redis.hset.assert_called_once()
        mapping = redis.hset.call_args.kwargs["mapping"]
        self.assertEqual(mapping["state"], "error")
        self.assertEqual(mapping["error_message"], "boom")
        redis.expire.assert_called_once()

    def test_does_not_touch_channel_owned_by_other_worker(self):
        redis = MagicMock()
        redis.get.return_value = "other-host:2"
        server = make_proxy_server(redis)

        server._mark_init_failure(CHANNEL_ID, "boom")

        redis.hset.assert_not_called()

    def test_does_not_clobber_active_state(self):
        redis = MagicMock()
        redis.get.return_value = None
        redis.exists.return_value = True
        redis.hget.return_value = "active"
        server = make_proxy_server(redis)

        server._mark_init_failure(CHANNEL_ID, "boom")

        redis.hset.assert_not_called()


class CheckIfChannelExistsGhostTests(SimpleTestCase):
    def setUp(self):
        self.grace = GRACE_PATCH.start()
        self.addCleanup(GRACE_PATCH.stop)

    def test_ghost_channel_is_cleaned_and_reported_missing(self):
        from apps.proxy.live_proxy.redis_keys import RedisKeys

        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        owner_key = RedisKeys.channel_owner(CHANNEL_ID)
        ghost_metadata = {
            "state": "initializing",
            "owner": "alive-worker:9",
            "init_time": str(time.time() - 3600),
        }

        redis = MagicMock()
        redis.exists.side_effect = lambda key: key == metadata_key
        redis.hgetall.return_value = ghost_metadata
        server = make_proxy_server(redis)

        with patch.object(server, "_clean_zombie_channel") as mock_clean:
            self.assertFalse(server.check_if_channel_exists(CHANNEL_ID))
            mock_clean.assert_called_once()
        # Ensure the ownership lock was actually consulted
        redis.exists.assert_any_call(owner_key)

    def test_initializing_channel_with_owner_lock_still_exists(self):
        from apps.proxy.live_proxy.redis_keys import RedisKeys

        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        owner_key = RedisKeys.channel_owner(CHANNEL_ID)
        heartbeat_key = "live:worker:alive-worker:9:heartbeat"
        metadata = {
            "state": "initializing",
            "owner": "alive-worker:9",
            "init_time": str(time.time() - 3600),
        }

        redis = MagicMock()
        redis.exists.side_effect = lambda key: key in (
            metadata_key,
            owner_key,
            heartbeat_key,
        )
        redis.hgetall.return_value = metadata
        server = make_proxy_server(redis)

        with patch.object(server, "_clean_zombie_channel") as mock_clean:
            self.assertTrue(server.check_if_channel_exists(CHANNEL_ID))
            mock_clean.assert_not_called()


class OrphanedMetadataReaperTests(SimpleTestCase):
    def setUp(self):
        self.grace = GRACE_PATCH.start()
        self.addCleanup(GRACE_PATCH.stop)

    def _run_orphan_check(self, *, owner_lock_exists, age=3600, clients=0):
        from apps.proxy.live_proxy.redis_keys import RedisKeys

        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        owner_key = RedisKeys.channel_owner(CHANNEL_ID)
        heartbeat_key = "live:worker:alive-worker:9:heartbeat"
        ghost_metadata = {
            "state": "initializing",
            "owner": "alive-worker:9",
            "init_time": str(time.time() - age),
        }

        redis = MagicMock()
        redis.keys.return_value = [metadata_key]
        redis.hgetall.return_value = ghost_metadata
        redis.scard.return_value = clients

        def exists(key):
            if key == owner_key:
                return owner_lock_exists
            return key in (metadata_key, heartbeat_key)

        redis.exists.side_effect = exists
        server = make_proxy_server(redis)

        with patch.object(server, "_stop_upstream_before_redis_cleanup") as mock_stop, \
                patch.object(server, "_clean_redis_keys") as mock_clean:
            server._check_orphaned_metadata()
        return mock_stop, mock_clean

    def test_reaps_stale_ghost_with_alive_owner_worker(self):
        # Owner worker heartbeat is alive (worker survived, init died) - the
        # reaper must still clean the channel because nobody holds the lock.
        mock_stop, mock_clean = self._run_orphan_check(owner_lock_exists=False)
        mock_stop.assert_called_once_with(CHANNEL_ID)
        mock_clean.assert_called_once_with(CHANNEL_ID)

    def test_keeps_channel_with_owner_lock(self):
        mock_stop, mock_clean = self._run_orphan_check(owner_lock_exists=True)
        mock_stop.assert_not_called()
        mock_clean.assert_not_called()

    def test_keeps_young_initializing_channel(self):
        # Below 2x grace period the watchdog must not fire.
        mock_stop, mock_clean = self._run_orphan_check(
            owner_lock_exists=False, age=30
        )
        mock_stop.assert_not_called()
        mock_clean.assert_not_called()

    def test_keeps_ghost_with_clients_until_they_stall_out(self):
        mock_stop, mock_clean = self._run_orphan_check(
            owner_lock_exists=False, clients=2
        )
        mock_stop.assert_not_called()
        mock_clean.assert_not_called()


class StreamTsGhostRevivalTests(SimpleTestCase):
    """A play request hitting ghost 'initializing' metadata must clean up and
    reinitialize the channel instead of attaching and stalling."""

    def setUp(self):
        self.factory = RequestFactory()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_ghost_initializing_channel_is_reinitialized(
        self,
        mock_proxy_cls,
        _network_ok,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        channel_id = "channel-uuid"

        channel = MagicMock()
        channel.id = 1
        channel.uuid = channel_id
        channel.name = "Test Channel"
        channel.get_stream_profile.return_value.is_redirect.return_value = False
        mock_get_stream_object.return_value = channel

        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False
        mock_channel_service.initialize_channel.return_value = True

        mock_generate_url.return_value = (
            "http://upstream/stream.ts", "UA", False, "profile", True, None,
        )

        proxy_server = MagicMock()
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hgetall.return_value = {
            "state": "initializing",
            "owner": "dead-init-worker:9",
            "init_time": str(time.time() - 3600),
        }
        proxy_server.redis_client.get.return_value = None
        # The ghost detector fires for this channel
        proxy_server.is_stale_pre_active.return_value = True
        proxy_server.check_if_channel_exists.return_value = True
        proxy_server.am_i_owner.return_value = True
        proxy_server.stream_buffers = {channel_id: MagicMock()}
        proxy_server.client_managers = {channel_id: MagicMock()}
        proxy_server.get_buffer.return_value = MagicMock()
        mock_proxy_cls.get_instance.return_value = proxy_server

        def _generate():
            yield b"chunk"

        mock_create_generator.return_value = lambda: _generate()

        request = self.factory.get(f"/proxy/live/{channel_id}/")
        request.user = MagicMock(is_authenticated=False)

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(request, channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        # Ghost must be torn down before reinitialization
        mock_channel_service.stop_channel.assert_called_once_with(channel_id)
        mock_channel_service.initialize_channel.assert_called_once()
        # And a fresh stream URL must have been requested
        mock_generate_url.assert_called()
