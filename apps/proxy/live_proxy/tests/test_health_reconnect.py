"""Tests for health-monitor reconnect handling in the live stream manager.

The health monitor flags a previously stable stream that stopped producing data
by setting ``needs_reconnect``. Three things have to happen for that flag to
mean anything:

1. The chunk-reading loop must notice it and yield, instead of staying parked on
   a dead connection.
2. The per-URL retry loop must clear the flag and tear the old socket down before
   opening a new one, so the next ``_process_stream_data`` call does not exit
   immediately and the HTTP reader thread is not orphaned.
3. Each health-driven reconnect counts as a connection failure toward
   ``max_retries`` / the retry window, so a URL that keeps dying eventually
   fails over instead of reconnecting forever.
"""
import time
from unittest.mock import patch

from django.test import TestCase

from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.input.manager import StreamManager


class _Buffer:
    """Buffer stand-in with no redis_client, so run() skips its Redis teardown."""


def _make_manager(**overrides):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = "test-channel"
    sm.channel_name = "Test Channel"
    sm.url = "http://example.com/stream.ts"
    sm.running = True
    sm.connected = True
    sm.stop_requested = False
    sm.needs_reconnect = False
    sm.needs_stream_switch = False
    sm.url_switching = False
    sm.url_switch_start_time = 0
    sm.url_switch_timeout = 10
    sm.transcode = False
    sm.retry_count = 0
    sm.max_retries = 3
    sm._retry_window_seconds = 1800
    sm._last_failure_time = None
    sm._stable_connection_threshold = 30
    sm.current_stream_id = 100
    sm.tried_stream_ids = {100}
    sm._failover_rotation_passes = 0
    sm._rotation_cooldown_until = None
    sm._had_successful_connection = True
    sm.last_data_time = 0.0
    sm._buffer_check_timers = []
    sm.transcode_process_active = False
    sm.buffer = _Buffer()
    for key, value in overrides.items():
        setattr(sm, key, value)
    return sm


class ProcessStreamDataExitTests(TestCase):
    """The chunk loop must yield when the health monitor asks for a reconnect."""

    def test_exits_when_reconnect_is_requested(self):
        sm = _make_manager()
        chunk_calls = []

        def fake_fetch_chunk():
            chunk_calls.append(1)
            if len(chunk_calls) == 3:
                sm.needs_reconnect = True
            if len(chunk_calls) >= 50:
                # Safety valve so a loop that ignores the flag still terminates
                # rather than hanging the test run.
                sm.running = False
            return True

        sm.fetch_chunk = fake_fetch_chunk
        sm._process_stream_data()

        self.assertEqual(len(chunk_calls), 3)
        self.assertFalse(sm.connected)

    def test_keeps_reading_while_no_recovery_is_requested(self):
        sm = _make_manager()
        chunk_calls = []

        def fake_fetch_chunk():
            chunk_calls.append(1)
            if len(chunk_calls) >= 5:
                sm.running = False
            return True

        sm.fetch_chunk = fake_fetch_chunk
        sm._process_stream_data()

        self.assertEqual(len(chunk_calls), 5)


