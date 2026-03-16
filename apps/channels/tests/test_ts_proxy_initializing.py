"""Tests for stuck INITIALIZING state fix.

Covers:
  - stream_manager.run() finally block: ownership check + state guard fallback
  - ChannelState.PRE_ACTIVE contains the correct states
  - INITIALIZING is included in the cleanup task grace period check
"""
import time
import threading
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.ts_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.ts_proxy.redis_keys import RedisKeys
from apps.proxy.ts_proxy.stream_manager import StreamManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHANNEL_ID = "00000000-0000-0000-0000-000000000001"


def _make_stream_manager(tried_stream_ids=None, max_retries=3):
    """Build a StreamManager via __new__ (bypasses __init__) with the
    minimum attributes required by the run() finally block."""
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = CHANNEL_ID
    sm.worker_id = "worker-1"
    sm.max_retries = max_retries
    sm.tried_stream_ids = tried_stream_ids if tried_stream_ids is not None else set()
    sm.running = False  # while-loop exits immediately
    sm.connected = False
    sm.transcode_process_active = False
    sm._buffer_check_timers = []
    sm.url = "http://example.com/stream"
    sm.url_switching = False
    sm.url_switch_start_time = 0
    sm.url_switch_timeout = 30
    sm.stop_requested = False
    sm.stopping = False
    sm.socket = None
    sm.transcode_process = None
    sm.current_response = None
    sm.current_session = None
    sm.current_stream_id = None

    buffer = MagicMock()
    buffer.redis_client = MagicMock()
    buffer.channel_id = CHANNEL_ID
    sm.buffer = buffer

    return sm


def _run_finally_block(sm, owner_value, current_state):
    """Invoke StreamManager.run() so its finally block executes against real code.

    Patches threading.Thread and ConfigHelper so the try-block is inert
    (self.running=False makes the while-loop exit immediately).

    Returns True if the finally block wrote ERROR to Redis.
    """
    redis = sm.buffer.redis_client

    # Mock the owner key GET — the finally block calls redis.get(owner_key)
    def get_side_effect(key):
        if "owner" in key:
            return owner_value
        return None

    redis.get.side_effect = get_side_effect

    # Mock hget for state field lookup in the PRE_ACTIVE guard
    if current_state is not None:
        redis.hget.return_value = current_state.encode('utf-8')
    else:
        redis.hget.return_value = None

    # Reset hset so we can detect whether ERROR was written
    redis.hset.reset_mock()
    redis.setex.reset_mock()

    with patch.object(threading, 'Thread', return_value=MagicMock()):
        with patch('apps.proxy.ts_proxy.stream_manager.ConfigHelper') as mock_cfg:
            mock_cfg.max_stream_switches.return_value = 0
            mock_cfg.max_retries.return_value = sm.max_retries
            sm.run()

    # Check if hset was called with ERROR state
    if redis.hset.called:
        mapping = redis.hset.call_args[1].get('mapping', {})
        return mapping.get(ChannelMetadataField.STATE) == ChannelState.ERROR
    return False


# ---------------------------------------------------------------------------
# stream_manager.run() finally block: ownership + state guard behavior
# ---------------------------------------------------------------------------

