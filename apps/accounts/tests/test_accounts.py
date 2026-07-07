from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

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
        self.assertFalse(response.json()["superuser_exists"])

    def test_returns_false_when_no_users_exist(self):
        """Empty database should return false"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["superuser_exists"])

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