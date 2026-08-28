"""System events endpoint is admin-only (channel UUID / connection telemetry)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.api_views import get_system_events
from core.models import SystemEvent


class SystemEventsPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="events_admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
        )
        self.standard = User.objects.create_user(
            username="events_user",
            password="x",
            user_level=User.UserLevel.STANDARD,
        )
        SystemEvent.objects.create(
            event_type="channel_start",
            channel_name="Test Channel",
        )
        self.factory = APIRequestFactory()

    def test_admin_can_list_system_events(self):
        request = self.factory.get("/api/core/system-events/")
        force_authenticate(request, user=self.admin)
        response = get_system_events(request)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data["total"], 1)

    def test_standard_user_cannot_list_system_events(self):
        request = self.factory.get("/api/core/system-events/")
        force_authenticate(request, user=self.standard)
        response = get_system_events(request)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_list_system_events(self):
        request = self.factory.get("/api/core/system-events/")
        response = get_system_events(request)
        self.assertIn(response.status_code, (401, 403))
