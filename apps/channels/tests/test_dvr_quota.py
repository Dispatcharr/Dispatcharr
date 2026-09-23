"""Tests for per-user DVR disk quota enforcement (block-at-schedule and
evict-after-finish)."""

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.channels.dvr_access import DVR_ACCESS_REQUEST
from apps.channels.dvr_quota import (
    evict_oldest_owned_recordings_until_under_quota,
    get_user_dvr_quota_bytes,
    get_user_dvr_usage_bytes,
    user_dvr_quota_exceeded,
)
from apps.channels.models import Channel, Recording, RecordingRequest

User = get_user_model()

_MB = 1024 * 1024


class DvrQuotaHelperTests(TestCase):
    def _user(self, quota_mb=None):
        custom_properties = {"dvr_access": DVR_ACCESS_REQUEST}
        if quota_mb is not None:
            custom_properties["dvr_quota_mb"] = quota_mb
        return User.objects.create_user(
            username=f"dvr-quota-{uuid4().hex[:8]}",
            password="pass",
            user_level=User.UserLevel.STANDARD,
            custom_properties=custom_properties,
        )

    def test_unset_quota_is_unlimited(self):
        user = self._user()
        self.assertIsNone(get_user_dvr_quota_bytes(user))

    def test_zero_or_negative_quota_is_unlimited(self):
        self.assertIsNone(get_user_dvr_quota_bytes(self._user(quota_mb=0)))
        self.assertIsNone(get_user_dvr_quota_bytes(self._user(quota_mb=-5)))

    def test_positive_quota_converts_mb_to_bytes(self):
        user = self._user(quota_mb=500)
        self.assertEqual(get_user_dvr_quota_bytes(user), 500 * _MB)

    def test_unlimited_never_exceeded(self):
        user = self._user()
        self.assertFalse(user_dvr_quota_exceeded(user))


