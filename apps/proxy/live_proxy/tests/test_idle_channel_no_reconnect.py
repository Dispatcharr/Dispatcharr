"""A channel nobody watches must not open new upstream connections.

Some providers allow one connection per account and drop the oldest one when
a new one opens. If an idle channel (no client, shutdown delay running)
reconnects or fails over, it can cut the channel someone is watching. When the
upstream of an idle channel needs a new connection, the shutdown delay ends now
instead.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.test import TestCase

from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

CHANNEL_ID = 'idle-channel'


def _manager(redis_client):
    buffer = SimpleNamespace(channel_id=CHANNEL_ID, redis_client=redis_client, stopping=False)
    return StreamManager(
        CHANNEL_ID, 'http://example.com/stream.ts', buffer,
        stream_id=1, worker_id='test-worker', channel_name='Idle test',
    )


def _redis(client_count, disconnect_value, later_client_count=0):
    redis_client = MagicMock()
    pipe = MagicMock()
    pipe.execute.return_value = [client_count, disconnect_value]
    redis_client.pipeline.return_value = pipe
    redis_client.scard.return_value = later_client_count
    return redis_client


@patch('apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay', return_value=60)
class IdleShutdownDeadlineTests(TestCase):
    def test_idle_channel_reports_when_its_shutdown_delay_ends(self, _delay):
        manager = _manager(_redis(0, b'1000.0'))
        self.assertEqual(manager._idle_shutdown_deadline(), 1060.0)

    def test_channel_with_a_viewer_is_not_idle(self, _delay):
        manager = _manager(_redis(1, b'1000.0'))
        self.assertIsNone(manager._idle_shutdown_deadline())

    def test_channel_still_starting_without_disconnect_marker_is_not_idle(self, _delay):
        # Before the first client leaves there is no disconnect marker.
        manager = _manager(_redis(0, None))
        self.assertIsNone(manager._idle_shutdown_deadline())

    def test_redis_errors_keep_the_usual_behavior(self, _delay):
        redis_client = MagicMock()
        redis_client.pipeline.side_effect = RuntimeError('redis down')
        manager = _manager(redis_client)
        self.assertIsNone(manager._idle_shutdown_deadline())


class StopIfIdleTests(TestCase):
    """The idle channel waits without a connection; it never ends the delay early."""

    def setUp(self):
        self.manager = _manager(MagicMock())
        self.sleep = self.enterContext(
            patch('apps.proxy.live_proxy.input.manager.gevent.sleep')
        )

    def test_watched_channel_reconnects_at_once(self):
        with patch.object(self.manager, '_idle_shutdown_deadline', return_value=None):
            self.assertFalse(self.manager._stop_if_idle())
        self.sleep.assert_not_called()

    def test_idle_channel_waits_for_the_coordinated_stop(self):
        def coordinated_stop(_seconds):
            self.manager.stop_requested = True

        self.sleep.side_effect = coordinated_stop
        with patch.object(
            self.manager, '_idle_shutdown_deadline', return_value=time.time() + 60
        ), patch.object(self.manager, '_ensure_owner_or_stop') as ensure:
            self.assertTrue(self.manager._stop_if_idle())

        # The manager does not stop the upstream itself: stop_channel does.
        ensure.assert_not_called()

    def test_viewer_returning_during_the_delay_reconnects(self):
        with patch.object(
            self.manager, '_idle_shutdown_deadline',
            side_effect=[time.time() + 60, time.time() + 60, None],
        ), patch.object(self.manager, '_ensure_owner_or_stop') as ensure:
            self.assertFalse(self.manager._stop_if_idle())

        self.assertEqual(self.sleep.call_count, 2)
        ensure.assert_not_called()

    def test_without_a_coordinated_stop_the_ownership_check_decides(self):
        self.manager._IDLE_STOP_GRACE_SECONDS = 0
        with patch.object(
            self.manager, '_idle_shutdown_deadline', return_value=time.time() - 1
        ), patch.object(self.manager, '_ensure_owner_or_stop', return_value=False) as ensure:
            self.assertTrue(self.manager._stop_if_idle())

        ensure.assert_called_once_with()


class IdleChannelSkipsNewConnectionsTests(TestCase):
    def setUp(self):
        self.redis = Mock()
        self.manager = _manager(self.redis)
        self.server = SimpleNamespace(
            stream_managers={CHANNEL_ID: self.manager},
            _live_stream_managers={CHANNEL_ID: self.manager},
            stream_buffers={CHANNEL_ID: self.manager.buffer},
        )
        self.enterContext(patch.object(ProxyServer, 'get_instance', return_value=self.server))
        self.enterContext(patch.object(self.manager, '_monitor_health'))
        self.enterContext(patch.object(self.manager, '_ensure_owner_or_stop', return_value=True))
        self.enterContext(patch.object(self.manager, '_close_socket'))
        self.enterContext(patch.object(self.manager, '_close_all_connections'))
        self.enterContext(patch('apps.proxy.live_proxy.input.manager.close_old_connections'))
        self.enterContext(patch('apps.proxy.live_proxy.input.manager.connection'))
        self.enterContext(patch('apps.proxy.live_proxy.input.manager.log_system_event'))
        self.enterContext(patch('apps.proxy.live_proxy.input.manager.gevent.sleep'))

    def test_upstream_end_on_idle_channel_does_not_reconnect(self):
        establish = self.enterContext(
            patch.object(self.manager, '_establish_http_connection', return_value=True)
        )
        self.enterContext(patch.object(self.manager, '_process_stream_data'))
        switch = self.enterContext(
            patch.object(self.manager, '_try_next_stream_with_cooldown', return_value=False)
        )
        # Watched at the first attempt, idle once the upstream ends.
        self.enterContext(
            patch.object(self.manager, '_stop_if_idle', side_effect=[False, True])
        )

        self.manager.run()

        establish.assert_called_once_with()
        switch.assert_not_called()

    def test_viewer_leaving_during_backoff_prevents_the_next_attempt(self):
        self.manager.max_retries = 3
        establish = self.enterContext(
            patch.object(self.manager, '_establish_http_connection', return_value=True)
        )
        self.enterContext(patch.object(self.manager, '_process_stream_data'))
        self.enterContext(
            patch.object(self.manager, '_try_next_stream_with_cooldown', return_value=False)
        )
        # First attempt and end of stream: watched. Before the retry: idle.
        self.enterContext(
            patch.object(self.manager, '_stop_if_idle', side_effect=[False, False, True])
        )

        self.manager.run()

        establish.assert_called_once_with()

    def test_upstream_end_on_watched_channel_still_reconnects(self):
        self.manager.max_retries = 2
        establish = self.enterContext(
            patch.object(self.manager, '_establish_http_connection', return_value=True)
        )
        self.enterContext(patch.object(self.manager, '_process_stream_data'))
        self.enterContext(
            patch.object(self.manager, '_try_next_stream_with_cooldown', return_value=False)
        )
        self.enterContext(patch.object(self.manager, '_stop_if_idle', return_value=False))

        self.manager.run()

        self.assertEqual(establish.call_count, 2)

    def test_failover_on_idle_channel_does_not_look_for_another_stream(self):
        # Non-blocking check: _try_next_stream also runs on the stderr thread.
        self.enterContext(
            patch.object(self.manager, '_idle_shutdown_deadline', return_value=time.time() + 60)
        )
        alternates = self.enterContext(
            patch('apps.proxy.live_proxy.input.manager.get_alternate_streams')
        )

        self.assertFalse(self.manager._try_next_stream(reason='health_monitor'))

        alternates.assert_not_called()

    def test_health_reconnect_on_idle_channel_is_skipped(self):
        self.enterContext(patch.object(self.manager, '_stop_if_idle', return_value=True))
        establish = self.enterContext(patch.object(self.manager, '_establish_http_connection'))

        self.assertFalse(self.manager._attempt_reconnect())

        establish.assert_not_called()

    def test_upstream_is_not_opened_when_the_last_viewer_left_during_cleanup(self):
        self.enterContext(
            patch.object(self.manager, '_idle_shutdown_deadline', return_value=time.time() + 60)
        )
        reader = self.enterContext(
            patch('apps.proxy.live_proxy.input.http_streamer.HTTPStreamReader')
        )

        self.assertFalse(self.manager._establish_http_connection())

        reader.assert_not_called()
