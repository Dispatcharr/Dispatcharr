"""Tests for connection retry idle reset and stable-playback failover reset."""
import time
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.input.manager import StreamManager

def _make_manager(**overrides):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = "test-channel"
    sm.max_retries = 3
    sm._retry_window_seconds = 1800
    sm._stable_connection_threshold = 30
    sm._last_failure_time = None
    sm.retry_count = 0
    sm.current_stream_id = 100
    sm.tried_stream_ids = {100, 200, 300}
    sm._failover_rotation_passes = 0
    sm._rotation_cooldown_until = None
    sm._had_successful_connection = True
    sm.running = True
    sm.stop_requested = False
    for key, value in overrides.items():
        setattr(sm, key, value)
    return sm


class RetryIdleResetTests(TestCase):
    def test_counter_resets_after_idle_period(self):
        sm = _make_manager(_retry_window_seconds=60)
        sm._last_failure_time = time.time() - 120
        sm.retry_count = 2

        count = sm._record_connection_failure()

        self.assertEqual(count, 1)

    def test_counter_accumulates_within_idle_period(self):
        sm = _make_manager(_retry_window_seconds=1800)
        self.assertEqual(sm._record_connection_failure(), 1)
        self.assertEqual(sm._record_connection_failure(), 2)
        self.assertEqual(sm._record_connection_failure(), 3)
        self.assertFalse(sm.should_retry())

    def test_stable_connection_resets_tried_streams_only(self):
        sm = _make_manager()
        sm._record_connection_failure()
        sm._record_connection_failure()
        sm._note_stable_connection()
        self.assertEqual(sm.retry_count, 2)
        self.assertEqual(sm.tried_stream_ids, {100})
        self.assertEqual(sm._failover_rotation_passes, 0)
        self.assertIsNone(sm._rotation_cooldown_until)

    def test_clear_connection_failure_history(self):
        sm = _make_manager()
        sm._record_connection_failure()
        sm._record_connection_failure()
        sm._clear_connection_failure_history()
        self.assertEqual(sm.retry_count, 0)
        self.assertIsNone(sm._last_failure_time)


