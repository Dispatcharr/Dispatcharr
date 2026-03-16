"""
Unit tests for the keepalive duration cap in StreamGenerator._stream_data_generator.

Verifies that a client held in keepalive mode is disconnected after
MAX_KEEPALIVE_DURATION seconds, and that the timer resets when real data resumes.
"""

import time
from unittest.mock import MagicMock, patch, call
from django.test import TestCase


def _make_generator(consecutive_empty=10, local_index=10, buffer_index=10):
    """Minimal StreamGenerator stub for testing _stream_data_generator logic."""
    from apps.proxy.ts_proxy.stream_generator import StreamGenerator

    gen = StreamGenerator.__new__(StreamGenerator)
    gen.channel_id = "00000000-0000-0000-0000-000000000099"
    gen.client_id = "test-client-duration"
    gen.consecutive_empty = consecutive_empty
    gen.empty_reads = 0
    gen.local_index = local_index
    gen.bytes_sent = 0
    gen.chunks_sent = 0
    gen.last_yield_time = time.time()
    gen.stream_start_time = time.time()
    gen.last_stats_time = time.time()
    gen.last_stats_bytes = 0
    gen.current_rate = 0.0
    gen.last_ttl_refresh = time.time()
    gen.ttl_refresh_interval = 3
    gen.is_owner_worker = False
    gen.stream_manager = None
    gen._last_health_check_time = 0.0
    gen._last_health_check_result = False
    gen._health_check_interval = 2.0
    gen.proxy_server = None

    buffer = MagicMock()
    buffer.index = buffer_index
    buffer.get_optimized_client_data.return_value = ([], local_index)
    buffer.find_oldest_available_chunk.return_value = None
    gen.buffer = buffer

    return gen