class HealthReconnectRetryLoopTests(TestCase):
    """Health reconnects must close, re-establish, and count toward max_retries."""

    def test_reconnect_closes_and_reestablishes_same_url(self):
        sm = _make_manager()
        events = []

        def fake_establish():
            events.append("establish")
            sm.connected = True
            return True

        def fake_process():
            events.append("process")
            if events.count("process") == 1:
                sm.needs_reconnect = True
            else:
                sm.running = False

        def fake_close_socket():
            events.append("close")
            sm.connected = False

        with patch.object(StreamManager, "_monitor_health"), \
                patch.object(StreamManager, "_ensure_owner_or_stop", return_value=True), \
                patch.object(StreamManager, "_close_all_connections"), \
                patch.object(StreamManager, "_try_next_stream", return_value=False) as try_next, \
                patch("apps.proxy.live_proxy.input.manager.close_old_connections"), \
                patch.object(sm, "_establish_http_connection", side_effect=fake_establish), \
                patch.object(sm, "_process_stream_data", side_effect=fake_process), \
                patch.object(sm, "_close_socket", side_effect=fake_close_socket), \
                patch("apps.proxy.live_proxy.input.manager.gevent.sleep"):
            sm.run()

        # Flag cleared, old connection torn down, same URL reopened, one failure counted.
        self.assertEqual(
            events, ["establish", "process", "close", "establish", "process"]
        )
        self.assertEqual(sm.retry_count, 1)
        self.assertFalse(sm.needs_reconnect)
        try_next.assert_not_called()

    def test_repeated_reconnects_exhaust_retry_budget_and_failover(self):
        sm = _make_manager(max_retries=3)
        events = []

        def fake_establish():
            events.append("establish")
            sm.connected = True
            return True

        def fake_process():
            events.append("process")
            sm.needs_reconnect = True

        def fake_close_socket():
            events.append("close")
            sm.connected = False

        def fake_try_next(reason=None):
            events.append(f"try_next:{reason}")
            sm.running = False
            return False

        with patch.object(StreamManager, "_monitor_health"), \
                patch.object(StreamManager, "_ensure_owner_or_stop", return_value=True), \
                patch.object(StreamManager, "_close_all_connections"), \
                patch.object(StreamManager, "_try_next_stream", side_effect=fake_try_next), \
                patch("apps.proxy.live_proxy.input.manager.close_old_connections"), \
                patch.object(sm, "_establish_http_connection", side_effect=fake_establish), \
                patch.object(sm, "_process_stream_data", side_effect=fake_process), \
                patch.object(sm, "_close_socket", side_effect=fake_close_socket), \
                patch("apps.proxy.live_proxy.input.manager.gevent.sleep"), \
                patch("apps.proxy.live_proxy.input.manager.log_system_event"):
            sm.run()

        # Three health reconnects (close + re-establish each time), then URL failed.
        self.assertEqual(events.count("close"), 3)
        self.assertEqual(events.count("establish"), 3)
        self.assertEqual(sm.retry_count, 3)
        self.assertIn("try_next:max_retries_exceeded", events)
        self.assertFalse(sm.needs_reconnect)

    def test_stream_switch_request_still_reaches_failover(self):
        sm = _make_manager()
        events = []

        def fake_establish():
            events.append("establish")
            sm.connected = True
            return True

        def fake_process():
            events.append("process")
            sm.needs_stream_switch = True

        def fake_try_next(reason=None):
            events.append(f"try_next:{reason}")
            sm.running = False
            return False

        with patch.object(StreamManager, "_monitor_health"), \
                patch.object(StreamManager, "_ensure_owner_or_stop", return_value=True), \
                patch.object(StreamManager, "_close_all_connections"), \
                patch.object(StreamManager, "_try_next_stream", side_effect=fake_try_next), \
                patch("apps.proxy.live_proxy.input.manager.close_old_connections"), \
                patch.object(sm, "_establish_http_connection", side_effect=fake_establish), \
                patch.object(sm, "_process_stream_data", side_effect=fake_process), \
                patch.object(sm, "_close_socket"):
            sm.run()

        self.assertEqual(events, ["establish", "process", "try_next:health_monitor"])
        self.assertEqual(sm.retry_count, 0)


