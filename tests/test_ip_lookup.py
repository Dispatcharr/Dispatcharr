"""Tests for stale-while-revalidate public IP lookup in core.api_views (issue #1395)."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests as requests_lib
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from core.api_views import (
    _IP_CACHE_KEY,
    _IP_LOCK_KEY,
    _IP_VERIFY_INTERVAL,
    _perform_ip_lookup,
    environment,
)

LOCMEM_CACHE = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
OLD_RESULT = {
    "public_ip": "1.2.3.4",
    "local_ip": "192.168.1.5",
    "country_code": "US",
    "country_name": "United States",
    "city": "Austin",
}


def _stale_entry():
    return {**OLD_RESULT, "verified_at": time.time() - _IP_VERIFY_INTERVAL - 1}


def _ok_requests_get(url, timeout=5):
    response = MagicMock(status_code=200)
    if "ipify" in url:
        response.json.return_value = {"ip": "5.6.7.8"}
    else:
        response.json.return_value = {
            "country_code": "DE",
            "country_name": "Germany",
            "city": "Berlin",
        }
    return response


@override_settings(CACHES=LOCMEM_CACHE)
@patch("core.api_views.socket.socket", side_effect=Exception("no network"))
@patch("core.utils.send_websocket_update")
class PerformIpLookupTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("core.api_views.requests.get", side_effect=_ok_requests_get)
    def test_successful_revalidation_overwrites_cache_and_pushes(self, _get, mock_ws, _socket):
        cache.set(_IP_CACHE_KEY, _stale_entry(), 3600)
        cache.add(_IP_LOCK_KEY, True, 30)

        before = time.time()
        _perform_ip_lookup()

        stored = cache.get(_IP_CACHE_KEY)
        self.assertEqual(stored["public_ip"], "5.6.7.8")
        self.assertGreaterEqual(stored["verified_at"], before)
        self.assertIsNone(cache.get(_IP_LOCK_KEY))
        mock_ws.assert_called_once()
        pushed = mock_ws.call_args[0][2]
        self.assertEqual(pushed["public_ip"], "5.6.7.8")
        self.assertNotIn("verified_at", pushed)

    @patch("core.api_views.requests.get", side_effect=requests_lib.RequestException)
    def test_failed_revalidation_preserves_last_known_result(self, _get, mock_ws, _socket):
        seeded = _stale_entry()
        cache.set(_IP_CACHE_KEY, seeded, 3600)

        _perform_ip_lookup()

        stored = cache.get(_IP_CACHE_KEY)
        self.assertEqual({k: stored[k] for k in OLD_RESULT}, OLD_RESULT)
        self.assertGreater(stored["verified_at"], seeded["verified_at"])
        self.assertIsNone(cache.get(_IP_LOCK_KEY))
        mock_ws.assert_not_called()

    @patch("core.api_views.requests.get", side_effect=requests_lib.RequestException)
    def test_failed_first_lookup_still_caches_and_pushes(self, _get, mock_ws, _socket):
        _perform_ip_lookup()

        stored = cache.get(_IP_CACHE_KEY)
        self.assertIsNone(stored["public_ip"])
        self.assertIn("verified_at", stored)
        mock_ws.assert_called_once()
        self.assertNotIn("verified_at", mock_ws.call_args[0][2])


@override_settings(CACHES=LOCMEM_CACHE, ENABLE_IP_LOOKUP=True)
@patch("apps.accounts.permissions.network_access_allowed", return_value=True)
@patch(
    "core.api_views.CoreSettings.get_system_settings",
    return_value={"enable_ip_lookup": True},
)
class EnvironmentStaleWhileRevalidateTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = APIRequestFactory()

    def _get_environment(self):
        request = self.factory.get("/api/core/environment/")
        force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
        return environment(request)

    @patch("core.api_views.threading.Thread")
    def test_stale_cache_serves_cached_and_kicks_background_refresh(self, mock_thread, *_):
        cache.set(_IP_CACHE_KEY, _stale_entry(), 3600)

        response = self._get_environment()

        self.assertEqual(response.data["public_ip"], "1.2.3.4")
        self.assertFalse(response.data["ip_lookup_pending"])
        self.assertNotIn("verified_at", response.data)
        mock_thread.assert_called_once_with(target=_perform_ip_lookup, daemon=True)
        mock_thread.return_value.start.assert_called_once()

    @patch("core.api_views.threading.Thread")
    def test_missing_verified_at_counts_as_stale(self, mock_thread, *_):
        cache.set(_IP_CACHE_KEY, OLD_RESULT, 3600)

        response = self._get_environment()

        self.assertEqual(response.data["public_ip"], "1.2.3.4")
        mock_thread.assert_called_once_with(target=_perform_ip_lookup, daemon=True)

    @patch("core.api_views.threading.Thread")
    def test_fresh_cache_does_not_refresh(self, mock_thread, *_):
        cache.set(_IP_CACHE_KEY, {**OLD_RESULT, "verified_at": time.time()}, 3600)

        response = self._get_environment()

        self.assertEqual(response.data["public_ip"], "1.2.3.4")
        mock_thread.assert_not_called()

    @patch("core.api_views.threading.Thread")
    def test_stale_cache_respects_existing_lock(self, mock_thread, *_):
        cache.set(_IP_CACHE_KEY, _stale_entry(), 3600)
        cache.add(_IP_LOCK_KEY, True, 30)

        self._get_environment()

        mock_thread.assert_not_called()

    @patch("core.api_views.threading.Thread")
    def test_cache_miss_path_unchanged(self, mock_thread, *_):
        response = self._get_environment()

        self.assertIsNone(response.data["public_ip"])
        self.assertTrue(response.data["ip_lookup_pending"])
        mock_thread.assert_called_once_with(target=_perform_ip_lookup, daemon=True)

    @patch("core.api_views.threading.Thread")
    def test_db_disabled_never_refreshes(self, mock_thread, mock_settings, _network):
        mock_settings.return_value = {"enable_ip_lookup": False}
        cache.set(_IP_CACHE_KEY, _stale_entry(), 3600)

        response = self._get_environment()

        self.assertFalse(response.data["ip_lookup_enabled"])
        self.assertIsNone(response.data["public_ip"])
        mock_thread.assert_not_called()
