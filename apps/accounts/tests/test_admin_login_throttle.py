"""Django admin login shares the JWT login rate-limit bucket."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from rest_framework.test import APIClient

User = get_user_model()


class AdminLoginRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.api = APIClient()
        self.admin_login_url = "/admin/login/"
        self.token_url = "/api/accounts/token/"
        User.objects.create_superuser(
            username="adminuser",
            password="correct-password",
            user_level=10,
        )

    def tearDown(self):
        cache.clear()

    def _admin_login_post(self, password="wrong-password"):
        return self.client.post(
            self.admin_login_url,
            {
                "username": "adminuser",
                "password": password,
                "next": "/admin/",
            },
        )

    def test_fourth_admin_login_post_is_throttled(self):
        for _ in range(3):
            response = self._admin_login_post()
            self.assertNotEqual(response.status_code, 429)

        response = self._admin_login_post()
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

    def test_get_admin_login_does_not_consume_quota(self):
        for _ in range(5):
            response = self.client.get(self.admin_login_url)
            self.assertEqual(response.status_code, 200)

        for _ in range(3):
            response = self._admin_login_post()
            self.assertNotEqual(response.status_code, 429)

        response = self._admin_login_post()
        self.assertEqual(response.status_code, 429)

    def test_admin_and_jwt_login_share_throttle_bucket(self):
        for _ in range(2):
            response = self.api.post(
                self.token_url,
                {"username": "adminuser", "password": "wrong-password"},
                format="json",
            )
            self.assertNotEqual(response.status_code, 429)

        response = self._admin_login_post()
        self.assertNotEqual(response.status_code, 429)

        response = self._admin_login_post()
        self.assertEqual(response.status_code, 429)

    def test_valid_admin_login_still_works_within_limit(self):
        response = self._admin_login_post(password="correct-password")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/admin/"))
