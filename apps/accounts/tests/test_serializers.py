from django.test import TestCase

from apps.accounts.serializers import UserSerializer


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