@override_settings(ALLOWED_HOSTS=["testserver"])
class DvrQuotaEnforcementTests(TestCase):
    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=401,
            name=f"Quota {uuid4().hex[:6]}",
            user_level=0,
        )

    def _user(self, quota_mb=None):
        custom_properties = {"dvr_access": DVR_ACCESS_REQUEST}
        if quota_mb is not None:
            custom_properties["dvr_quota_mb"] = quota_mb
        return User.objects.create_user(
            username=f"dvr-quota-{uuid4().hex[:8]}",
            password="pass",
            user_level=User.UserLevel.STANDARD,
            custom_properties=custom_properties,
        )

    def _owned_recording(self, owner, *, bytes_written=0, status="completed", start=None):
        start = start or (timezone.now() - timedelta(hours=2))
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=start,
            end_time=start + timedelta(hours=1),
            custom_properties={"status": status, "bytes_written": bytes_written},
        )
        RecordingRequest.objects.create(recording=rec, user=owner, is_owner=True)
        return rec

    def test_usage_sums_owned_recording_sizes(self):
        user = self._user()
        self._owned_recording(user, bytes_written=100 * _MB)
        self._owned_recording(user, bytes_written=50 * _MB)
        self.assertEqual(get_user_dvr_usage_bytes(user), 150 * _MB)

    def test_quota_exceeded_once_usage_at_or_over_quota(self):
        user = self._user(quota_mb=100)
        self._owned_recording(user, bytes_written=100 * _MB)
        self.assertTrue(user_dvr_quota_exceeded(user))

    def test_create_blocked_when_over_quota(self):
        user = self._user(quota_mb=100)
        self._owned_recording(user, bytes_written=150 * _MB)

        client = APIClient()
        client.force_authenticate(user=user)
        start = timezone.now() + timedelta(hours=3)
        response = client.post(
            "/api/channels/recordings/",
            {
                "channel": self.channel.id,
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_joining_existing_recording_exempt_from_quota(self):
        """Joining someone else's already-scheduled recording costs the
        joiner zero extra storage, so it must not be blocked by their own
        quota -- only actually creating a new Recording should be."""
        owner = self._user()
        start = timezone.now() + timedelta(hours=3)
        end = start + timedelta(hours=1)
        existing = Recording.objects.create(
            channel=self.channel,
            start_time=start,
            end_time=end,
            custom_properties={"status": "scheduled"},
        )
        RecordingRequest.objects.create(recording=existing, user=owner, is_owner=True)

        over_quota_user = self._user(quota_mb=1)
        self._owned_recording(over_quota_user, bytes_written=10 * _MB)

        client = APIClient()
        client.force_authenticate(user=over_quota_user)
        response = client.post(
            "/api/channels/recordings/",
            {
                "channel": self.channel.id,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], existing.id)
        self.assertTrue(
            RecordingRequest.objects.filter(
                recording=existing, user=over_quota_user
            ).exists()
        )

    def test_create_allowed_when_under_quota(self):
        user = self._user(quota_mb=1000)
        self._owned_recording(user, bytes_written=100 * _MB)

        client = APIClient()
        client.force_authenticate(user=user)
        start = timezone.now() + timedelta(hours=3)
        response = client.post(
            "/api/channels/recordings/",
            {
                "channel": self.channel.id,
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_eviction_removes_oldest_first_until_under_quota(self):
        user = self._user(quota_mb=100)
        old = self._owned_recording(
            user, bytes_written=80 * _MB, start=timezone.now() - timedelta(hours=5)
        )
        newer = self._owned_recording(
            user, bytes_written=80 * _MB, start=timezone.now() - timedelta(hours=1)
        )

        evicted = evict_oldest_owned_recordings_until_under_quota(user)
        evicted_ids = {e["id"] for e in evicted}

        self.assertIn(old.id, evicted_ids)
        self.assertFalse(Recording.objects.filter(pk=old.id).exists())
        self.assertTrue(Recording.objects.filter(pk=newer.id).exists())

    def test_eviction_reassigns_instead_of_deleting_when_another_wants_it(self):
        user = self._user(quota_mb=50)
        wanter = self._user()
        rec = self._owned_recording(user, bytes_written=80 * _MB)
        RecordingRequest.objects.create(recording=rec, user=wanter, is_owner=False)

        evicted = evict_oldest_owned_recordings_until_under_quota(user)

        self.assertEqual(evicted, [{"id": rec.id, "action": "reassigned"}])
        rec.refresh_from_db()
        self.assertEqual(rec.owner, wanter)

    def test_eviction_never_touches_in_progress_or_upcoming_recordings(self):
        user = self._user(quota_mb=10)
        in_progress = self._owned_recording(
            user,
            bytes_written=0,
            status="recording",
            start=timezone.now() - timedelta(minutes=10),
        )

        evicted = evict_oldest_owned_recordings_until_under_quota(user)

        self.assertEqual(evicted, [])
        self.assertTrue(Recording.objects.filter(pk=in_progress.id).exists())

    def test_eviction_never_touches_another_users_recordings(self):
        user = self._user(quota_mb=10)
        other_user = self._user()
        other_rec = self._owned_recording(other_user, bytes_written=100 * _MB)

        evict_oldest_owned_recordings_until_under_quota(user)

        self.assertTrue(Recording.objects.filter(pk=other_rec.id).exists())

    def test_eviction_no_op_when_unlimited(self):
        user = self._user()
        rec = self._owned_recording(user, bytes_written=1000 * _MB)

        evicted = evict_oldest_owned_recordings_until_under_quota(user)

        self.assertEqual(evicted, [])
        self.assertTrue(Recording.objects.filter(pk=rec.id).exists())


@override_settings(ALLOWED_HOSTS=["testserver"])
class DvrDiskUsageApiTests(TestCase):
    def _user(self, *, user_level=User.UserLevel.STANDARD, dvr_access=None):
        custom_properties = {}
        if dvr_access is not None:
            custom_properties["dvr_access"] = dvr_access
        return User.objects.create_user(
            username=f"dvr-disk-{uuid4().hex[:8]}",
            password="pass",
            user_level=user_level,
            custom_properties=custom_properties,
        )

    def test_view_tier_can_see_disk_usage(self):
        user = self._user(dvr_access="view")
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/channels/recordings/disk-usage/")
        self.assertEqual(response.status_code, 200)
        for key in ("total_bytes", "used_bytes", "free_bytes"):
            self.assertIn(key, response.data)
            self.assertIsInstance(response.data[key], int)
            self.assertGreaterEqual(response.data[key], 0)

    def test_none_tier_cannot_see_disk_usage(self):
        user = self._user(dvr_access="none")
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/channels/recordings/disk-usage/")
        self.assertEqual(response.status_code, 403)

    def test_falls_back_to_nearest_existing_ancestor_when_storage_root_missing(self):
        """The DVR storage root may not exist yet (fresh install, or a test
        environment that never wrote a recording) -- the endpoint should
        still succeed by walking up to whichever ancestor does exist,
        rather than 503ing."""
        from apps.channels import api_views

        user = self._user(dvr_access="view")
        client = APIClient()
        client.force_authenticate(user=user)

        original_root = api_views.RECORDINGS_STORAGE_ROOT
        api_views.RECORDINGS_STORAGE_ROOT = "/this/path/does/not/exist/recordings"
        try:
            response = client.get("/api/channels/recordings/disk-usage/")
        finally:
            api_views.RECORDINGS_STORAGE_ROOT = original_root

        self.assertEqual(response.status_code, 200)
        self.assertIn("free_bytes", response.data)
