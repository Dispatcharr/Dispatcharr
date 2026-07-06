"""Tests for stale-while-revalidate public IP lookup in core.api_views (issue #1395)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests as requests_lib
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from core.api_views import (
    _IP_CACHE_KEY,
    _IP_FRESH_KEY,
    _IP_LOCK_KEY,
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
        cache.set(_IP_CACHE_KEY, OLD_RESULT, 3600)
        cache.add(_IP_LOCK_KEY, True, 30)

        _perform_ip_lookup()

        self.assertEqual(cache.get(_IP_CACHE_KEY)["public_ip"], "5.6.7.8")
        self.assertTrue(cache.get(_IP_FRESH_KEY))
        self.assertIsNone(cache.get(_IP_LOCK_KEY))
        mock_ws.assert_called_once()
        self.assertEqual(mock_ws.call_args[0][2]["public_ip"], "5.6.7.8")

    @patch("core.api_views.requests.get", side_effect=requests_lib.RequestException)
    def test_failed_revalidation_preserves_last_known_result(self, _get, mock_ws, _socket):
        cache.set(_IP_CACHE_KEY, OLD_RESULT, 3600)

        _perform_ip_lookup()

        self.assertEqual(cache.get(_IP_CACHE_KEY), OLD_RESULT)
        self.assertTrue(cache.get(_IP_FRESH_KEY))
        self.assertIsNone(cache.get(_IP_LOCK_KEY))
        mock_ws.assert_not_called()

    @patch("core.api_views.requests.get", side_effect=requests_lib.RequestException)
    def test_failed_first_lookup_still_caches_and_pushes(self, _get, mock_ws, _socket):
        _perform_ip_lookup()

        self.assertIsNone(cache.get(_IP_CACHE_KEY)["public_ip"])
        self.assertTrue(cache.get(_IP_FRESH_KEY))
        mock_ws.assert_called_once()


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
        cache.set(_IP_CACHE_KEY, OLD_RESULT, 3600)

        response = self._get_environment()

        self.assertEqual(response.data["public_ip"], "1.2.3.4")
        self.assertFalse(response.data["ip_lookup_pending"])
        mock_thread.assert_called_once_with(target=_perform_ip_lookup, daemon=True)
        mock_thread.return_value.start.assert_called_once()

    @patch("core.api_views.threading.Thread")
    def test_fresh_cache_does_not_refresh(self, mock_thread, *_):
        cache.set(_IP_CACHE_KEY, OLD_RESULT, 3600)
        cache.set(_IP_FRESH_KEY, True, 60)

        response = self._get_environment()

        self.assertEqual(response.data["public_ip"], "1.2.3.4")
        mock_thread.assert_not_called()

    @patch("core.api_views.threading.Thread")
    def test_stale_cache_respects_existing_lock(self, mock_thread, *_):
        cache.set(_IP_CACHE_KEY, OLD_RESULT, 3600)
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
        cache.set(_IP_CACHE_KEY, OLD_RESULT, 3600)

        response = self._get_environment()

        self.assertFalse(response.data["ip_lookup_enabled"])
        self.assertIsNone(response.data["public_ip"])
        mock_thread.assert_not_called()
