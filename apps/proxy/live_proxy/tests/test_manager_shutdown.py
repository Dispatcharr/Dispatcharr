"""Intentional shutdown must not publish a stream failure during cleanup."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer


class StreamManagerShutdownTests(TestCase):
    def setUp(self):
        self.redis = Mock()
        self.redis.get.return_value = b'test-worker'
        self.redis.hget.return_value = ChannelState.CONNECTING.encode()
        self.buffer = SimpleNamespace(
            channel_id='test-shutdown', redis_client=self.redis, stopping=False,
        )
        self.manager = StreamManager(
            self.buffer.channel_id, 'http://example.com/stream.ts', self.buffer,
            stream_id=1, worker_id='test-worker', channel_name='Shutdown test',
        )
        self.manager.max_retries = 1
        self.server = SimpleNamespace(
            stream_managers={self.manager.channel_id: self.manager},
            _live_stream_managers={self.manager.channel_id: self.manager},
            stream_buffers={self.manager.channel_id: self.buffer},
        )
        self.enterContext(patch.object(ProxyServer, 'get_instance', return_value=self.server))
        self.enterContext(patch.object(self.manager, '_monitor_health'))
        self.enterContext(patch.object(self.manager, '_ensure_owner_or_stop', return_value=True))
        self.enterContext(patch.object(self.manager, '_close_socket'))
        self.cleanup = self.enterContext(patch.object(self.manager, '_close_all_connections'))
        self.enterContext(patch.object(self.manager, '_try_next_stream_with_cooldown', return_value=False))
        self.enterContext(patch('apps.proxy.live_proxy.input.manager.close_old_connections'))
        self.db_connection = self.enterContext(patch('apps.proxy.live_proxy.input.manager.connection'))
        self.enterContext(patch('apps.proxy.live_proxy.input.manager.log_system_event'))
        self.establish = self.enterContext(
            patch.object(self.manager, '_establish_http_connection', return_value=False)
        )
        self.redis.reset_mock()

    def assert_no_failure_published(self):
        self.redis.hset.assert_not_called()
        self.redis.setex.assert_not_called()
        self.cleanup.assert_called_once_with()
        self.db_connection.close.assert_called_once_with()
        self.assertNotIn(self.manager.channel_id, self.server._live_stream_managers)

    def assert_failure_published(self):
        self.assertFalse(self.manager.stop_requested)
        self.assertEqual(self.manager.retry_count, 1)
        self.assertEqual(
            self.redis.hset.call_args.kwargs['mapping'][ChannelMetadataField.STATE],
            ChannelState.ERROR,
        )
        self.redis.setex.assert_called_once_with(
            RedisKeys.channel_stopping(self.manager.channel_id), 60, 'true',
        )

    def test_stop_cleans_up_without_writing_error_or_stopping_key(self):
        timer = Mock()
        self.manager._buffer_check_timers.append(timer)
        self.establish.return_value = True
        with patch.object(self.manager, '_process_stream_data', side_effect=self.manager.stop):
            self.manager.run()

        self.assertTrue(self.manager.stop_requested)
        timer.cancel.assert_called_once_with()
        self.assertEqual(self.manager._buffer_check_timers, [])
        self.assert_no_failure_published()

    def test_server_shutdown_signal_does_not_publish_failure(self):
        # stop_channel signals before scanning Redis, then joins/stops locally.
        # The manager can exit before the later call to manager.stop().
        def signal_shutdown():
            ProxyServer._signal_upstream_shutdown(self.server, self.manager.channel_id)

        self.establish.return_value = True
        with patch.object(self.manager, '_process_stream_data', side_effect=signal_shutdown):
            self.manager.run()

        self.assertTrue(self.buffer.stopping)
        self.assertTrue(self.manager.stop_requested)
        self.assert_no_failure_published()

    def test_exhausted_retries_still_publish_failure_for_owner(self):
        self.manager.run()
        self.assert_failure_published()

    def test_exhausted_retries_still_publish_failure_after_ownership_expires(self):
        self.redis.get.return_value = None
        self.manager.run()
        self.assert_failure_published()

    def test_failure_does_not_overwrite_a_new_owner(self):
        self.redis.get.return_value = b'new-worker'
        self.manager.run()
        self.assert_no_failure_published()

    def test_failure_does_not_overwrite_ownerless_active_stream(self):
        self.redis.get.return_value = None
        self.redis.hget.return_value = ChannelState.ACTIVE.encode()
        self.manager.run()
        self.assert_no_failure_published()
