"""Tests for per-user DVR recording visibility.

Request-tier users only see recordings they own; view-tier users keep the
existing shared-library behavior (everything on channels they can access);
manage/admin always see everything.
"""

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.channels.dvr_access import DVR_ACCESS_MANAGE, DVR_ACCESS_REQUEST, DVR_ACCESS_VIEW
from apps.channels.models import Channel, Recording, RecordingRequest

User = get_user_model()


@override_settings(ALLOWED_HOSTS=["testserver"])
class DvrRecordingVisibilityApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.channel = Channel.objects.create(
            channel_number=301,
            name=f"Visibility {uuid4().hex[:6]}",
            user_level=0,
        )

    def _user(self, *, user_level=User.UserLevel.STANDARD, dvr_access=None):
        custom_properties = {}
        if dvr_access is not None:
            custom_properties["dvr_access"] = dvr_access
        return User.objects.create_user(
            username=f"dvr-vis-{uuid4().hex[:8]}",
            password="pass",
            user_level=user_level,
            custom_properties=custom_properties,
        )

    def _recording(self, owner=None):
        start = timezone.now() + timedelta(hours=1)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=start,
            end_time=start + timedelta(hours=1),
            custom_properties={"status": "scheduled"},
        )
        if owner is not None:
            RecordingRequest.objects.create(
                recording=rec, user=owner, is_owner=True
            )
        return rec

    def test_request_tier_sees_only_own_recordings(self):
        mine = self._user(dvr_access=DVR_ACCESS_REQUEST)
        theirs = self._user(dvr_access=DVR_ACCESS_REQUEST)
        my_rec = self._recording(owner=mine)
        their_rec = self._recording(owner=theirs)

        self.client.force_authenticate(user=mine)
        response = self.client.get("/api/channels/recordings/")
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data}
        self.assertIn(my_rec.id, ids)
        self.assertNotIn(their_rec.id, ids)

    def test_request_tier_cannot_retrieve_others_recording_directly(self):
        theirs = self._user(dvr_access=DVR_ACCESS_REQUEST)
        their_rec = self._recording(owner=theirs)

        mine = self._user(dvr_access=DVR_ACCESS_REQUEST)
        self.client.force_authenticate(user=mine)
        response = self.client.get(f"/api/channels/recordings/{their_rec.id}/")
        self.assertEqual(response.status_code, 404)

    def test_request_tier_sees_shared_recording_they_also_requested(self):
        owner = self._user(dvr_access=DVR_ACCESS_REQUEST)
        wanter = self._user(dvr_access=DVR_ACCESS_REQUEST)
        rec = self._recording(owner=owner)
        RecordingRequest.objects.create(recording=rec, user=wanter, is_owner=False)

        self.client.force_authenticate(user=wanter)
        response = self.client.get("/api/channels/recordings/")
        ids = {row["id"] for row in response.data}
        self.assertIn(rec.id, ids)

    def test_view_tier_still_sees_all_recordings_on_visible_channel(self):
        owner = self._user(dvr_access=DVR_ACCESS_REQUEST)
        rec = self._recording(owner=owner)

        viewer = self._user(dvr_access=DVR_ACCESS_VIEW)
        self.client.force_authenticate(user=viewer)
        response = self.client.get("/api/channels/recordings/")
        ids = {row["id"] for row in response.data}
        self.assertIn(rec.id, ids)

    def test_manage_and_admin_see_all_recordings(self):
        owner = self._user(dvr_access=DVR_ACCESS_REQUEST)
        rec = self._recording(owner=owner)

        manager = self._user(dvr_access=DVR_ACCESS_MANAGE)
        self.client.force_authenticate(user=manager)
        response = self.client.get("/api/channels/recordings/")
        ids = {row["id"] for row in response.data}
        self.assertIn(rec.id, ids)

        admin = self._user(user_level=User.UserLevel.ADMIN)
        self.client.force_authenticate(user=admin)
        admin_response = self.client.get("/api/channels/recordings/")
        admin_ids = {row["id"] for row in admin_response.data}
        self.assertIn(rec.id, admin_ids)

    def test_request_tier_cannot_play_others_unowned_recording(self):
        theirs = self._user(dvr_access=DVR_ACCESS_REQUEST)
        their_rec = self._recording(owner=theirs)

        mine = self._user(dvr_access=DVR_ACCESS_REQUEST)
        self.client.force_authenticate(user=mine)
        response = self.client.get(f"/api/channels/recordings/{their_rec.id}/file/")
        self.assertEqual(response.status_code, 403)