class FailoverRotationCooldownTests(TestCase):
    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    def test_arms_cooldown_without_blocking(self, mock_alts):
        sm = _make_manager(
            tried_stream_ids={100, 200},
            current_stream_id=200,
        )
        mock_alts.return_value = [{"stream_id": 100, "profile_id": 1}]

        self.assertFalse(sm._try_next_stream())
        self.assertEqual(sm._failover_rotation_passes, 1)
        self.assertIsNotNone(sm._rotation_cooldown_until)
        self.assertGreater(sm._rotation_cooldown_remaining(), 0)

    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    @patch("apps.proxy.live_proxy.input.manager.get_stream_info_for_switch")
    @patch.object(StreamManager, "update_url", return_value=True)
    def test_wraps_after_cooldown_elapsed(self, mock_update, mock_info, mock_alts):
        sm = _make_manager(
            tried_stream_ids={100, 200},
            current_stream_id=200,
            url="http://current",
            user_agent="ua",
            transcode=False,
            buffer=type("Buf", (), {"redis_client": None})(),
            _failover_rotation_passes=1,
            _rotation_cooldown_until=time.time() - 1,
        )
        mock_alts.return_value = [{"stream_id": 100, "profile_id": 1}]
        mock_info.return_value = {
            "url": "http://first",
            "user_agent": "ua",
            "transcode": False,
            "stream_profile": 1,
        }

        self.assertTrue(sm._try_next_stream())
        self.assertIsNone(sm._rotation_cooldown_until)
        self.assertEqual(sm.current_stream_id, 100)
        mock_update.assert_called_once()

    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    @patch.object(StreamManager, "update_url")
    def test_returns_false_while_cooldown_active(self, mock_update, mock_alts):
        sm = _make_manager(
            tried_stream_ids={100, 200},
            current_stream_id=200,
            _failover_rotation_passes=1,
            _rotation_cooldown_until=time.time() + 30,
        )
        mock_alts.return_value = [{"stream_id": 100, "profile_id": 1}]

        self.assertFalse(sm._try_next_stream())
        mock_update.assert_not_called()

    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    def test_stops_after_rotation_limit(self, mock_alts):
        sm = _make_manager(
            tried_stream_ids={100, 200},
            current_stream_id=200,
            _failover_rotation_passes=10,
        )
        mock_alts.return_value = [{"stream_id": 100, "profile_id": 1}]

        self.assertFalse(sm._try_next_stream())
        self.assertIsNone(sm._rotation_cooldown_until)

    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    def test_startup_does_not_wrap(self, mock_alts):
        sm = _make_manager(
            tried_stream_ids={100, 200},
            current_stream_id=200,
            _had_successful_connection=False,
        )
        mock_alts.return_value = [{"stream_id": 100, "profile_id": 1}]

        self.assertFalse(sm._try_next_stream())
        self.assertEqual(sm._failover_rotation_passes, 0)
        self.assertIsNone(sm._rotation_cooldown_until)

    @patch.object(StreamManager, "_try_next_stream", side_effect=[False, True])
    @patch.object(StreamManager, "_sleep_interruptible", return_value=True)
    def test_with_cooldown_waits_then_retries(self, mock_sleep, mock_try):
        sm = _make_manager(_rotation_cooldown_until=time.time() + 5)

        self.assertTrue(sm._try_next_stream_with_cooldown())
        mock_sleep.assert_called_once()
        self.assertEqual(mock_try.call_count, 2)

    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    @patch.object(StreamManager, "_sleep_interruptible")
    def test_with_cooldown_skips_wait_when_not_armed(self, mock_sleep, mock_try):
        sm = _make_manager(_rotation_cooldown_until=None)

        self.assertFalse(sm._try_next_stream_with_cooldown())
        mock_sleep.assert_not_called()
        mock_try.assert_called_once()

    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    @patch.object(StreamManager, "_sleep_interruptible", return_value=True)
    def test_with_cooldown_skips_retry_if_already_switched(self, mock_sleep, mock_try):
        sm = _make_manager(
            current_stream_id=200,
            _rotation_cooldown_until=time.time() + 5,
        )

        def _sleep(_seconds):
            sm.current_stream_id = 100
            return True

        mock_sleep.side_effect = _sleep

        self.assertTrue(sm._try_next_stream_with_cooldown())
        mock_try.assert_called_once()

    def test_stable_connection_resets_rotation_passes(self):
        sm = _make_manager(
            _failover_rotation_passes=4,
            _rotation_cooldown_until=time.time() + 10,
        )
        sm._note_stable_connection()
        self.assertEqual(sm._failover_rotation_passes, 0)
        self.assertIsNone(sm._rotation_cooldown_until)

    def test_manual_reset_clears_tried_and_rotation_state(self):
        sm = _make_manager(
            tried_stream_ids={100, 200, 300},
            _failover_rotation_passes=7,
            _rotation_cooldown_until=time.time() + 10,
        )
        sm.reset_failover_rotation_state()
        self.assertEqual(sm.tried_stream_ids, set())
        self.assertEqual(sm._failover_rotation_passes, 0)
        self.assertIsNone(sm._rotation_cooldown_until)


