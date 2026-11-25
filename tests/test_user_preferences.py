import json
from urllib.parse import urlencode

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

User = get_user_model()


class UserPreferencesAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
            user_level=10
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.me_url = "/api/accounts/users/me/"

    def test_get_me_returns_user_data(self):
        """Test GET /me/ returns current user data"""
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "testuser")

    def test_patch_me_updates_custom_properties(self):
        """Test PATCH /me/ updates custom_properties"""
        nav_order = ["channels", "vods", "sources", "guide", "dvr", "stats"]
        data = {
            "custom_properties": {
                "navOrder": nav_order
            }
        }

        response = self.client.patch(self.me_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["custom_properties"]["navOrder"], nav_order)

        # Verify database was updated
        self.user.refresh_from_db()
        self.assertEqual(self.user.custom_properties["navOrder"], nav_order)

    def test_patch_me_nav_order_persists(self):
        """Test navOrder persists and returns correctly"""
        nav_order = ["settings", "channels", "vods"]
        data = {
            "custom_properties": {
                "navOrder": nav_order
            }
        }

        # Update
        self.client.patch(self.me_url, data, format="json")

        # Fetch again
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["custom_properties"]["navOrder"], nav_order)

    def test_patch_me_partial_update_preserves_other_properties(self):
        """Test partial update merges into existing custom_properties, preserving other keys"""
        # Set initial custom_properties
        self.user.custom_properties = {
            "theme": "dark",
            "someOtherSetting": True
        }
        self.user.save()

        # Update only navOrder - send delta, not full object
        nav_order = ["channels", "vods"]
        data = {
            "custom_properties": {
                "navOrder": nav_order
            }
        }

        response = self.client.patch(self.me_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Backend merge semantics: existing keys are preserved
        self.assertEqual(response.data["custom_properties"]["navOrder"], nav_order)
        self.assertEqual(response.data["custom_properties"]["theme"], "dark")
        self.assertEqual(response.data["custom_properties"]["someOtherSetting"], True)

    def test_patch_me_with_empty_nav_order(self):
        """Test PATCH with empty navOrder array"""
        data = {
            "custom_properties": {
                "navOrder": []
            }
        }

        response = self.client.patch(self.me_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["custom_properties"]["navOrder"], [])

    def test_patch_me_updates_first_name(self):
        """Test PATCH /me/ can update other fields like first_name"""
        data = {
            "first_name": "Test"
        }

        response = self.client.patch(self.me_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["first_name"], "Test")

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Test")

    def test_patch_me_unauthenticated_fails(self):
        """Test PATCH /me/ fails for unauthenticated users"""
        self.client.logout()
        unauthenticated_client = APIClient()

        data = {
            "custom_properties": {
                "navOrder": ["channels"]
            }
        }

        response = unauthenticated_client.patch(self.me_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_me_cannot_escalate_privileges(self):
        """PATCH /me/ ignores privilege fields; they are stripped before save."""
        original_level = self.user.user_level

        data = {"user_level": 99, "is_staff": True, "is_superuser": True}
        response = self.client.patch(self.me_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertEqual(self.user.user_level, original_level)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def test_patch_me_cannot_set_catchup_enabled(self):
        """catchup_enabled is admin-managed; /me must not change it."""
        self.user.custom_properties = {"catchup_enabled": False, "theme": "dark"}
        self.user.save(update_fields=["custom_properties"])

        response = self.client.patch(
            self.me_url,
            {"custom_properties": {"catchup_enabled": True, "theme": "light"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        # Stripped from input; existing False preserved. Other props still update.
        self.assertFalse(self.user.custom_properties.get("catchup_enabled"))
        self.assertEqual(self.user.custom_properties.get("theme"), "light")

    def test_patch_me_cannot_set_vod_access_flags(self):
        """vod_movies_enabled / vod_series_enabled are admin-managed; /me must not change them."""
        self.user.custom_properties = {
            "vod_movies_enabled": False,
            "vod_series_enabled": False,
            "theme": "dark",
        }
        self.user.save(update_fields=["custom_properties"])

        response = self.client.patch(
            self.me_url,
            {
                "custom_properties": {
                    "vod_movies_enabled": True,
                    "vod_series_enabled": True,
                    "theme": "light",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.custom_properties.get("vod_movies_enabled"))
        self.assertFalse(self.user.custom_properties.get("vod_series_enabled"))
        self.assertEqual(self.user.custom_properties.get("theme"), "light")

    def test_patch_me_filters_admin_properties_for_all_content_types(self):
        original = {
            "xc_password": "original",
            "allowed_networks": {"XC": "192.168.1.0/24"},
            "catchup_enabled": False,
            "vod_movies_enabled": False,
            "vod_series_enabled": False,
            "dvr_access": "none",
            "allowed_m3u_profile_ids": [1],
            "hide_adult_content": True,
        }
        attempted = {
            "xc_password": "changed",
            "allowed_networks": None,
            "catchup_enabled": True,
            "vod_movies_enabled": True,
            "vod_series_enabled": True,
            "dvr_access": "manage",
            "allowed_m3u_profile_ids": None,
            "hide_adult_content": False,
            "theme": "light",
        }
        self.user.user_level = 1
        for content_type in ("json", "multipart", "form"):
            with self.subTest(content_type=content_type):
                self.user.custom_properties = original.copy()
                self.user.save(update_fields=["custom_properties", "user_level"])
                if content_type == "form":
                    response = self.client.patch(
                        self.me_url, urlencode({"custom_properties": json.dumps(attempted), "user_level": 99}),
                        content_type="application/x-www-form-urlencoded",
                    )
                else:
                    value = attempted if content_type == "json" else json.dumps(attempted)
                    response = self.client.patch(
                        self.me_url, {"custom_properties": value, "user_level": 99}, format=content_type,
                    )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.user.refresh_from_db()
                self.assertEqual(self.user.custom_properties, {**original, "theme": "light"})
                self.assertEqual(self.user.user_level, 1)
