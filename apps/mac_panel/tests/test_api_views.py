from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.mac_panel.api_views import _find_playlist_id
from apps.mac_panel.client import MacPanelError
from apps.mac_panel.models import MacPanelDevice

User = get_user_model()


class MacPanelPermissionTests(TestCase):
    """Every route on MacPanelDeviceViewSet is admin-only."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin1", password="testpass123", user_level=User.UserLevel.ADMIN
        )
        self.standard = User.objects.create_user(
            username="standard1", password="testpass123", user_level=User.UserLevel.STANDARD
        )
        self.target_user = User.objects.create_user(
            username="xcuser1", password="testpass123",
            custom_properties={"xc_password": "pw123"},
        )
        self.device = MacPanelDevice.objects.create(
            user=self.target_user,
            panel="iboxx",
            mac_address="aa:bb:cc:dd:ee:ff",
            device_key="devkey",
        )

    def test_list_denied_for_non_admin(self):
        self.client.force_authenticate(user=self.standard)
        response = self.client.get("/api/mac-panel/devices/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_allowed_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/mac-panel/devices/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_denied_for_non_admin(self):
        self.client.force_authenticate(user=self.standard)
        response = self.client.post(
            "/api/mac-panel/devices/",
            {
                "user": self.target_user.id,
                "panel": "iboxx",
                "mac_address": "11:22:33:44:55:66",
                "device_key": "k",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_allowed_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/mac-panel/devices/",
            {
                "user": self.target_user.id,
                "panel": "iboxx",
                "mac_address": "11:22:33:44:55:66",
                "device_key": "k",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_destroy_denied_for_non_admin(self):
        self.client.force_authenticate(user=self.standard)
        response = self.client.delete(f"/api/mac-panel/devices/{self.device.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_destroy_allowed_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(f"/api/mac-panel/devices/{self.device.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_captcha_action_denied_for_non_admin(self):
        self.client.force_authenticate(user=self.standard)
        response = self.client.post(f"/api/mac-panel/devices/{self.device.id}/captcha/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_push_action_denied_for_non_admin(self):
        self.client.force_authenticate(user=self.standard)
        response = self.client.post(f"/api/mac-panel/devices/{self.device.id}/push/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_filter_by_user_query_param(self):
        other_user = User.objects.create_user(username="xcuser2", password="testpass123")
        MacPanelDevice.objects.create(
            user=other_user, panel="cr7", mac_address="22:22:22:22:22:22", device_key="k2"
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f"/api/mac-panel/devices/?user={self.target_user.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [d["id"] for d in response.json()]
        self.assertEqual(ids, [self.device.id])


class MacPanelPushFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin2", password="testpass123", user_level=User.UserLevel.ADMIN
        )
        self.target_user = User.objects.create_user(
            username="xcuser3", password="testpass123",
            custom_properties={"xc_password": "pw123"},
        )
        self.device = MacPanelDevice.objects.create(
            user=self.target_user,
            panel="iboxx",
            mac_address="aa:bb:cc:dd:ee:ff",
            device_key="devkey",
        )
        self.client.force_authenticate(user=self.admin)

    def tearDown(self):
        cache.clear()

    def test_push_without_captcha_and_no_cached_token_returns_428(self):
        response = self.client.post(f"/api/mac-panel/devices/{self.device.id}/push/")
        self.assertEqual(response.status_code, 428)
        self.assertEqual(response.json()["error"], "captcha_required")

    @patch("apps.mac_panel.api_views.MacPanelClient")
    def test_push_with_captcha_logs_in_and_saves(self, mock_client_cls):
        # save_playlist's own response is never trusted for a usable id (the
        # panel's own SPA doesn't read one from it either) — the real id
        # comes from a follow-up list_playlists call, matched by name.
        mock_client = mock_client_cls.return_value
        mock_client.device_login.return_value = {
            "token": "jwt-1", "device": {"_id": "panel-dev-1"},
        }
        mock_client.save_playlist.return_value = {"message": "Playlist saved"}
        mock_client.list_playlists.return_value = {
            "playlists": [{"playlist_name": self.device.playlist_name, "id": "pl-1"}],
        }

        response = self.client.post(
            f"/api/mac-panel/devices/{self.device.id}/push/",
            {"captcha": "ABCD", "captcha_token": "tok-1"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        self.device.refresh_from_db()
        self.assertEqual(self.device.last_push_status, "success")
        self.assertEqual(self.device.last_playlist_id, "pl-1")

    @patch("apps.mac_panel.api_views.MacPanelClient")
    def test_push_succeeds_even_if_playlist_id_lookup_fails(self, mock_client_cls):
        """The list_playlists confirmation step is best-effort — a failure
        there must not turn an otherwise-successful push into an error."""
        mock_client = mock_client_cls.return_value
        mock_client.device_login.return_value = {
            "token": "jwt-1", "device": {"_id": "panel-dev-1"},
        }
        mock_client.save_playlist.return_value = {"message": "Playlist saved"}
        mock_client.list_playlists.side_effect = MacPanelError("temporarily unavailable")

        response = self.client.post(
            f"/api/mac-panel/devices/{self.device.id}/push/",
            {"captcha": "ABCD", "captcha_token": "tok-1"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_push_status, "success")
        self.assertEqual(self.device.last_playlist_id, "")

    @patch("apps.mac_panel.api_views.MacPanelClient")
    def test_push_reuses_cached_token_without_captcha(self, mock_client_cls):
        cache.set(
            f"macpanel:token:{self.device.id}",
            {"jwt": "cached-jwt", "panel_device_id": "panel-dev-1"},
            timeout=60,
        )
        mock_client = mock_client_cls.return_value
        mock_client.save_playlist.return_value = {"message": "Updated"}
        mock_client.list_playlists.return_value = {"playlists": []}

        response = self.client.post(f"/api/mac-panel/devices/{self.device.id}/push/")

        self.assertEqual(response.status_code, 200)
        mock_client.device_login.assert_not_called()
        mock_client.save_playlist.assert_called_once()

    @patch("apps.mac_panel.api_views.MacPanelClient")
    def test_login_failure_surfaces_panel_message(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.device_login.side_effect = MacPanelError("Invalid captcha")

        response = self.client.post(
            f"/api/mac-panel/devices/{self.device.id}/push/",
            {"captcha": "WRONG", "captcha_token": "tok-1"},
            format="json",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "Invalid captcha")

        self.device.refresh_from_db()
        self.assertEqual(self.device.last_push_status, "error")

    @patch("apps.mac_panel.api_views.MacPanelClient")
    def test_expired_cached_token_falls_back_to_captcha_required(self, mock_client_cls):
        cache.set(
            f"macpanel:token:{self.device.id}",
            {"jwt": "stale-jwt", "panel_device_id": "panel-dev-1"},
            timeout=60,
        )
        mock_client = mock_client_cls.return_value
        mock_client.save_playlist.side_effect = MacPanelError("Token expired")

        response = self.client.post(f"/api/mac-panel/devices/{self.device.id}/push/")

        self.assertEqual(response.status_code, 428)
        self.assertEqual(response.json()["error"], "captcha_required")
        self.assertIsNone(cache.get(f"macpanel:token:{self.device.id}"))

    @patch("apps.mac_panel.api_views.MacPanelClient")
    def test_captcha_action_returns_svg_and_token(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.get_captcha.return_value = {"svg": "<svg></svg>", "token": "tok-xyz"}

        response = self.client.post(f"/api/mac-panel/devices/{self.device.id}/captcha/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"svg": "<svg></svg>", "captcha_token": "tok-xyz"})


class FindPlaylistIdTests(TestCase):
    """savePlaylist's response can't be trusted for a usable id — every
    push must resolve it via a follow-up list_playlists call, matched by
    playlist_name. Confirmed live: without this, every push fell back to
    current_playlist_url_id: -1 (create) and silently duplicated the
    playlist on the panel side on every re-push."""

    def test_returns_none_when_playlists_key_missing(self):
        self.assertIsNone(_find_playlist_id({}, "Dispatcharr"))

    def test_returns_none_when_no_name_match(self):
        resp = {"playlists": [{"playlist_name": "Someone Else's List"}]}
        self.assertIsNone(_find_playlist_id(resp, "Dispatcharr"))

    def test_matches_by_playlist_name(self):
        resp = {"playlists": [{"playlist_name": "Dispatcharr", "id": "abc"}]}
        self.assertEqual(_find_playlist_id(resp, "Dispatcharr"), "abc")

    def test_falls_back_to_underscore_id_key(self):
        resp = {"playlists": [{"playlist_name": "Dispatcharr", "_id": "xyz"}]}
        self.assertEqual(_find_playlist_id(resp, "Dispatcharr"), "xyz")

    def test_picks_last_match_when_multiple_share_name(self):
        resp = {"playlists": [
            {"playlist_name": "Dispatcharr", "id": "old"},
            {"playlist_name": "Dispatcharr", "id": "new"},
        ]}
        self.assertEqual(_find_playlist_id(resp, "Dispatcharr"), "new")

    def test_returns_none_when_playlists_is_not_a_list(self):
        self.assertIsNone(_find_playlist_id({"playlists": "unexpected"}, "Dispatcharr"))
