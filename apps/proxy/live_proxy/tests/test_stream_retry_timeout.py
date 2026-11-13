from unittest.mock import patch
from django.test import SimpleTestCase

from apps.proxy.config import TSConfig
from apps.proxy.live_proxy.config_helper import ConfigHelper


class StreamRetryTimeoutConfigTests(SimpleTestCase):
    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_default_stream_retry_timeout(self, _mock_settings):
        """Default stream retry timeout is 3 seconds."""
        self.assertEqual(ConfigHelper.stream_retry_timeout(), 3)

    @patch.object(TSConfig, "get_proxy_settings", return_value={"stream_retry_timeout": 15})
    def test_proxy_settings_override_stream_retry_timeout(self, _mock_settings):
        """proxy_settings overrides stream retry timeout."""
        self.assertEqual(ConfigHelper.stream_retry_timeout(), 15)

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_default_max_retries(self, _mock_settings):
        """Default MAX_RETRIES is 3."""
        self.assertEqual(ConfigHelper.max_retries(), 3)

    @patch.object(TSConfig, "get_proxy_settings", return_value={"max_retries": 5})
    def test_proxy_settings_override_max_retries(self, _mock_settings):
        """proxy_settings overrides max retries."""
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
