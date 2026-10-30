"""Routine Library reads must not be logged as failures."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.vod.api_views import UnifiedContentViewSet


class UnifiedContentLoggingTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="library_logging_admin",
            password="test-password",
            user_level=user_model.UserLevel.ADMIN,
        )
        self.factory = APIRequestFactory()
        self.view = UnifiedContentViewSet.as_view({"get": "list"})

    def request(self, **query):
        request = self.factory.get("/api/vod/all/", query)
        force_authenticate(request, user=self.admin)
        return self.view(request)

    def test_successful_empty_library_read_does_not_log_a_warning_or_error(self):
        with self.assertNoLogs("apps.vod.api_views", level="WARNING"):
            response = self.request(page=1, page_size=24)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_actual_database_failure_remains_an_error(self):
        with (
            patch(
                "django.db.connection.cursor",
                side_effect=RuntimeError("test database failure"),
            ),
            self.assertLogs("apps.vod.api_views", level="ERROR") as messages,
        ):
            response = self.request()
        self.assertEqual(response.status_code, 500)
        self.assertTrue(
            any("test database failure" in line for line in messages.output)
        )
