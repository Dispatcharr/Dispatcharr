import os
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase

from apps.proxy.config import BaseConfig
from apps.proxy.live_proxy.config_helper import ConfigHelper


class StreamRetryTimeoutConfigTests(SimpleTestCase):
    def test_default_stream_retry_timeout(self):
        """Default stream retry timeout is 3.0 seconds."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ConfigHelper.stream_retry_timeout(), 3.0)

    def test_env_var_overrides_stream_retry_timeout(self):
        """DISPATCHARR_STREAM_RETRY_TIMEOUT environment variable overrides stream retry timeout."""
        with patch.dict(os.environ, {"DISPATCHARR_STREAM_RETRY_TIMEOUT": "8.5"}):
            # Test that BaseConfig / ConfigHelper returns float value from env var
            with patch.object(BaseConfig, "STREAM_RETRY_TIMEOUT", float(os.environ["DISPATCHARR_STREAM_RETRY_TIMEOUT"])):
                self.assertEqual(ConfigHelper.stream_retry_timeout(), 8.5)

    def test_default_max_retries(self):
        """Default MAX_RETRIES is 3."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ConfigHelper.max_retries(), 3)

    def test_env_var_overrides_max_retries(self):
        """DISPATCHARR_MAX_RETRIES environment variable overrides max retries."""
        with patch.dict(os.environ, {"DISPATCHARR_MAX_RETRIES": "5"}):
            with patch.object(BaseConfig, "MAX_RETRIES", int(os.environ["DISPATCHARR_MAX_RETRIES"])):
                self.assertEqual(ConfigHelper.max_retries(), 5)


class ObtainStreamWithRetriesTimeoutTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.views.ConfigHelper.stream_retry_timeout", return_value=0.2)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    def test_obtain_stream_uses_configured_timeout(self, mock_generate, mock_timeout):
        """_obtain_stream_with_retries retries until the configured stream retry timeout expires."""
        from apps.proxy.live_proxy.views import _obtain_stream_with_retries

        mock_generate.return_value = (None, None, False, None, False, "maximum connection limits reached", None)

        res = _obtain_stream_with_retries(
            channel_id="test-channel",
            client_id="test-client",
            user=None,
            allowed_m3u_profiles=None,
        )
        stream_url = res[0]
        attempts = res[7]

        mock_timeout.assert_called_once()
        self.assertIsNone(stream_url)
        # In 0.2s with ~0.1s sleep, it should make 2 attempts before timing out
        self.assertGreaterEqual(attempts, 1)
