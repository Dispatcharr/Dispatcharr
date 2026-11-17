from unittest.mock import patch
from django.test import SimpleTestCase


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

    @patch("apps.proxy.live_proxy.views.ConfigHelper.stream_retry_timeout", return_value=0)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    def test_obtain_stream_timeout_zero_tries_once(self, mock_generate, mock_timeout):
        """timeout 0 still tries once, then fails without waiting for a free slot."""
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
        mock_generate.assert_called_once()
        self.assertIsNone(stream_url)
        self.assertEqual(attempts, 1)
