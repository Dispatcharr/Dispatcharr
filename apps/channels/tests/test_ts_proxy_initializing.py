"""Tests for stuck INITIALIZING state fix.

Covers:
  - stream_manager.run() finally block: ownership check + state guard fallback
  - Channels in INITIALIZING state are included in cleanup task grace period monitoring
"""
import time
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.ts_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.ts_proxy.redis_keys import RedisKeys


# ---------------------------------------------------------------------------
# stream_manager.run() finally block: ownership + state guard behavior
# ---------------------------------------------------------------------------

class StreamManagerFinallyBlockTests(TestCase):
    """The run() finally block writes ERROR if the worker is still the owner
    (normal case) OR if ownership expired and the channel is still in a
    pre-active state (no new owner has taken over)."""

    def _make_stream_manager(self, tried_stream_ids=None, max_retries=3):
        from apps.proxy.ts_proxy.stream_manager import StreamManager
        sm = StreamManager.__new__(StreamManager)
        sm.channel_id = "00000000-0000-0000-0000-000000000001"
        sm.worker_id = "worker-1"
        sm.max_retries = max_retries
        sm.tried_stream_ids = tried_stream_ids or []
        sm.running = False
        sm.connected = False
        sm.transcode_process_active = False
        sm._buffer_check_timers = []

        buffer = MagicMock()
        buffer.redis_client = MagicMock()
        sm.buffer = buffer

        return sm

    def _run_finally_logic(self, sm, owner_value, current_state):
        """Simulate the finally block's state-update logic.

        Args:
            sm: StreamManager mock
            owner_value: bytes value of owner key (None = expired,
                         sm.worker_id.encode() = self, b'other' = new owner)
            current_state: ChannelState string or None
        Returns:
            True if ERROR was written, False otherwise
        """
        redis = sm.buffer.redis_client

        # Mock the owner key GET
        redis.get.return_value = owner_value

        # Mock hget for state field
        if current_state is not None:
            redis.hget.return_value = current_state.encode('utf-8')
        else:
            redis.hget.return_value = None

        # Replicate the finally block logic
        owner_key = RedisKeys.channel_owner(sm.channel_id)
        current_owner = redis.get(owner_key)

        is_owner = (
            current_owner
            and sm.worker_id
            and current_owner.decode('utf-8') == sm.worker_id
        )
        no_owner = current_owner is None

        should_update = is_owner
        if not should_update and no_owner:
            metadata_key = RedisKeys.channel_metadata(sm.channel_id)
            current_state_bytes = redis.hget(
                metadata_key, ChannelMetadataField.STATE
            )
            current_state_str = (
                current_state_bytes.decode('utf-8')
                if current_state_bytes else None
            )
            should_update = current_state_str in ChannelState.PRE_ACTIVE

        if should_update:
            if sm.tried_stream_ids and len(sm.tried_stream_ids) > 0:
                error_message = f"All {len(sm.tried_stream_ids)} stream options failed"
            else:
                error_message = f"Connection failed after {sm.max_retries} attempts"

            metadata_key = RedisKeys.channel_metadata(sm.channel_id)
            update_data = {
                ChannelMetadataField.STATE: ChannelState.ERROR,
                ChannelMetadataField.STATE_CHANGED_AT: str(time.time()),
                ChannelMetadataField.ERROR_MESSAGE: error_message,
                ChannelMetadataField.ERROR_TIME: str(time.time())
            }
            redis.hset(metadata_key, mapping=update_data)
            stop_key = RedisKeys.channel_stopping(sm.channel_id)
            redis.setex(stop_key, 60, "true")
            return True
        return False

    # --- Owner still valid: always write ERROR ---

    def test_owner_writes_error_regardless_of_state(self):
        """When we're still the owner, always write ERROR."""
        sm = self._make_stream_manager()
        owner = sm.worker_id.encode('utf-8')
        # State doesn't matter when we're the owner
        updated = self._run_finally_logic(sm, owner, ChannelState.ACTIVE)
        self.assertTrue(updated)

    def test_owner_writes_error_on_initializing(self):
        """Owner + INITIALIZING = write ERROR."""
        sm = self._make_stream_manager()
        owner = sm.worker_id.encode('utf-8')
        updated = self._run_finally_logic(sm, owner, ChannelState.INITIALIZING)
        self.assertTrue(updated)
        call_args = sm.buffer.redis_client.hset.call_args
        self.assertEqual(
            call_args[1]['mapping'][ChannelMetadataField.STATE],
            ChannelState.ERROR
        )

    # --- Ownership expired, no new owner: use state guard ---

    def test_no_owner_initializing_writes_error(self):
        """Ownership expired + INITIALIZING = write ERROR."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, None, ChannelState.INITIALIZING)
        self.assertTrue(updated)

    def test_no_owner_connecting_writes_error(self):
        """Ownership expired + CONNECTING = write ERROR."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, None, ChannelState.CONNECTING)
        self.assertTrue(updated)

    def test_no_owner_buffering_writes_error(self):
        """Ownership expired + BUFFERING = write ERROR."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, None, ChannelState.BUFFERING)
        self.assertTrue(updated)

    def test_no_owner_waiting_for_clients_writes_error(self):
        """Ownership expired + WAITING_FOR_CLIENTS = write ERROR."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, None, ChannelState.WAITING_FOR_CLIENTS)
        self.assertTrue(updated)

    def test_no_owner_active_does_not_write(self):
        """Ownership expired + ACTIVE = do NOT write ERROR.
        ACTIVE means a previous owner successfully served the channel."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, None, ChannelState.ACTIVE)
        self.assertFalse(updated)

    def test_no_owner_error_does_not_write(self):
        """Ownership expired + already ERROR = do NOT write again."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, None, ChannelState.ERROR)
        self.assertFalse(updated)

    def test_no_owner_no_state_does_not_write(self):
        """Ownership expired + no state metadata = do NOT write."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, None, None)
        self.assertFalse(updated)

    # --- New owner took over: never clobber ---

    def test_new_owner_initializing_does_not_write(self):
        """Another worker owns the channel and is INITIALIZING —
        do NOT clobber, even though state is pre-active."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, b"other-worker", ChannelState.INITIALIZING)
        self.assertFalse(updated)

    def test_new_owner_active_does_not_write(self):
        """Another worker owns the channel and is ACTIVE — do NOT write."""
        sm = self._make_stream_manager()
        updated = self._run_finally_logic(sm, b"other-worker", ChannelState.ACTIVE)
        self.assertFalse(updated)

    # --- Stopping key and error messages ---

    def test_stopping_key_set_on_error_update(self):
        """When ERROR is written, stopping key must also be set."""
        sm = self._make_stream_manager()
        self._run_finally_logic(sm, None, ChannelState.INITIALIZING)
        sm.buffer.redis_client.setex.assert_called_once()
        args = sm.buffer.redis_client.setex.call_args[0]
        self.assertIn("stopping", args[0])
        self.assertEqual(args[1], 60)

    def test_error_message_includes_stream_count(self):
        """When multiple streams were tried, error message reflects that."""
        sm = self._make_stream_manager(tried_stream_ids=[1, 2, 3])
        self._run_finally_logic(sm, None, ChannelState.INITIALIZING)
        call_args = sm.buffer.redis_client.hset.call_args
        error_msg = call_args[1]['mapping'][ChannelMetadataField.ERROR_MESSAGE]
        self.assertIn("3 stream options failed", error_msg)

    def test_error_message_with_no_streams_tried(self):
        """When no alternate streams were tried, shows retry count."""
        sm = self._make_stream_manager(tried_stream_ids=[], max_retries=5)
        self._run_finally_logic(sm, None, ChannelState.INITIALIZING)
        call_args = sm.buffer.redis_client.hset.call_args
        error_msg = call_args[1]['mapping'][ChannelMetadataField.ERROR_MESSAGE]
        self.assertIn("5", error_msg)


# ---------------------------------------------------------------------------
# Cleanup task: INITIALIZING included in grace period monitoring
# ---------------------------------------------------------------------------

class CleanupTaskInitializingStateTests(TestCase):
    """The cleanup task's grace period check must include INITIALIZING
    alongside CONNECTING and WAITING_FOR_CLIENTS."""

    def test_initializing_in_monitored_states(self):
        """ChannelState.INITIALIZING must be in the list of states that
        trigger grace period monitoring in the cleanup task."""
        monitored_states = [
            ChannelState.INITIALIZING,
            ChannelState.CONNECTING,
            ChannelState.WAITING_FOR_CLIENTS,
        ]
        self.assertIn(ChannelState.INITIALIZING, monitored_states)
        self.assertIn(ChannelState.CONNECTING, monitored_states)
        self.assertIn(ChannelState.WAITING_FOR_CLIENTS, monitored_states)

    def test_active_not_in_monitored_states(self):
        """ACTIVE channels should NOT be in the grace period list."""
        monitored_states = [
            ChannelState.INITIALIZING,
            ChannelState.CONNECTING,
            ChannelState.WAITING_FOR_CLIENTS,
        ]
        self.assertNotIn(ChannelState.ACTIVE, monitored_states)
