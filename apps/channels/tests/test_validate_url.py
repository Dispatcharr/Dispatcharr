"""Tests for the _validate_url() helper in tasks.py.

Covers:
  - Rejection of None, empty, and non-string inputs
  - Non-HTTP URLs pass through without network requests
  - HTTP(S) URLs validated via get_with_validated_redirects (2xx/3xx pass, 4xx/5xx fail)
  - Network errors (timeout, connection) treated as failures
  - Per-worker result cache: hits, expiry, eviction
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.channels.tasks import _validate_url, _url_validation_cache, _URL_CACHE_TTL

FETCH = "core.http_security.get_with_validated_redirects"


def _ctx_response(status_code):
    """Response usable as a context manager (matches get_with_validated_redirects)."""
    response = MagicMock(status_code=status_code)
    response.__enter__.return_value = response
    # A truthy __exit__ would swallow exceptions inside the with-block.
    response.__exit__.return_value = False
    return response


class ValidateUrlInputTests(TestCase):
    """Input validation: no network requests should be made."""

    def setUp(self):
        _url_validation_cache.clear()

    def test_none_returns_false(self):
        self.assertFalse(_validate_url(None))

    def test_empty_string_returns_false(self):
        self.assertFalse(_validate_url(""))

    def test_non_string_returns_false(self):
        self.assertFalse(_validate_url(123))
        self.assertFalse(_validate_url(["http://example.com"]))

    @patch(FETCH)
    def test_non_http_url_returns_true_without_request(self, mock_fetch):
        """file:// and other non-HTTP schemes skip validation."""
        self.assertTrue(_validate_url("file:///local/path.jpg"))
        self.assertTrue(_validate_url("/data/images/poster.jpg"))
        mock_fetch.assert_not_called()


class ValidateUrlNetworkTests(TestCase):
    """HTTP(S) URL validation via get_with_validated_redirects."""

    def setUp(self):
        _url_validation_cache.clear()

    @patch(FETCH, return_value=_ctx_response(200))
    def test_200_returns_true(self, _mock_fetch):
        self.assertTrue(_validate_url("https://example.com/poster.jpg"))

    @patch(FETCH, return_value=_ctx_response(302))
    def test_302_redirect_returns_true(self, _mock_fetch):
        # _validate_url treats any status below 400 as reachable.
        self.assertTrue(_validate_url("https://example.com/redirect"))

    @patch(FETCH, return_value=_ctx_response(404))
    def test_404_returns_false(self, _mock_fetch):
        self.assertFalse(_validate_url("https://dead-cdn.com/missing.jpg"))

    @patch(FETCH, return_value=_ctx_response(500))
    def test_500_returns_false(self, _mock_fetch):
        self.assertFalse(_validate_url("https://broken.com/error"))

    @patch(FETCH)
    def test_timeout_returns_false(self, mock_fetch):
        import requests
        mock_fetch.side_effect = requests.Timeout("timed out")
        self.assertFalse(_validate_url("https://slow-cdn.com/poster.jpg"))

    @patch(FETCH)
    def test_connection_error_returns_false(self, mock_fetch):
        import requests
        mock_fetch.side_effect = requests.ConnectionError("refused")
        self.assertFalse(_validate_url("https://unreachable.com/poster.jpg"))

    @patch(FETCH, return_value=_ctx_response(200))
    def test_custom_timeout_passed_to_fetch(self, mock_fetch):
        _validate_url("https://example.com/img.jpg", timeout=10)
        mock_fetch.assert_called_once_with(
            "https://example.com/img.jpg",
            timeout=10,
            method="HEAD",
            allow_private=True,
        )

    @patch(FETCH)
    def test_405_falls_back_to_get(self, mock_fetch):
        """When HEAD returns 405, fall back to a ranged GET request."""
        head = _ctx_response(405)
        get_response = _ctx_response(200)
        mock_fetch.side_effect = [head, get_response]
        self.assertTrue(_validate_url("https://no-head.com/poster.jpg"))
        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(
            mock_fetch.call_args.kwargs,
            {
                "timeout": 4,
                "headers": {"Range": "bytes=0-0"},
                "stream": True,
                "allow_private": True,
            },
        )
        head.__exit__.assert_called_once()
        get_response.__exit__.assert_called_once()

    @patch(FETCH)
    def test_405_fallback_get_also_fails(self, mock_fetch):
        """When HEAD returns 405 and GET also fails, return False."""
        mock_fetch.side_effect = [_ctx_response(405), _ctx_response(403)]
        self.assertFalse(_validate_url("https://blocked.com/poster.jpg"))


class ValidateUrlCacheTests(TestCase):
    """Per-worker result caching."""

    def setUp(self):
        _url_validation_cache.clear()

    @patch(FETCH, return_value=_ctx_response(200))
    def test_cache_hit_avoids_second_request(self, mock_fetch):
        url = "https://cached.com/poster.jpg"
        self.assertTrue(_validate_url(url))
        self.assertTrue(_validate_url(url))
        mock_fetch.assert_called_once()

    @patch(FETCH, return_value=_ctx_response(404))
    def test_cache_hit_returns_false_for_failed_url(self, mock_fetch):
        url = "https://dead.com/missing.jpg"
        self.assertFalse(_validate_url(url))
        self.assertFalse(_validate_url(url))
        mock_fetch.assert_called_once()

    @patch("apps.channels.tasks.time.monotonic")
    @patch(FETCH, return_value=_ctx_response(200))
    def test_cache_expiry_triggers_new_request(self, mock_fetch, mock_time):
        """After TTL expires, a new HEAD request is made."""
        url = "https://expiring.com/poster.jpg"

        mock_time.return_value = 1000.0
        self.assertTrue(_validate_url(url))
        self.assertEqual(mock_fetch.call_count, 1)

        # Within TTL: cache hit
        mock_time.return_value = 1000.0 + _URL_CACHE_TTL - 1
        self.assertTrue(_validate_url(url))
        self.assertEqual(mock_fetch.call_count, 1)

        # Past TTL: new request
        mock_time.return_value = 1000.0 + _URL_CACHE_TTL + 1
        self.assertTrue(_validate_url(url))
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("apps.channels.tasks.time.monotonic")
    @patch(FETCH, return_value=_ctx_response(200))
    def test_eviction_when_cache_exceeds_limit(self, mock_fetch, mock_time):
        """Expired entries are evicted when cache grows past 512 entries."""
        # Fill cache with 513 entries at time 0
        mock_time.return_value = 0.0
        for i in range(513):
            _url_validation_cache[f"https://fill-{i}.com/img.jpg"] = (True, 0.0)

        # Advance past TTL and add one more: triggers eviction
        mock_time.return_value = _URL_CACHE_TTL + 1
        _validate_url("https://trigger-eviction.com/img.jpg")

        # All 513 old entries expired and should be evicted
        remaining = [k for k in _url_validation_cache if k.startswith("https://fill-")]
        self.assertEqual(len(remaining), 0)
        # The new entry should remain
        self.assertIn("https://trigger-eviction.com/img.jpg", _url_validation_cache)
