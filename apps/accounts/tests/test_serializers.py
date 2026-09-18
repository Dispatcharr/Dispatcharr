from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.vod.models import VODAccessPolicy


class UserSerializerValidationTests(TestCase):
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

    def test_xc_live_refresh_permission_requires_boolean(self):
        serializer = UserSerializer(
            data={
                "username": "refresh-user",
                "password": "testpassword123",
                "custom_properties": {
                    "xc_live_refresh_on_request": "yes",
                },
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("custom_properties", serializer.errors)

    def test_xc_live_refresh_request_interval_is_bounded(self):
        serializer = UserSerializer(
            data={
                "username": "refresh-interval-user",
                "password": "testpassword123",
                "custom_properties": {
                    "xc_live_refresh_request_interval_minutes": -1,
                },
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("custom_properties", serializer.errors)

    def test_xc_live_refresh_wait_settings_are_typed_and_bounded(self):
        serializer = UserSerializer(
            data={
                "username": "refresh-wait-user",
                "password": "testpassword123",
                "custom_properties": {
                    "xc_live_refresh_wait_for_completion": True,
                    "xc_live_refresh_wait_timeout_seconds": 61,
                },
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("custom_properties", serializer.errors)

    def test_user_without_profile_receives_the_default_vod_policy(self):
        serializer = UserSerializer(
            data={
                "username": "vod-user",
                "password": "testpassword123",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertEqual(
            list(user.vod_access_policies.values_list("name", flat=True)),
            ["All"],
        )

    def test_user_can_be_assigned_to_a_reusable_vod_output_profile(self):
        policy = VODAccessPolicy.objects.create(
            name="German HD",
            export_mode="compact",
            hard_constraints={"required_audio_languages": ["ger"]},
        )
        serializer = UserSerializer(
            data={
                "username": "profile-user",
                "password": "testpassword123",
                "vod_policy_id": policy.id,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertEqual(list(user.vod_access_policies.all()), [policy])

    def test_user_rejects_an_inactive_vod_output_profile(self):
        policy = VODAccessPolicy.objects.create(
            name="Inactive profile",
            is_active=False,
        )
        serializer = UserSerializer(
            data={
                "username": "inactive-profile-user",
                "password": "testpassword123",
                "vod_policy_id": policy.id,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("vod_policy_id", serializer.errors)

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
