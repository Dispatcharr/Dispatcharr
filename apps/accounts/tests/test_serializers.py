from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer


class UserSerializerValidationTests(TestCase):
    def test_client_refresh_permission_is_saved_without_retired_wait_settings(self):
        serializer = UserSerializer(data={
            "username": "wait-user",
            "password": "testpassword123",
            "custom_properties": {
                "xc_live_refresh_on_request": True,
                "xc_live_refresh_wait_for_completion": True,
                "xc_live_refresh_wait_timeout_seconds": 20,
            },
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertTrue(user.custom_properties["xc_live_refresh_on_request"])
        self.assertNotIn("xc_live_refresh_wait_for_completion", user.custom_properties)
        self.assertNotIn("xc_live_refresh_wait_timeout_seconds", user.custom_properties)
        self.assertNotIn("xc_live_refresh_request_interval_minutes", user.custom_properties)

    def test_client_refresh_permission_requires_a_boolean(self):
        serializer = UserSerializer(data={
            "username": "wait-user", "password": "testpassword123",
            "custom_properties": {"xc_live_refresh_on_request": "true"},
        })
        self.assertFalse(serializer.is_valid())

    def test_retired_wait_settings_are_removed_on_update(self):
        user = User.objects.create_user(username="wait-user", custom_properties={
            "xc_live_refresh_on_request": True,
            "xc_live_refresh_wait_for_completion": True,
            "xc_live_refresh_wait_timeout_seconds": 60,
            "unrelated": "preserved",
        })
        serializer = UserSerializer(user, data={"custom_properties": {}}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        saved = serializer.save()
        self.assertEqual(saved.custom_properties, {
            "xc_live_refresh_on_request": True,
            "unrelated": "preserved",
        })

    def test_retired_refresh_interval_is_ignored_on_create(self):
        serializer = UserSerializer(data={
            "username": "client-user",
            "password": "testpassword123",
            "custom_properties": {
                "xc_live_refresh_on_request": True,
                "xc_live_refresh_request_interval_minutes": 55,
            },
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertTrue(user.custom_properties["xc_live_refresh_on_request"])
        self.assertNotIn("xc_live_refresh_request_interval_minutes", user.custom_properties)

    def test_username_validation_allows_supported_characters(self):
        serializer = UserSerializer(
            data={
                "username": "joe.smith_123@test-user",
                "password": "testpassword123",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_username_validation_rejects_unsupported_characters(self):
        # Use +, which Django allows but our XC-safe allow-list rejects.
        serializer = UserSerializer(
            data={
                "username": "joe+smith",
                "password": "testpassword123",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("username", serializer.errors)
        self.assertIn(
            "Username may only contain letters, numbers, periods (.), underscores (_), at signs (@), and hyphens (-)",
            str(serializer.errors["username"]),
        )

    def test_xc_password_allows_supported_characters(self):
        serializer = UserSerializer(
            data={
                "username": "joe",
                "password": "testpassword123",
                "custom_properties": {
                    "xc_password": "pass.word_123@test-user",
                },
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_xc_password_rejects_unsupported_characters(self):
        serializer = UserSerializer(
            data={
                "username": "joe",
                "password": "testpassword123",
                "custom_properties": {
                    "xc_password": "pass!word",
                },
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("custom_properties", serializer.errors)
        self.assertIn(
            "XC password may only contain letters, numbers, periods (.), underscores (_), at signs (@), and hyphens (-)",
            str(serializer.errors["custom_properties"]),
        )

    def test_allowed_m3u_profile_ids_accepts_positive_integers(self):
        serializer = UserSerializer(
            data={
                "username": "joe",
                "password": "testpassword123",
                "custom_properties": {"allowed_m3u_profile_ids": [3, 1]},
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_allowed_m3u_profile_ids_accepts_empty_list(self):
        serializer = UserSerializer(
            data={
                "username": "joe",
                "password": "testpassword123",
                "custom_properties": {"allowed_m3u_profile_ids": []},
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_allowed_m3u_profile_ids_rejects_invalid_values(self):
        serializer = UserSerializer(
            data={
                "username": "joe",
                "password": "testpassword123",
                "custom_properties": {"allowed_m3u_profile_ids": [1, "2"]},
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("custom_properties", serializer.errors)
