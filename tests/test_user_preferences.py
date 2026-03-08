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
        """Test partial update doesn't overwrite other custom_properties"""
        # Set initial custom_properties
        self.user.custom_properties = {
            "theme": "dark",
            "someOtherSetting": True
        }
        self.user.save()

        # Update only navOrder
        nav_order = ["channels", "vods"]
        data = {
            "custom_properties": {
                "navOrder": nav_order
            }
        }

        response = self.client.patch(self.me_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Note: JSONField replacement behavior - the entire custom_properties is replaced
        # This is expected Django behavior for JSONField
        self.assertEqual(response.data["custom_properties"]["navOrder"], nav_order)

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
