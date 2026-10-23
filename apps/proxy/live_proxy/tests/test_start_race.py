"""Start-race guards for a brand-new channel.

A new channel writes its first metadata (temp_init, no state), then the owner monitor
and the stream manager's ownership audit run while the channel is still starting and
has no viewers. These tests pin the four guards that keep that window from stopping the
upstream and leaving the channel stuck in connecting:

- the ownership audit does not stop a startup-state channel on the disconnect timer
- the owner monitor treats a state-less metadata hash as initializing
- the ownership failure log names the check instead of claiming ownership was lost
- CONNECTING is written before the stream manager thread can write ERROR
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import ChannelState
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.server import ProxyServer

CHANNEL_ID = "11111111-2222-3333-4444-555555555555"
WORKER = "worker-a:1"


class _FakePipeline:
    """Returns fixed results in the order _evaluate_ownership_from_redis queues them."""

    def __init__(self, results):
        self._results = results

    def exists(self, *args):
        return self

    def scard(self, *args):
        return self

    def get(self, *args):
        return self

    def hget(self, *args):
        return self

    def execute(self):
        return tuple(self._results)


def _make_manager(owner, clients, state, disconnect_value="1000.0"):
    redis_client = MagicMock()
    redis_client.pipeline.return_value = _FakePipeline(
        [0, 1, clients, owner, disconnect_value, state]
    )
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = CHANNEL_ID
    sm.worker_id = WORKER
    sm.stopping = False
    sm.stop_requested = False
    sm.buffer = MagicMock(redis_client=redis_client)
    return sm


class OwnershipAuditStartupTests(SimpleTestCase):
    """The owner branch must not stop a startup-state channel on the disconnect timer."""

    def _audit(self, **kwargs):
        sm = _make_manager(**kwargs)
        with patch(
            "apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay",
            return_value=0,
        ):
            return sm._evaluate_ownership_from_redis(sm.buffer.redis_client)

    def test_startup_states_with_no_clients_keep_upstream(self):
        for state in ChannelState.STARTUP:
            with self.subTest(state=state):
                self.assertTrue(self._audit(owner=WORKER, clients=0, state=state))

    def test_buffering_with_no_clients_stops_on_disconnect_timer(self):
        self.assertFalse(
            self._audit(owner=WORKER, clients=0, state=ChannelState.BUFFERING)
        )

    def test_active_channel_with_no_clients_still_stops_on_disconnect_timer(self):
        self.assertFalse(
            self._audit(owner=WORKER, clients=0, state=ChannelState.ACTIVE)
        )

    def test_missing_state_with_no_clients_still_stops_on_disconnect_timer(self):
        self.assertFalse(self._audit(owner=WORKER, clients=0, state=None))

    def test_clients_present_keeps_upstream(self):
        self.assertTrue(
            self._audit(owner=WORKER, clients=2, state=ChannelState.ACTIVE)
        )

    def test_other_owner_stops_and_logs_both_workers(self):
        with self.assertLogs(level="WARNING") as logs:
            result = self._audit(owner="worker-b:1", clients=0, state=ChannelState.ACTIVE)
        self.assertFalse(result)
        self.assertTrue(
            any("worker-b:1" in line and WORKER in line for line in logs.output),
            logs.output,
        )


class MonitorChannelStateTests(SimpleTestCase):
    def test_missing_or_empty_metadata_is_unknown(self):
        self.assertEqual(ProxyServer._monitor_channel_state(None), "unknown")
        self.assertEqual(ProxyServer._monitor_channel_state({}), "unknown")

    def test_explicit_state_is_returned(self):
        self.assertEqual(
            ProxyServer._monitor_channel_state({"state": "active"}), "active"
        )

    def test_first_metadata_without_state_is_initializing(self):
        self.assertEqual(
            ProxyServer._monitor_channel_state({"stream_id": "5", "temp_init": "1.0"}),
            ChannelState.INITIALIZING,
        )

    def test_registry_recreated_hash_without_state_is_unknown(self):
        self.assertEqual(
            ProxyServer._monitor_channel_state({"last_active": "1.0"}), "unknown"
        )

    def test_hash_without_state_or_temp_init_is_unknown(self):
        self.assertEqual(
            ProxyServer._monitor_channel_state({"stream_id": "5"}), "unknown"
        )


class PreActiveStartTimeTests(SimpleTestCase):
    def test_connection_attempt_wins(self):
        metadata = {"init_time": "1.0", "temp_init": "2.0", "state_changed_at": "3.0"}
        self.assertEqual(ProxyServer._pre_active_start_time(metadata, 9.0), 9.0)

    def test_init_time_used_without_attempt(self):
        metadata = {"init_time": "1.0", "temp_init": "2.0", "state_changed_at": "3.0"}
        self.assertEqual(ProxyServer._pre_active_start_time(metadata, None), 1.0)

    def test_temp_init_used_without_init_time(self):
        metadata = {"temp_init": "2.0", "state_changed_at": "3.0"}
        self.assertEqual(ProxyServer._pre_active_start_time(metadata, None), 2.0)

    def test_state_changed_at_used_when_only_that(self):
        metadata = {"state_changed_at": "3.0", "last_active": "4.0"}
        self.assertEqual(ProxyServer._pre_active_start_time(metadata, None), 3.0)

    def test_none_when_nothing_usable(self):
        self.assertIsNone(ProxyServer._pre_active_start_time({}, None))
        self.assertIsNone(ProxyServer._pre_active_start_time(None, None))

    def test_non_numeric_value_is_skipped(self):
        metadata = {"init_time": "not-a-number", "temp_init": "2.0"}
        self.assertEqual(ProxyServer._pre_active_start_time(metadata, None), 2.0)


class EnsureOwnerOrStopTests(SimpleTestCase):
    def test_failed_check_logs_new_message_and_stops(self):
        sm = StreamManager.__new__(StreamManager)
        sm.channel_id = CHANNEL_ID
        sm.worker_id = WORKER
        sm._still_owner = MagicMock(return_value=False)
        sm.stop = MagicMock()

        with self.assertLogs(level="WARNING") as logs:
            self.assertFalse(sm._ensure_owner_or_stop())

        sm._still_owner.assert_called_once_with(force=True)
        sm.stop.assert_called_once_with()
        message = "\n".join(logs.output)
        self.assertIn("failed its ownership check", message)
        self.assertNotIn("lost ownership", message)


class InitializeChannelConnectingOrderTests(SimpleTestCase):
    """CONNECTING must be written before the stream manager thread starts."""

    @patch("apps.proxy.live_proxy.server.close_old_connections")
    @patch("apps.proxy.live_proxy.server.log_system_event")
    @patch("apps.proxy.live_proxy.server.ClientManager")
    @patch("apps.proxy.live_proxy.server.StreamBuffer")
    @patch("apps.proxy.live_proxy.server.StreamManager")
    @patch("apps.proxy.live_proxy.server.RedisClient")
    def test_connecting_is_written_before_thread_start(
        self, _redis_cls, _manager_cls, _buffer_cls, _client_cls, _log_event, _close
    ):
        order = []
        thread = MagicMock()
        thread.start.side_effect = lambda: order.append("thread_start")
        thread_cls = MagicMock(
            side_effect=lambda **kwargs: (order.append("thread_created"), thread)[1]
        )

        proxy = ProxyServer.__new__(ProxyServer)
        proxy.redis_client = MagicMock()
        proxy.redis_client.exists.return_value = False
        proxy.redis_client.hgetall.return_value = {}
        proxy.redis_client.hget.return_value = None
        proxy.stream_buffers = {}
        proxy.client_managers = {}
        proxy.stream_managers = {}
        proxy._live_stream_managers = {}
        proxy._channel_names = {}
        proxy.worker_id = WORKER
        proxy._channel_unavailable_for_new_clients = MagicMock(return_value=False)
        proxy._has_local_upstream_activity = MagicMock(return_value=False)
        proxy.get_channel_owner = MagicMock(return_value=None)
        proxy.try_acquire_ownership = MagicMock(return_value=True)
        proxy.am_i_owner = MagicMock(return_value=True)
        proxy.update_channel_state = MagicMock(
            side_effect=lambda *args, **kwargs: order.append("connecting")
        )
        proxy._local_stop_locks = {}
        proxy._channel_init_locks = {}
        proxy._channels_setting_up = set()
        proxy._stopping_channels = set()

        with patch("apps.proxy.live_proxy.server.threading.Thread", thread_cls):
            result = proxy.initialize_channel(
                "http://example.com/stream.ts", CHANNEL_ID, user_agent="ua", stream_id=1
            )

        self.assertTrue(result)
        proxy.update_channel_state.assert_called_once()
        args = proxy.update_channel_state.call_args.args
        self.assertEqual(args[0], CHANNEL_ID)
        self.assertEqual(args[1], ChannelState.CONNECTING)
        self.assertEqual(order, ["connecting", "thread_created", "thread_start"])