class StartupNoDataSwitchTests(TestCase):
    """Each new connection requests a switch at stream_startup_timeout."""

    def _startup_manager(self, *, silent_for, awaiting_data=True, buffer_index=4):
        sm = _make_manager()
        sm.buffer.index = buffer_index
        sm._connection_awaiting_data = awaiting_data
        sm.connected = True
        sm.running = True
        sm.healthy = True
        sm.url_switching = False
        sm.last_data_time = time.time() - silent_for
        sm.health_check_interval = 5
        return sm

    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    def test_requests_switch_once_past_startup_timeout(self, _startup):
        sm = self._startup_manager(silent_for=8.1)
        self.assertTrue(sm._startup_no_data_switch_due())
        self.assertTrue(sm._request_startup_stream_switch())
        self.assertTrue(sm.needs_stream_switch)
        self.assertFalse(sm.healthy)
        self.assertFalse(sm._request_startup_stream_switch())

    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    def test_does_not_switch_before_startup_timeout(self, _startup):
        sm = self._startup_manager(silent_for=7.9)
        self.assertFalse(sm._startup_no_data_switch_due())

    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    def test_switches_even_when_the_channel_buffer_already_has_data(self, _startup):
        sm = self._startup_manager(silent_for=8.1, buffer_index=4)
        self.assertTrue(sm._startup_no_data_switch_due())

    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    def test_ignores_startup_timeout_after_this_connection_sent_data(self, _startup):
        sm = self._startup_manager(silent_for=30, awaiting_data=False)
        self.assertFalse(sm._startup_no_data_switch_due())

    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    def test_health_poll_wakes_at_startup_deadline(self, _startup):
        sm = self._startup_manager(silent_for=5)
        # 3s left, shorter than the 5s health interval.
        self.assertAlmostEqual(sm._health_poll_interval(time.time()), 3, delta=0.1)

    def test_reconnect_restarts_the_startup_clock(self):
        sm = self._startup_manager(silent_for=30, awaiting_data=False, buffer_index=4)
        sm.needs_stream_switch = True
        before = time.time()
        sm._arm_startup_no_data_clock()
        self.assertGreaterEqual(sm.last_data_time, before)
        self.assertTrue(sm._connection_awaiting_data)
        self.assertFalse(sm.needs_stream_switch)
        self.assertTrue(sm.healthy)

    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    def test_no_startup_switch_once_there_is_nowhere_to_switch(self, _startup):
        sm = self._startup_manager(silent_for=30)
        sm._startup_failover_exhausted = True
        self.assertFalse(sm._startup_no_data_switch_due())
        # Back on the normal health interval, not the 50ms deadline spin.
        self.assertEqual(sm._health_poll_interval(time.time()), 5)

    def test_failed_startup_switch_turns_the_short_clock_off(self):
        sm = _make_manager()
        sm._connection_awaiting_data = True
        sm._startup_failover_exhausted = False
        established = []

        def fake_establish():
            established.append(1)
            sm.connected = True
            sm._arm_startup_no_data_clock()
            return True

        def fake_process():
            if len(established) == 1:
                sm.needs_stream_switch = True
            else:
                sm.running = False

        with patch.object(StreamManager, "_monitor_health"), \
                patch.object(StreamManager, "_ensure_owner_or_stop", return_value=True), \
                patch.object(StreamManager, "_close_all_connections"), \
                patch.object(StreamManager, "_try_next_stream", return_value=False), \
                patch("apps.proxy.live_proxy.input.manager.close_old_connections"), \
                patch.object(sm, "_establish_http_connection", side_effect=fake_establish), \
                patch.object(sm, "_process_stream_data", side_effect=fake_process), \
                patch.object(sm, "_close_socket"):
            sm.run()

        self.assertTrue(sm._startup_failover_exhausted)
        # The reconnect after the failed switch is silent but must not be on the
        # short clock, so the monitor leaves it alone.
        self.assertFalse(sm._startup_switch_enabled())

    def test_first_chunk_turns_the_short_clock_back_on(self):
        sm = _make_manager()
        sm._connection_awaiting_data = True
        sm._startup_failover_exhausted = True
        chunks = []

        def fake_fetch_chunk():
            chunks.append(1)
            if len(chunks) >= 2:
                sm.running = False
            return True

        sm.fetch_chunk = fake_fetch_chunk
        sm._process_stream_data()

        self.assertFalse(sm._connection_awaiting_data)
        self.assertFalse(sm._startup_failover_exhausted)

    def test_new_url_turns_the_short_clock_back_on(self):
        sm = _make_manager()
        sm.socket = None
        sm._startup_failover_exhausted = True
        sm._smoothed_output_bitrate = None
        sm._last_bitrate_db_save_time = 0
        sm._bitrate_warmup_samples = 0
        sm.buffering_timeout_error_stream_id = StreamManager._NO_BUFFERING_TIMEOUT_ERROR

        with patch.object(sm, "_close_connection"), \
                patch("apps.proxy.live_proxy.input.manager.log_system_event"):
            self.assertTrue(sm.update_url("http://example.com/other.ts"))

        self.assertFalse(sm._startup_failover_exhausted)
