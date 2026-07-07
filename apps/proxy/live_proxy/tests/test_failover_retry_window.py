"""Tests for connection retry idle reset and stable-playback failover reset."""
import time

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

    def test_clear_connection_failure_history(self):
        sm = _make_manager()
        sm._record_connection_failure()
        sm._record_connection_failure()
        sm._clear_connection_failure_history()
        self.assertEqual(sm.retry_count, 0)
        self.assertIsNone(sm._last_failure_time)


class FailoverConfigDefaultsTests(SimpleTestCase):
    def test_retry_window_default(self):
        self.assertEqual(ConfigHelper.retry_window_seconds(), 1800)

    def test_stable_connection_threshold_default(self):
        self.assertEqual(ConfigHelper.stable_connection_threshold(), 30)
