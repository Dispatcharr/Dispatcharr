"""Tests for DVR recording ownership, request-tier access, and reassignment."""

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.channels.dvr_access import (
    DVR_ACCESS_MANAGE,
    DVR_ACCESS_REQUEST,
    DVR_ACCESS_VIEW,
    get_dvr_access,
    is_dvr_request_enabled,
    is_dvr_view_enabled,
)
from apps.channels.models import Channel, Recording, RecordingRequest

User = get_user_model()


class DvrRequestTierHelperTests(TestCase):
    def test_request_tier_enables_request_and_view_not_manage(self):
        user = User(
            user_level=User.UserLevel.STANDARD,
            custom_properties={"dvr_access": DVR_ACCESS_REQUEST},
        )
        self.assertEqual(get_dvr_access(user=user), DVR_ACCESS_REQUEST)
        self.assertTrue(is_dvr_request_enabled(user=user))
        self.assertTrue(is_dvr_view_enabled(user=user))

    def test_manage_implies_request(self):
        user = User(
            user_level=User.UserLevel.STANDARD,
            custom_properties={"dvr_access": DVR_ACCESS_MANAGE},
        )
        self.assertTrue(is_dvr_request_enabled(user=user))

    def test_view_does_not_imply_request(self):
        user = User(
            user_level=User.UserLevel.STANDARD,
            custom_properties={"dvr_access": DVR_ACCESS_VIEW},
        )
        self.assertFalse(is_dvr_request_enabled(user=user))


@override_settings(ALLOWED_HOSTS=["testserver"])
class DvrRecordingOwnershipApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.channel = Channel.objects.create(
            channel_number=201,
            name=f"Ownership {uuid4().hex[:6]}",
            user_level=0,
        )
        self.other_channel = Channel.objects.create(
            channel_number=202,
            name=f"Ownership Other {uuid4().hex[:6]}",
            user_level=0,
        )

    def _user(self, *, user_level=User.UserLevel.STANDARD, dvr_access=None):
        custom_properties = {}
        if dvr_access is not None:
            custom_properties["dvr_access"] = dvr_access
        return User.objects.create_user(
            username=f"dvr-owner-{uuid4().hex[:8]}",
            password="pass",
            user_level=user_level,
            custom_properties=custom_properties,
        )

    def _schedule(self, user, channel=None, start=None, end=None):
        start = start or (timezone.now() + timedelta(hours=1))
        end = end or (start + timedelta(hours=1))
        self.client.force_authenticate(user=user)
        return self.client.post(
            "/api/channels/recordings/",
            {
                "channel": (channel or self.channel).id,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
            format="json",
        )

    def test_request_tier_can_schedule_for_visible_channel(self):
        user = self._user(dvr_access=DVR_ACCESS_REQUEST)
        response = self._schedule(user)
        self.assertEqual(response.status_code, 201)
        recording = Recording.objects.get(pk=response.data["id"])
        self.assertEqual(recording.owner, user)
        self.assertTrue(
            RecordingRequest.objects.filter(
                recording=recording, user=user, is_owner=True
            ).exists()
        )
        # The create() response itself must reflect the just-created
        # ownership, not the stale pre-attribution serialization.
        self.assertEqual(response.data["owner"], {"id": user.id, "username": user.username})

    def test_request_tier_cannot_schedule_for_invisible_channel(self):
        user = self._user(dvr_access=DVR_ACCESS_REQUEST, user_level=User.UserLevel.STANDARD)
        hidden = Channel.objects.create(
            channel_number=999, name=f"Hidden {uuid4().hex[:6]}", user_level=10
        )
        response = self._schedule(user, channel=hidden)
        self.assertEqual(response.status_code, 403)

    def test_view_tier_cannot_schedule(self):
        user = self._user(dvr_access=DVR_ACCESS_VIEW)
        response = self._schedule(user)
        self.assertEqual(response.status_code, 403)

    def test_second_request_for_same_timeslot_joins_instead_of_duplicating(self):
        owner = self._user(dvr_access=DVR_ACCESS_REQUEST)
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(hours=1)
        first = self._schedule(owner, start=start, end=end)
        self.assertEqual(first.status_code, 201)

        wanter = self._user(dvr_access=DVR_ACCESS_REQUEST)
        second = self._schedule(wanter, start=start, end=end)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["id"], first.data["id"])
        self.assertEqual(Recording.objects.count(), 1)

        recording = Recording.objects.get(pk=first.data["id"])
        self.assertEqual(recording.owner, owner)
        self.assertEqual(recording.requests.count(), 2)

    def test_owner_can_delete_unshared_recording(self):
        owner = self._user(dvr_access=DVR_ACCESS_REQUEST)
        created = self._schedule(owner)
        recording_id = created.data["id"]

        self.client.force_authenticate(user=owner)
        response = self.client.delete(f"/api/channels/recordings/{recording_id}/")
        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(Recording.objects.filter(pk=recording_id).exists())

    def test_non_owner_request_tier_cannot_delete(self):
        owner = self._user(dvr_access=DVR_ACCESS_REQUEST)
        created = self._schedule(owner)
        recording_id = created.data["id"]

        other = self._user(dvr_access=DVR_ACCESS_REQUEST)
        self.client.force_authenticate(user=other)
        response = self.client.delete(f"/api/channels/recordings/{recording_id}/")
        # Request-tier visibility (see test_dvr_recording_visibility.py) scopes
        # the queryset to recordings this user owns, so a recording they don't
        # own 404s before the destroy()-level ownership check ever runs --
        # this also avoids leaking that the recording exists at all.
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Recording.objects.filter(pk=recording_id).exists())

    def test_owner_delete_with_other_wanter_reassigns_instead_of_deleting(self):
        owner = self._user(dvr_access=DVR_ACCESS_REQUEST)
        start = timezone.now() + timedelta(hours=4)
        end = start + timedelta(hours=1)
        created = self._schedule(owner, start=start, end=end)
        recording_id = created.data["id"]

        wanter = self._user(dvr_access=DVR_ACCESS_REQUEST)
        self._schedule(wanter, start=start, end=end)

        self.client.force_authenticate(user=owner)
        response = self.client.delete(f"/api/channels/recordings/{recording_id}/")
        self.assertIn(response.status_code, (200, 204))

        recording = Recording.objects.get(pk=recording_id)
        self.assertEqual(recording.owner, wanter)
        self.assertFalse(
            RecordingRequest.objects.filter(recording=recording, user=owner).exists()
        )
        self.assertTrue(
            RecordingRequest.objects.filter(
                recording=recording, user=wanter, is_owner=True
            ).exists()
        )

    def test_admin_delete_of_unowned_recording_hard_deletes_even_with_wanters(self):
        owner = self._user(dvr_access=DVR_ACCESS_REQUEST)
        start = timezone.now() + timedelta(hours=6)
        end = start + timedelta(hours=1)
        created = self._schedule(owner, start=start, end=end)
        recording_id = created.data["id"]

        wanter = self._user(dvr_access=DVR_ACCESS_REQUEST)
        self._schedule(wanter, start=start, end=end)

        admin = self._user(user_level=User.UserLevel.ADMIN)
        self.client.force_authenticate(user=admin)
        response = self.client.delete(f"/api/channels/recordings/{recording_id}/")
        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(Recording.objects.filter(pk=recording_id).exists())