class StableBeforeBufferingTests(TestCase):
    """A connection that played well before buffering counts as a fresh rotation."""

    def _buffering_manager(self, healthy_for, **overrides):
        buffering_start = 5000.0
        values = dict(
            connection_start_time=buffering_start - healthy_for,
            buffering_start_time=buffering_start,
            _failover_rotation_passes=3,
            _rotation_cooldown_until=time.time() + 60,
        )
        values.update(overrides)
        return _make_manager(**values)

    def test_stable_connection_resets_rotation_state(self):
        sm = self._buffering_manager(healthy_for=2283.7)

        self.assertTrue(sm._note_stable_before_buffering())

        self.assertEqual(sm.tried_stream_ids, {100})
        self.assertEqual(sm._failover_rotation_passes, 0)
        self.assertIsNone(sm._rotation_cooldown_until)

    def test_threshold_boundary_counts_as_stable(self):
        sm = self._buffering_manager(healthy_for=30)
        self.assertTrue(sm._note_stable_before_buffering())

    def test_connection_unstable_before_buffering_keeps_state(self):
        sm = self._buffering_manager(healthy_for=29.9)

        self.assertFalse(sm._note_stable_before_buffering())

        self.assertEqual(sm.tried_stream_ids, {100, 200, 300})
        self.assertEqual(sm._failover_rotation_passes, 3)
        self.assertIsNotNone(sm._rotation_cooldown_until)

    def test_unknown_connection_start_keeps_state(self):
        sm = self._buffering_manager(healthy_for=2283.7, connection_start_time=0)
        self.assertFalse(sm._note_stable_before_buffering())
        self.assertEqual(sm.tried_stream_ids, {100, 200, 300})

        del sm.connection_start_time
        sm.buffering_start_time = 6000.0
        self.assertFalse(sm._note_stable_before_buffering())
        self.assertEqual(sm.tried_stream_ids, {100, 200, 300})

    def test_no_buffering_start_keeps_state(self):
        sm = self._buffering_manager(healthy_for=2283.7, buffering_start_time=None)
        self.assertFalse(sm._note_stable_before_buffering())
        self.assertEqual(sm.tried_stream_ids, {100, 200, 300})

    def test_resets_once_per_connection(self):
        sm = self._buffering_manager(healthy_for=2283.7)
        self.assertTrue(sm._note_stable_before_buffering())

        # State the throttle depends on, rebuilt by failed switches. A speed
        # recovery starts a new episode on the same connection.
        sm.tried_stream_ids = {100, 200, 300}
        sm._failover_rotation_passes = 1
        sm._rotation_cooldown_until = time.time() + 60
        sm.buffering_start_time = 9000.0

        self.assertFalse(sm._note_stable_before_buffering())

        self.assertEqual(sm.tried_stream_ids, {100, 200, 300})
        self.assertEqual(sm._failover_rotation_passes, 1)
        self.assertIsNotNone(sm._rotation_cooldown_until)

    def test_early_buffering_does_not_block_a_later_stable_episode(self):
        sm = self._buffering_manager(healthy_for=5)
        self.assertFalse(sm._note_stable_before_buffering())
        self.assertEqual(sm.tried_stream_ids, {100, 200, 300})

        # Same connection, now buffered after playing past the threshold.
        sm.buffering_start_time = sm.connection_start_time + 120
        self.assertTrue(sm._note_stable_before_buffering())
        self.assertEqual(sm.tried_stream_ids, {100})

    def test_new_connection_resets_again(self):
        sm = self._buffering_manager(healthy_for=2283.7)
        self.assertTrue(sm._note_stable_before_buffering())

        sm.tried_stream_ids = {100, 200, 300}
        sm.connection_start_time = 8000.0
        sm.buffering_start_time = 8000.0 + 120

        self.assertTrue(sm._note_stable_before_buffering())
        self.assertEqual(sm.tried_stream_ids, {100})


class FailoverConfigDefaultsTests(SimpleTestCase):
    def test_retry_window_default(self):
        self.assertEqual(ConfigHelper.retry_window_seconds(), 1800)

    def test_stable_connection_threshold_default(self):
        self.assertEqual(ConfigHelper.stable_connection_threshold(), 30)

    def test_failover_rotation_cooldown_default(self):
        self.assertEqual(ConfigHelper.failover_rotation_cooldown(), 60)
