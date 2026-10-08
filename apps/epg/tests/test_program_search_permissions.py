"""Program search honors IsStandardUser via @action permission_classes."""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


class ProgramSearchPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _user(self, level):
        return User.objects.create_user(
            username=f"prog-search-{level}-{uuid4().hex[:8]}",
            password="pass",
            user_level=level,
        )

    def test_streamer_denied_program_search(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.STREAMER))
        response = self.client.get("/api/epg/programs/search/?q=test")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_standard_user_can_program_search(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.STANDARD))
        response = self.client.get("/api/epg/programs/search/?q=test")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
