import sys
import os
import importlib
from django.test import SimpleTestCase
from unittest.mock import patch, MagicMock

import redis as redis_module

# Ensure the scripts directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))


def _import_wait_for_redis():
    """Import (or reimport) the wait_for_redis function from scripts/."""
    import wait_for_redis as module
    importlib.reload(module)
    return module.wait_for_redis


class WaitForRedisTests(SimpleTestCase):
    """
    Tests for scripts/wait_for_redis.py.

    Verifies flush behaviour: full flushdb in AIO mode, selective
    (non-Celery) key deletion in modular mode.
    """

    @patch('wait_for_redis.redis.Redis')
    def test_aio_mode_calls_flushdb(self, mock_redis_cls):
        """In AIO mode (default), flushdb is called after successful ping."""
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_cls.return_value = mock_client

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DISPATCHARR_ENV', None)
            wait_for_redis = _import_wait_for_redis()
            result = wait_for_redis(max_retries=1, retry_interval=0)

        self.assertTrue(result)
        mock_client.flushdb.assert_called_once()

    @patch('wait_for_redis._flush_non_celery_keys')
    @patch('wait_for_redis.redis.Redis')
    def test_modular_mode_does_not_call_flushdb(self, mock_redis_cls, mock_selective):
        """In modular mode, flushdb must NOT be called — selective flush instead."""
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_cls.return_value = mock_client

        with patch.dict(os.environ, {'DISPATCHARR_ENV': 'modular'}):
            wait_for_redis = _import_wait_for_redis()
            result = wait_for_redis(max_retries=1, retry_interval=0)

        self.assertTrue(result)
        mock_client.flushdb.assert_not_called()
        mock_selective.assert_called_once_with(mock_client)

    @patch('wait_for_redis.redis.Redis')
    def test_retries_on_connection_error(self, mock_redis_cls):
        """Should retry on ConnectionError and eventually succeed."""
        mock_client = MagicMock()
        mock_client.ping.side_effect = [
            redis_module.exceptions.ConnectionError("refused"),
            redis_module.exceptions.ConnectionError("refused"),
            True,
        ]
        mock_redis_cls.return_value = mock_client

        wait_for_redis = _import_wait_for_redis()
        result = wait_for_redis(max_retries=5, retry_interval=0)

        self.assertTrue(result)
        self.assertEqual(mock_client.ping.call_count, 3)

    @patch('wait_for_redis.redis.Redis')
    def test_returns_false_after_max_retries(self, mock_redis_cls):
        """Should return False when max retries are exhausted."""
        mock_client = MagicMock()
        mock_client.ping.side_effect = redis_module.exceptions.ConnectionError("refused")
        mock_redis_cls.return_value = mock_client

        wait_for_redis = _import_wait_for_redis()
        result = wait_for_redis(max_retries=2, retry_interval=0)

        self.assertFalse(result)

    @patch('wait_for_redis.redis.Redis')
    def test_unexpected_error_returns_false(self, mock_redis_cls):
        """Generic exceptions should return False immediately."""
        mock_client = MagicMock()
        mock_client.ping.side_effect = RuntimeError("unexpected")
        mock_redis_cls.return_value = mock_client

        wait_for_redis = _import_wait_for_redis()
        result = wait_for_redis(max_retries=5, retry_interval=0)

        self.assertFalse(result)
