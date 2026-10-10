"""Stream custom read actions require standard user, not streamer."""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


class StreamCustomActionPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _user(self, level):
        return User.objects.create_user(
            username=f"stream-act-{level}-{uuid4().hex[:8]}",
            password="pass",
            user_level=level,
        )

    def test_streamer_denied_stream_helper_actions(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.STREAMER))
        ids = self.client.get("/api/channels/streams/ids/")
        groups = self.client.get("/api/channels/streams/groups/")
        filter_options = self.client.get("/api/channels/streams/filter-options/")
        by_ids = self.client.post(
            "/api/channels/streams/by-ids/",
            {"ids": []},
            format="json",
        )
        self.assertEqual(ids.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(groups.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(filter_options.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(by_ids.status_code, status.HTTP_403_FORBIDDEN)

    def test_standard_user_can_call_stream_helper_actions(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.STANDARD))
        ids = self.client.get("/api/channels/streams/ids/")
        groups = self.client.get("/api/channels/streams/groups/")
        filter_options = self.client.get("/api/channels/streams/filter-options/")
        by_ids = self.client.post(
            "/api/channels/streams/by-ids/",
            {"ids": []},
            format="json",
        )
        self.assertEqual(ids.status_code, status.HTTP_200_OK)
        self.assertEqual(groups.status_code, status.HTTP_200_OK)
        self.assertEqual(filter_options.status_code, status.HTTP_200_OK)
        self.assertEqual(by_ids.status_code, status.HTTP_200_OK)
