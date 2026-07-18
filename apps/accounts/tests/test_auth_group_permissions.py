"""Django auth.Group API is admin-only (unused by the React UI)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.api_views import GroupViewSet, list_permissions


class AuthGroupPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="auth_group_admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
        )
        self.standard = User.objects.create_user(
            username="auth_group_user",
            password="x",
            user_level=User.UserLevel.STANDARD,
        )
        self.factory = APIRequestFactory()
        self.group = Group.objects.create(name="unused-role")

    def test_standard_user_cannot_list_groups(self):
        request = self.factory.get("/api/accounts/groups/")
        force_authenticate(request, user=self.standard)
        view = GroupViewSet.as_view({"get": "list"})
        response = view(request)
        self.assertEqual(response.status_code, 403)

    def test_admin_can_list_groups(self):
        request = self.factory.get("/api/accounts/groups/")
        force_authenticate(request, user=self.admin)
        view = GroupViewSet.as_view({"get": "list"})
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_standard_user_cannot_list_permissions(self):
        request = self.factory.get("/api/accounts/permissions/")
        force_authenticate(request, user=self.standard)
        response = list_permissions(request)
        self.assertEqual(response.status_code, 403)
