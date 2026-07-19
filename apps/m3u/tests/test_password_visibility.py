"""M3U account password visibility for admin vs standard users."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountSerializer


class M3UPasswordVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="m3u_pwd_admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
        )
        self.standard = User.objects.create_user(
            username="m3u_pwd_user",
            password="x",
            user_level=User.UserLevel.STANDARD,
        )
        self.account = M3UAccount.objects.create(
            name="XC Acc",
            server_url="http://example.test",
            account_type="XC",
            username="xcuser",
            password="super-secret",
        )
        self.factory = APIRequestFactory()

    def test_admin_sees_password(self):
        request = self.factory.get("/api/m3u/accounts/")
        request.user = self.admin
        data = M3UAccountSerializer(
            self.account, context={"request": request}
        ).data
        self.assertEqual(data.get("password"), "super-secret")

    def test_standard_user_does_not_see_password(self):
        request = self.factory.get("/api/m3u/accounts/")
        request.user = self.standard
        data = M3UAccountSerializer(
            self.account, context={"request": request}
        ).data
        self.assertNotIn("password", data)
