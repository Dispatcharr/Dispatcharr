from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from unittest.mock import patch

User = get_user_model()


class InitializeSuperuserTests(TestCase):
    """Tests for the initialize_superuser endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/accounts/initialize-superuser/"

    def test_returns_true_when_superuser_exists(self):
        """Superuser with is_superuser=True should be detected"""
        User.objects.create_superuser(
            username="admin", password="testpass123", user_level=10
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["superuser_exists"])

    def test_returns_true_when_admin_level_user_exists(self):
        """User with user_level=10 but is_superuser=False should be detected"""
        user = User.objects.create_user(username="admin", password="testpass123")
        user.user_level = 10
        user.is_superuser = False
        user.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["superuser_exists"])

    def test_returns_false_when_no_admin_exists(self):
        """No admin or superuser should return false"""
        # Create a non-admin user
        User.objects.create_user(username="regular", password="testpass123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["superuser_exists"])
        self.assertIn("client_ip", data)
        self.assertIn("setup_allowed", data)

    def test_returns_false_when_no_users_exist(self):
        """Empty database should return false"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["superuser_exists"])
        # Django test client is loopback, so local setup should be allowed
        self.assertTrue(data["setup_allowed"])

    def test_create_superuser_when_none_exists(self):
        """POST should create superuser when none exists"""
        response = self.client.post(
            self.url,
            {"username": "newadmin", "password": "testpass123", "email": "admin@test.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["superuser_exists"])
        self.assertTrue(User.objects.filter(username="newadmin", user_level=10).exists())

    def test_cannot_create_superuser_when_admin_exists(self):
        """POST should fail when an admin-level user already exists"""
        user = User.objects.create_user(username="existing", password="testpass123")
        user.user_level = 10
        user.save()
        response = self.client.post(
            self.url,
            {"username": "newadmin", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["superuser_exists"])
        # Should NOT have created a new user
        self.assertFalse(User.objects.filter(username="newadmin").exists())

    def test_post_blocked_from_public_ip_by_default(self):
        """Remote public IPs cannot complete web setup without the env override."""
        response = self.client.post(
            self.url,
            {"username": "newadmin", "password": "testpass123"},
            format="json",
            REMOTE_ADDR="203.0.113.50",
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data["client_ip"], "203.0.113.50")
        self.assertFalse(data["setup_allowed"])
        self.assertFalse(User.objects.filter(username="newadmin").exists())

    def test_get_reports_setup_not_allowed_for_public_ip(self):
        response = self.client.get(self.url, REMOTE_ADDR="203.0.113.50")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["superuser_exists"])
        self.assertFalse(data["setup_allowed"])
        self.assertEqual(data["client_ip"], "203.0.113.50")

    def test_post_allowed_from_private_lan(self):
        response = self.client.post(
            self.url,
            {"username": "lanadmin", "password": "testpass123"},
            format="json",
            REMOTE_ADDR="192.168.1.50",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username="lanadmin", user_level=10).exists())

    @patch.dict("os.environ", {"DISPATCHARR_SETUP_ALLOWED_IP": "203.0.113.50"})
    def test_post_allowed_for_env_override_ip(self):
        response = self.client.post(
            self.url,
            {"username": "vpsadmin", "password": "testpass123"},
            format="json",
            REMOTE_ADDR="203.0.113.50",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username="vpsadmin", user_level=10).exists())

    @patch.dict("os.environ", {"DISPATCHARR_SETUP_ALLOWED_IP": "203.0.113.50"})
    def test_post_blocked_when_env_ip_does_not_match(self):
        """When the override is set, only that exact IP may set up (not local)."""
        response = self.client.post(
            self.url,
            {"username": "other", "password": "testpass123"},
            format="json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="other").exists())

    @patch.dict("os.environ", {"DISPATCHARR_SETUP_ALLOWED_IP": "203.0.113.50"})
    def test_x_real_ip_used_for_setup_gate(self):
        response = self.client.post(
            self.url,
            {"username": "proxied", "password": "testpass123"},
            format="json",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_REAL_IP="203.0.113.50",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username="proxied", user_level=10).exists())

    def test_post_allowed_for_ipv4_mapped_private_address(self):
        """Proxies may present LAN clients as ::ffff:x.x.x.x."""
        response = self.client.post(
            self.url,
            {"username": "mapped", "password": "testpass123"},
            format="json",
            REMOTE_ADDR="::ffff:192.168.1.50",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username="mapped", user_level=10).exists())

    @patch.dict("os.environ", {"DISPATCHARR_SETUP_ALLOWED_IP": "not-an-ip"})
    def test_invalid_setup_allowed_ip_env_denies_post(self):
        response = self.client.post(
            self.url,
            {"username": "badenv", "password": "testpass123"},
            format="json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="badenv").exists())