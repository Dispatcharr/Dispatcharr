import sys
import os
import importlib
from django.test import SimpleTestCase
from unittest.mock import patch, MagicMock

from redis.exceptions import ConnectionError

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

    def test_aio_mode_calls_flushdb(self):
        """In AIO mode (default), flushdb is called after successful ping."""
        mock_client = MagicMock()
        wait_for_redis = _import_wait_for_redis()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DISPATCHARR_ENV', None)
            with patch('wait_for_redis.client_from_env', return_value=(mock_client, 'localhost:6379')):
                result = wait_for_redis(max_retries=1, retry_interval=0)

        self.assertTrue(result)
        mock_client.flushdb.assert_called_once()

    def test_modular_mode_does_not_call_flushdb(self):
        """In modular mode, flushdb must NOT be called. Selective flush instead."""
        mock_client = MagicMock()
        wait_for_redis = _import_wait_for_redis()

        with patch.dict(os.environ, {'DISPATCHARR_ENV': 'modular'}):
            with patch('wait_for_redis.client_from_env', return_value=(mock_client, 'localhost:6379')):
                with patch('wait_for_redis._flush_non_celery_keys') as mock_selective:
                    result = wait_for_redis(max_retries=1, retry_interval=0)

        self.assertTrue(result)
        mock_client.flushdb.assert_not_called()
        mock_selective.assert_called_once_with(mock_client)

    def test_retries_on_connection_error(self):
        """Should retry on ConnectionError and eventually succeed."""
        mock_client = MagicMock()
        mock_client.ping.side_effect = [
            ConnectionError("refused"),
            ConnectionError("refused"),
            True,
        ]
        wait_for_redis = _import_wait_for_redis()

        with patch('wait_for_redis.client_from_env', return_value=(mock_client, 'localhost:6379')):
            result = wait_for_redis(max_retries=5, retry_interval=0)

        self.assertTrue(result)
        self.assertEqual(mock_client.ping.call_count, 3)

    def test_returns_false_after_max_retries(self):
        """Should return False when max retries are exhausted."""
        mock_client = MagicMock()
        mock_client.ping.side_effect = ConnectionError("refused")
        wait_for_redis = _import_wait_for_redis()

        with patch('wait_for_redis.client_from_env', return_value=(mock_client, 'localhost:6379')):
            result = wait_for_redis(max_retries=2, retry_interval=0)

        self.assertFalse(result)

    def test_unexpected_error_returns_false(self):
        """Generic exceptions should return False immediately."""
        mock_client = MagicMock()
        mock_client.ping.side_effect = RuntimeError("Unexpected")
        wait_for_redis = _import_wait_for_redis()

        with patch('wait_for_redis.client_from_env', return_value=(mock_client, 'localhost:6379')):
            result = wait_for_redis(max_retries=5, retry_interval=0)

        self.assertFalse(result)