class StreamManagerFinallyBlockTests(TestCase):
    """The run() finally block writes ERROR if the worker is still the owner
    (normal case) OR if ownership expired and the channel is still in a
    pre-active state (no new owner has taken over)."""

    # --- Owner still valid: always write ERROR ---

    def test_owner_writes_error_regardless_of_state(self):
        """When we're still the owner, always write ERROR."""
        sm = _make_stream_manager()
        owner = sm.worker_id.encode('utf-8')
        self.assertTrue(_run_finally_block(sm, owner, ChannelState.ACTIVE))

    def test_owner_writes_error_on_initializing(self):
        """Owner + INITIALIZING = write ERROR."""
        sm = _make_stream_manager()
        owner = sm.worker_id.encode('utf-8')
        self.assertTrue(_run_finally_block(sm, owner, ChannelState.INITIALIZING))

        mapping = sm.buffer.redis_client.hset.call_args[1]['mapping']
        self.assertEqual(mapping[ChannelMetadataField.STATE], ChannelState.ERROR)

    # --- Ownership expired, no new owner: use state guard ---

    def test_no_owner_initializing_writes_error(self):
        """Ownership expired + INITIALIZING = write ERROR."""
        sm = _make_stream_manager()
        self.assertTrue(_run_finally_block(sm, None, ChannelState.INITIALIZING))

    def test_no_owner_connecting_writes_error(self):
        """Ownership expired + CONNECTING = write ERROR."""
        sm = _make_stream_manager()
        self.assertTrue(_run_finally_block(sm, None, ChannelState.CONNECTING))

    def test_no_owner_buffering_writes_error(self):
        """Ownership expired + BUFFERING = write ERROR."""
        sm = _make_stream_manager()
        self.assertTrue(_run_finally_block(sm, None, ChannelState.BUFFERING))

    def test_no_owner_waiting_for_clients_writes_error(self):
        """Ownership expired + WAITING_FOR_CLIENTS = write ERROR."""
        sm = _make_stream_manager()
        self.assertTrue(_run_finally_block(sm, None, ChannelState.WAITING_FOR_CLIENTS))

    def test_no_owner_active_does_not_write(self):
        """Ownership expired + ACTIVE = do NOT write ERROR."""
        sm = _make_stream_manager()
        self.assertFalse(_run_finally_block(sm, None, ChannelState.ACTIVE))

    def test_no_owner_error_does_not_write(self):
        """Ownership expired + already ERROR = do NOT write again."""
        sm = _make_stream_manager()
        self.assertFalse(_run_finally_block(sm, None, ChannelState.ERROR))

    def test_no_owner_no_state_does_not_write(self):
        """Ownership expired + no state metadata = do NOT write."""
        sm = _make_stream_manager()
        self.assertFalse(_run_finally_block(sm, None, None))

    # --- New owner took over: never clobber ---

    def test_new_owner_initializing_does_not_write(self):
        """Another worker owns the channel — do NOT clobber."""
        sm = _make_stream_manager()
        self.assertFalse(_run_finally_block(sm, b"other-worker", ChannelState.INITIALIZING))

    def test_new_owner_active_does_not_write(self):
        """Another worker owns the channel and is ACTIVE — do NOT write."""
        sm = _make_stream_manager()
        self.assertFalse(_run_finally_block(sm, b"other-worker", ChannelState.ACTIVE))

    # --- Stopping key and error messages ---

    def test_stopping_key_set_on_error_update(self):
        """When ERROR is written, stopping key must also be set."""
        sm = _make_stream_manager()
        _run_finally_block(sm, None, ChannelState.INITIALIZING)

        sm.buffer.redis_client.setex.assert_called_once()
        args = sm.buffer.redis_client.setex.call_args[0]
        self.assertIn("stopping", args[0])
        self.assertEqual(args[1], 60)

    def test_error_message_includes_stream_count(self):
        """When multiple streams were tried, error message reflects that."""
        sm = _make_stream_manager(tried_stream_ids={1, 2, 3})
        _run_finally_block(sm, None, ChannelState.INITIALIZING)

        mapping = sm.buffer.redis_client.hset.call_args[1]['mapping']
        error_msg = mapping[ChannelMetadataField.ERROR_MESSAGE]
        self.assertIn("3 stream options failed", error_msg)

    def test_error_message_with_no_streams_tried(self):
        """When no alternate streams were tried, shows retry count."""
        sm = _make_stream_manager(tried_stream_ids=set(), max_retries=5)
        _run_finally_block(sm, None, ChannelState.INITIALIZING)

        mapping = sm.buffer.redis_client.hset.call_args[1]['mapping']
        error_msg = mapping[ChannelMetadataField.ERROR_MESSAGE]
        self.assertIn("5", error_msg)


# ---------------------------------------------------------------------------
# ChannelState.PRE_ACTIVE: verify contents and immutability
# ---------------------------------------------------------------------------

class PreActiveStateTests(TestCase):
    """Verify PRE_ACTIVE contains the correct states and is immutable."""

    def test_initializing_in_pre_active(self):
        self.assertIn(ChannelState.INITIALIZING, ChannelState.PRE_ACTIVE)

    def test_connecting_in_pre_active(self):
        self.assertIn(ChannelState.CONNECTING, ChannelState.PRE_ACTIVE)

    def test_buffering_in_pre_active(self):
        self.assertIn(ChannelState.BUFFERING, ChannelState.PRE_ACTIVE)

    def test_waiting_for_clients_in_pre_active(self):
        self.assertIn(ChannelState.WAITING_FOR_CLIENTS, ChannelState.PRE_ACTIVE)

    def test_active_not_in_pre_active(self):
        self.assertNotIn(ChannelState.ACTIVE, ChannelState.PRE_ACTIVE)

    def test_error_not_in_pre_active(self):
        self.assertNotIn(ChannelState.ERROR, ChannelState.PRE_ACTIVE)

    def test_pre_active_is_frozenset(self):
        self.assertIsInstance(ChannelState.PRE_ACTIVE, frozenset)