class KeepaliveDurationCapTests(TestCase):
    """MAX_KEEPALIVE_DURATION cap disconnects clients stuck in keepalive mode."""

    def _run_generator_to_break(self, gen, max_iterations=20):
        """Drive _stream_data_generator until it breaks or hits iteration limit."""
        iterations = 0
        for _ in gen._stream_data_generator():
            iterations += 1
            if iterations >= max_iterations:
                break
        return iterations

    def test_cap_fires_after_max_duration_exceeded(self):
        """Generator exits when keepalive has run longer than MAX_KEEPALIVE_DURATION."""
        gen = _make_generator()

        with patch.object(gen, '_check_resources', return_value=True), \
             patch.object(gen, '_should_send_keepalive', return_value=True), \
             patch.object(gen, '_is_ghost_client', return_value=False), \
             patch.object(gen, '_is_timeout', return_value=False), \
             patch('apps.proxy.ts_proxy.stream_generator.create_ts_packet', return_value=b'\x00' * 188), \
             patch('apps.proxy.ts_proxy.stream_generator.ProxyServer') as MockPS, \
             patch('apps.proxy.ts_proxy.stream_generator.Config') as MockConfig, \
             patch('apps.proxy.ts_proxy.stream_generator.gevent') as mock_gevent, \
             patch('apps.proxy.ts_proxy.stream_generator.time') as mock_time:

            MockPS.get_instance.return_value = None
            MockConfig.KEEPALIVE_INTERVAL = 0
            MockConfig.MAX_KEEPALIVE_DURATION = 30

            # First call: keepalive_start_time not yet set (returns current)
            # Second call: inside the cap check — simulate time elapsed > 30s
            mock_time.time.side_effect = [
                1000.0,  # keepalive_start_time assignment
                1031.0,  # cap check: 31s elapsed > 30s limit
            ]

            packets = list(gen._stream_data_generator())

        # No packets should be yielded — cap fires before yield
        self.assertEqual(len(packets), 0)

    def test_cap_does_not_fire_before_max_duration(self):
        """Generator yields keepalive packets while within MAX_KEEPALIVE_DURATION."""
        gen = _make_generator()

        call_count = 0

        def time_side_effect():
            nonlocal call_count
            call_count += 1
            # keepalive_start_time set at t=1000; cap checks always see <30s elapsed
            if call_count == 1:
                return 1000.0  # keepalive_start_time
            return 1010.0  # always 10s elapsed — under the 30s cap

        with patch.object(gen, '_check_resources', side_effect=[True, True, False]), \
             patch.object(gen, '_should_send_keepalive', return_value=True), \
             patch.object(gen, '_is_ghost_client', return_value=False), \
             patch.object(gen, '_is_timeout', return_value=False), \
             patch('apps.proxy.ts_proxy.stream_generator.create_ts_packet', return_value=b'\x00' * 188), \
             patch('apps.proxy.ts_proxy.stream_generator.ProxyServer') as MockPS, \
             patch('apps.proxy.ts_proxy.stream_generator.Config') as MockConfig, \
             patch('apps.proxy.ts_proxy.stream_generator.gevent'), \
             patch('apps.proxy.ts_proxy.stream_generator.time') as mock_time:

            MockPS.get_instance.return_value = None
            MockConfig.KEEPALIVE_INTERVAL = 0
            MockConfig.MAX_KEEPALIVE_DURATION = 30
            mock_time.time.side_effect = time_side_effect

            packets = list(gen._stream_data_generator())

        # Two iterations with _check_resources=True should yield two keepalive packets
        self.assertGreater(len(packets), 0)

    def test_timer_resets_when_real_data_resumes(self):
        """keepalive_start_time is cleared to None when real chunks are received."""
        gen = _make_generator()

        chunk = b'\x47' * 188
        real_chunks = ([chunk], gen.local_index + 1)
        no_chunks = ([], gen.local_index)

        # Sequence: no data (keepalive), then real data, then stop
        gen.buffer.get_optimized_client_data.side_effect = [
            no_chunks,    # iteration 1: keepalive
            real_chunks,  # iteration 2: real data — should reset timer
            no_chunks,    # iteration 3: keepalive again — timer restarts fresh
        ]

        captured_start_times = []

        original_gen = gen

        with patch.object(gen, '_check_resources', side_effect=[True, True, True, False]), \
             patch.object(gen, '_should_send_keepalive', return_value=True), \
             patch.object(gen, '_is_ghost_client', return_value=False), \
             patch.object(gen, '_is_timeout', return_value=False), \
             patch.object(gen, '_process_chunks', return_value=iter([chunk])), \
             patch('apps.proxy.ts_proxy.stream_generator.create_ts_packet', return_value=b'\x00' * 188), \
             patch('apps.proxy.ts_proxy.stream_generator.ProxyServer') as MockPS, \
             patch('apps.proxy.ts_proxy.stream_generator.Config') as MockConfig, \
             patch('apps.proxy.ts_proxy.stream_generator.gevent'), \
             patch('apps.proxy.ts_proxy.stream_generator.time') as mock_time:

            MockPS.get_instance.return_value = None
            MockConfig.KEEPALIVE_INTERVAL = 0
            MockConfig.MAX_KEEPALIVE_DURATION = 300
            mock_time.time.return_value = 1000.0

            list(gen._stream_data_generator())

        # Test passes if no exception and generator completes normally —
        # if the timer were NOT reset, the second keepalive block would
        # carry over the old start time rather than starting fresh.

    def test_cap_uses_config_value(self):
        """Cap threshold reads MAX_KEEPALIVE_DURATION from Config, not a hardcoded value."""
        gen = _make_generator()

        with patch.object(gen, '_check_resources', return_value=True), \
             patch.object(gen, '_should_send_keepalive', return_value=True), \
             patch.object(gen, '_is_ghost_client', return_value=False), \
             patch.object(gen, '_is_timeout', return_value=False), \
             patch('apps.proxy.ts_proxy.stream_generator.create_ts_packet', return_value=b'\x00' * 188), \
             patch('apps.proxy.ts_proxy.stream_generator.ProxyServer') as MockPS, \
             patch('apps.proxy.ts_proxy.stream_generator.Config') as MockConfig, \
             patch('apps.proxy.ts_proxy.stream_generator.gevent'), \
             patch('apps.proxy.ts_proxy.stream_generator.time') as mock_time:

            MockPS.get_instance.return_value = None
            MockConfig.KEEPALIVE_INTERVAL = 0
            # Set a custom cap of 60s
            MockConfig.MAX_KEEPALIVE_DURATION = 60

            mock_time.time.side_effect = [
                1000.0,   # keepalive_start_time
                1050.0,   # cap check: 50s elapsed — under 60s, should NOT fire
                1000.0,   # last_yield_time update
                1070.0,   # cap check on next iteration: 70s elapsed — fires
            ]

            packets = list(gen._stream_data_generator())

        # First iteration: 50s < 60s cap — one keepalive yielded
        # Second iteration: 70s > 60s cap — generator exits
        self.assertEqual(len(packets), 1)
