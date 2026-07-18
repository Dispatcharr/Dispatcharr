"""SystemNotification write vs dismiss permission split."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.api_views import SystemNotificationViewSet
from core.models import SystemNotification


class SystemNotificationPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="notif_admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
        )
        self.standard = User.objects.create_user(
            username="notif_user",
            password="x",
            user_level=User.UserLevel.STANDARD,
        )
        self.notif = SystemNotification.objects.create(
            notification_key="test.notif",
            title="Hello",
            message="World",
            is_active=True,
            admin_only=False,
        )
        self.factory = APIRequestFactory()

    def test_standard_user_can_list(self):
        request = self.factory.get("/api/system/notifications/")
        force_authenticate(request, user=self.standard)
        view = SystemNotificationViewSet.as_view({"get": "list"})
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_standard_user_cannot_create(self):
        request = self.factory.post(
            "/api/system/notifications/",
            {
                "notification_key": "evil",
                "title": "Phish",
                "message": "Click",
                "is_active": True,
            },
            format="json",
        )
        force_authenticate(request, user=self.standard)
        view = SystemNotificationViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, 403)

    def test_standard_user_can_dismiss(self):
        request = self.factory.post(
            f"/api/system/notifications/{self.notif.id}/dismiss/"
        )
        force_authenticate(request, user=self.standard)
        view = SystemNotificationViewSet.as_view({"post": "dismiss"})
        response = view(request, pk=self.notif.id)
        self.assertEqual(response.status_code, 200)
