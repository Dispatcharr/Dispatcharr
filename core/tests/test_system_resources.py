from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.api_views import CoreSettingsViewSet


class SystemResourcesTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="resource_admin",
            password="x",
            user_level=user_model.UserLevel.ADMIN,
        )

    def test_resource_snapshot_separates_container_process_and_shm(self):
        request = APIRequestFactory().get("/api/core/settings/resources/")
        force_authenticate(request, user=self.admin)
        response = CoreSettingsViewSet.as_view({"get": "resources"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.data["process"]["memory_bytes"], 0)
        self.assertGreater(response.data["memory"]["used_bytes"], 0)
        self.assertIn("limited", response.data["memory"])
        self.assertIn("limit_bytes", response.data["memory"])
        self.assertGreater(response.data["shared_memory"]["total_bytes"], 0)
        self.assertEqual(response.data["shared_memory"]["path"], "/dev/shm")
