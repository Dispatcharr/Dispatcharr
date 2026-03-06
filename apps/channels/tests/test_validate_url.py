"""Tests for the _validate_url() helper in tasks.py.

Covers:
  - Rejection of None, empty, and non-string inputs
  - Non-HTTP URLs pass through without network requests
  - HTTP(S) URLs validated via HEAD request (2xx/3xx pass, 4xx/5xx fail)
  - Network errors (timeout, connection) treated as failures
  - Per-worker result cache: hits, expiry, eviction
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.channels.tasks import _validate_url, _url_validation_cache, _URL_CACHE_TTL


class ValidateUrlInputTests(TestCase):
    """Input validation — no network requests should be made."""

    def setUp(self):
        _url_validation_cache.clear()

    def test_none_returns_false(self):
        self.assertFalse(_validate_url(None))

    def test_empty_string_returns_false(self):
        self.assertFalse(_validate_url(""))

    def test_non_string_returns_false(self):
        self.assertFalse(_validate_url(123))
        self.assertFalse(_validate_url(["http://example.com"]))

    @patch("apps.channels.tasks.requests.head")
    def test_non_http_url_returns_true_without_request(self, mock_head):
        """file:// and other non-HTTP schemes skip validation."""
        self.assertTrue(_validate_url("file:///local/path.jpg"))
        self.assertTrue(_validate_url("/data/images/poster.jpg"))
        mock_head.assert_not_called()


class ValidateUrlNetworkTests(TestCase):
    """HTTP(S) URL validation via HEAD request."""

    def setUp(self):
        _url_validation_cache.clear()

    @patch("apps.channels.tasks.requests.head")
    def test_200_returns_true(self, mock_head):
        mock_head.return_value = MagicMock(status_code=200)
        self.assertTrue(_validate_url("https://example.com/poster.jpg"))

    @patch("apps.channels.tasks.requests.head")
    def test_302_redirect_returns_true(self, mock_head):
        mock_head.return_value = MagicMock(status_code=302)
        self.assertTrue(_validate_url("https://example.com/redirect"))

    @patch("apps.channels.tasks.requests.head")
    def test_404_returns_false(self, mock_head):
        mock_head.return_value = MagicMock(status_code=404)
        self.assertFalse(_validate_url("https://dead-cdn.com/missing.jpg"))

    @patch("apps.channels.tasks.requests.head")
    def test_500_returns_false(self, mock_head):
        mock_head.return_value = MagicMock(status_code=500)
        self.assertFalse(_validate_url("https://broken.com/error"))

    @patch("apps.channels.tasks.requests.head")
    def test_timeout_returns_false(self, mock_head):
        import requests
        mock_head.side_effect = requests.Timeout("timed out")
        self.assertFalse(_validate_url("https://slow-cdn.com/poster.jpg"))

    @patch("apps.channels.tasks.requests.head")
    def test_connection_error_returns_false(self, mock_head):
        import requests
        mock_head.side_effect = requests.ConnectionError("refused")
        self.assertFalse(_validate_url("https://unreachable.com/poster.jpg"))

    @patch("apps.channels.tasks.requests.head")
    def test_custom_timeout_passed_to_head(self, mock_head):
        mock_head.return_value = MagicMock(status_code=200)
        _validate_url("https://example.com/img.jpg", timeout=10)
        mock_head.assert_called_once_with(
            "https://example.com/img.jpg", timeout=10, allow_redirects=True
        )

    @patch("apps.channels.tasks.requests.get")
    @patch("apps.channels.tasks.requests.head")
    def test_405_falls_back_to_get(self, mock_head, mock_get):
        """When HEAD returns 405, fall back to a ranged GET request."""
        mock_head.return_value = MagicMock(status_code=405)
        mock_resp = MagicMock(status_code=200)
        mock_get.return_value = mock_resp
        self.assertTrue(_validate_url("https://no-head.com/poster.jpg"))
        mock_get.assert_called_once()
        mock_resp.close.assert_called_once()

    @patch("apps.channels.tasks.requests.get")
    @patch("apps.channels.tasks.requests.head")
    def test_405_fallback_get_also_fails(self, mock_head, mock_get):
        """When HEAD returns 405 and GET also fails, return False."""
        mock_head.return_value = MagicMock(status_code=405)
        mock_get.return_value = MagicMock(status_code=403)
        self.assertFalse(_validate_url("https://blocked.com/poster.jpg"))


class ValidateUrlCacheTests(TestCase):
    """Per-worker result caching."""

    def setUp(self):
        _url_validation_cache.clear()

    @patch("apps.channels.tasks.requests.head")
    def test_cache_hit_avoids_second_request(self, mock_head):
        mock_head.return_value = MagicMock(status_code=200)
        url = "https://cached.com/poster.jpg"
        self.assertTrue(_validate_url(url))
        self.assertTrue(_validate_url(url))
        mock_head.assert_called_once()

    @patch("apps.channels.tasks.requests.head")
    def test_cache_hit_returns_false_for_failed_url(self, mock_head):
        mock_head.return_value = MagicMock(status_code=404)
        url = "https://dead.com/missing.jpg"
        self.assertFalse(_validate_url(url))
        self.assertFalse(_validate_url(url))
        mock_head.assert_called_once()

    @patch("apps.channels.tasks.time.monotonic")
    @patch("apps.channels.tasks.requests.head")
    def test_cache_expiry_triggers_new_request(self, mock_head, mock_time):
        """After TTL expires, a new HEAD request is made."""
        mock_head.return_value = MagicMock(status_code=200)
        url = "https://expiring.com/poster.jpg"

        mock_time.return_value = 1000.0
        self.assertTrue(_validate_url(url))
        self.assertEqual(mock_head.call_count, 1)

        # Within TTL — cache hit
        mock_time.return_value = 1000.0 + _URL_CACHE_TTL - 1
        self.assertTrue(_validate_url(url))
        self.assertEqual(mock_head.call_count, 1)

        # Past TTL — new request
        mock_time.return_value = 1000.0 + _URL_CACHE_TTL + 1
        self.assertTrue(_validate_url(url))
        self.assertEqual(mock_head.call_count, 2)

    @patch("apps.channels.tasks.time.monotonic")
    @patch("apps.channels.tasks.requests.head")
    def test_eviction_when_cache_exceeds_limit(self, mock_head, mock_time):
        """Expired entries are evicted when cache grows past 512 entries."""
        mock_head.return_value = MagicMock(status_code=200)

        # Fill cache with 513 entries at time 0
        mock_time.return_value = 0.0
        for i in range(513):
            _url_validation_cache[f"https://fill-{i}.com/img.jpg"] = (True, 0.0)

        # Advance past TTL and add one more — triggers eviction
        mock_time.return_value = _URL_CACHE_TTL + 1
        _validate_url("https://trigger-eviction.com/img.jpg")

        # All 513 old entries expired and should be evicted
        remaining = [k for k in _url_validation_cache if k.startswith("https://fill-")]
        self.assertEqual(len(remaining), 0)
        # The new entry should remain
        self.assertIn("https://trigger-eviction.com/img.jpg", _url_validation_cache)
