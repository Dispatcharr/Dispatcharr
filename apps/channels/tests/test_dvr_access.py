"""Tests for DVR access levels and API gates."""

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.channels.dvr_access import (
    DVR_ACCESS_MANAGE,
    DVR_ACCESS_NONE,
    DVR_ACCESS_VIEW,
    get_dvr_access,
    is_dvr_manage_enabled,
    is_dvr_view_enabled,
    recordings_queryset_for_user,
)
from apps.channels.models import (
    Channel,
    ChannelProfile,
    ChannelProfileMembership,
    Recording,
)

User = get_user_model()


class DvrAccessHelperTests(TestCase):
    def test_anonymous_is_denied(self):
        self.assertEqual(get_dvr_access(user=None), DVR_ACCESS_NONE)
        self.assertFalse(is_dvr_view_enabled(user=None))
        self.assertFalse(is_dvr_manage_enabled(user=None))

    def test_admin_always_manage(self):
        admin = User(user_level=User.UserLevel.ADMIN, custom_properties={})
        self.assertEqual(get_dvr_access(user=admin), DVR_ACCESS_MANAGE)
        self.assertTrue(is_dvr_view_enabled(user=admin))
        self.assertTrue(is_dvr_manage_enabled(user=admin))

    def test_absent_flag_defaults_to_view(self):
        user = User(user_level=User.UserLevel.STANDARD, custom_properties={})
        self.assertEqual(get_dvr_access(user=user), DVR_ACCESS_VIEW)
        self.assertTrue(is_dvr_view_enabled(user=user))
        self.assertFalse(is_dvr_manage_enabled(user=user))

    def test_none_disables_view_and_manage(self):
        user = User(
            user_level=User.UserLevel.STANDARD,
            custom_properties={"dvr_access": DVR_ACCESS_NONE},
        )
        self.assertEqual(get_dvr_access(user=user), DVR_ACCESS_NONE)
        self.assertFalse(is_dvr_view_enabled(user=user))
        self.assertFalse(is_dvr_manage_enabled(user=user))

    def test_explicit_view(self):
        user = User(
            user_level=User.UserLevel.STANDARD,
            custom_properties={"dvr_access": DVR_ACCESS_VIEW},
        )
        self.assertEqual(get_dvr_access(user=user), DVR_ACCESS_VIEW)
        self.assertTrue(is_dvr_view_enabled(user=user))
        self.assertFalse(is_dvr_manage_enabled(user=user))

    def test_manage_includes_view(self):
        user = User(
            user_level=User.UserLevel.STANDARD,
            custom_properties={"dvr_access": DVR_ACCESS_MANAGE},
        )
        self.assertEqual(get_dvr_access(user=user), DVR_ACCESS_MANAGE)
        self.assertTrue(is_dvr_manage_enabled(user=user))
        self.assertTrue(is_dvr_view_enabled(user=user))

    def test_streamer_never_gets_dvr_even_with_manage(self):
        user = User(
            user_level=User.UserLevel.STREAMER,
            custom_properties={"dvr_access": DVR_ACCESS_MANAGE},
        )
        self.assertEqual(get_dvr_access(user=user), DVR_ACCESS_NONE)
        self.assertFalse(is_dvr_view_enabled(user=user))
        self.assertFalse(is_dvr_manage_enabled(user=user))


@override_settings(ALLOWED_HOSTS=["testserver"])
class DvrAccessApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.channel = Channel.objects.create(
            channel_number=101,
            name=f"DVR Access {uuid4().hex[:6]}",
            user_level=0,
        )
        self.other_channel = Channel.objects.create(
            channel_number=102,
            name=f"DVR Other {uuid4().hex[:6]}",
            user_level=0,
        )
        now = timezone.now()
        self.recording = Recording.objects.create(
            channel=self.channel,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            custom_properties={"status": "scheduled", "program": {"title": "Show"}},
        )
        self.other_recording = Recording.objects.create(
            channel=self.other_channel,
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=4),
            custom_properties={"status": "scheduled", "program": {"title": "Other"}},
        )

    def _user(self, *, user_level=User.UserLevel.STANDARD, dvr_access=None):
        custom_properties = {}
        if dvr_access is not None:
            custom_properties["dvr_access"] = dvr_access
        return User.objects.create_user(
            username=f"dvr-access-{uuid4().hex[:8]}",
            password="pass",
            user_level=user_level,
            custom_properties=custom_properties,
        )

    def test_standard_with_default_view_can_list(self):
        self.client.force_authenticate(user=self._user())
        response = self.client.get("/api/channels/recordings/")
        self.assertEqual(response.status_code, 200)

    def test_none_cannot_list(self):
        self.client.force_authenticate(user=self._user(dvr_access=DVR_ACCESS_NONE))
        response = self.client.get("/api/channels/recordings/")
        self.assertEqual(response.status_code, 403)

    def test_view_can_list_but_not_create_or_delete(self):
        user = self._user(dvr_access=DVR_ACCESS_VIEW)
        self.client.force_authenticate(user=user)

        list_response = self.client.get("/api/channels/recordings/")
        self.assertEqual(list_response.status_code, 200)

        create_response = self.client.post(
            "/api/channels/recordings/",
            {
                "channel": self.channel.id,
                "start_time": (timezone.now() + timedelta(hours=3)).isoformat(),
                "end_time": (timezone.now() + timedelta(hours=4)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 403)

        delete_response = self.client.delete(
            f"/api/channels/recordings/{self.recording.id}/"
        )
        self.assertEqual(delete_response.status_code, 403)

    def test_view_list_is_scoped_to_channel_profiles(self):
        profile = ChannelProfile.objects.create(name=f"dvr-prof-{uuid4().hex[:6]}")
        # New profiles auto-get memberships for all channels; disable the other.
        ChannelProfileMembership.objects.filter(
            channel_profile=profile, channel=self.other_channel
        ).update(enabled=False)
        user = self._user()
        user.channel_profiles.add(profile)
        self.client.force_authenticate(user=user)

        response = self.client.get("/api/channels/recordings/")
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data}
        self.assertIn(self.recording.id, ids)
        self.assertNotIn(self.other_recording.id, ids)

    def test_manage_sees_all_recordings(self):
        profile = ChannelProfile.objects.create(name=f"dvr-mgr-{uuid4().hex[:6]}")
        ChannelProfileMembership.objects.filter(
            channel_profile=profile, channel=self.other_channel
        ).update(enabled=False)
        user = self._user(dvr_access=DVR_ACCESS_MANAGE)
        user.channel_profiles.add(profile)
        self.client.force_authenticate(user=user)

        response = self.client.get("/api/channels/recordings/")
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data}
        self.assertIn(self.recording.id, ids)
        self.assertIn(self.other_recording.id, ids)

    def test_recordings_queryset_helper_scopes_viewers(self):
        profile = ChannelProfile.objects.create(name=f"dvr-qs-{uuid4().hex[:6]}")
        ChannelProfileMembership.objects.filter(
            channel_profile=profile, channel=self.other_channel
        ).update(enabled=False)
        user = self._user()
        user.channel_profiles.add(profile)
        qs = recordings_queryset_for_user(Recording.objects.all(), user)
        ids = set(qs.values_list("id", flat=True))
        self.assertEqual(ids, {self.recording.id})

    def test_manage_can_create_and_delete(self):
        user = self._user(dvr_access=DVR_ACCESS_MANAGE)
        self.client.force_authenticate(user=user)

        list_response = self.client.get("/api/channels/recordings/")
        self.assertEqual(list_response.status_code, 200)

        start = timezone.now() + timedelta(hours=5)
        end = start + timedelta(hours=1)
        create_response = self.client.post(
            "/api/channels/recordings/",
            {
                "channel": self.channel.id,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "custom_properties": {"program": {"title": "Managed"}},
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        created_id = create_response.data["id"]

        delete_response = self.client.delete(
            f"/api/channels/recordings/{created_id}/"
        )
        self.assertIn(delete_response.status_code, (200, 204))

    def test_manage_can_use_recurring_and_series_rules(self):
        user = self._user(dvr_access=DVR_ACCESS_MANAGE)
        self.client.force_authenticate(user=user)

        recurring = self.client.get("/api/channels/recurring-rules/")
        self.assertEqual(recurring.status_code, 200)

        series_get = self.client.get("/api/channels/series-rules/")
        self.assertEqual(series_get.status_code, 200)

        series_post = self.client.post(
            "/api/channels/series-rules/",
            {"title": "Test Series", "mode": "all"},
            format="json",
        )
        self.assertIn(series_post.status_code, (200, 201))

    def test_view_can_get_series_rules_but_not_mutate(self):
        user = self._user()
        self.client.force_authenticate(user=user)

        series_get = self.client.get("/api/channels/series-rules/")
        self.assertEqual(series_get.status_code, 200)

        series_post = self.client.post(
            "/api/channels/series-rules/",
            {"title": "Blocked", "mode": "all"},
            format="json",
        )
        self.assertEqual(series_post.status_code, 403)

        recurring = self.client.get("/api/channels/recurring-rules/")
        self.assertEqual(recurring.status_code, 403)

    def test_bulk_delete_upcoming_requires_manage(self):
        viewer = self._user()
        self.client.force_authenticate(user=viewer)
        denied = self.client.post("/api/channels/recordings/bulk-delete-upcoming/")
        self.assertEqual(denied.status_code, 403)

        manager = self._user(dvr_access=DVR_ACCESS_MANAGE)
        self.client.force_authenticate(user=manager)
        allowed = self.client.post("/api/channels/recordings/bulk-delete-upcoming/")
        self.assertEqual(allowed.status_code, 200)

    def test_comskip_config_stays_admin_only(self):
        manager = self._user(dvr_access=DVR_ACCESS_MANAGE)
        self.client.force_authenticate(user=manager)
        response = self.client.get("/api/channels/dvr/comskip-config/")
        self.assertEqual(response.status_code, 403)

        admin = self._user(user_level=User.UserLevel.ADMIN)
        self.client.force_authenticate(user=admin)
        admin_response = self.client.get("/api/channels/dvr/comskip-config/")
        self.assertEqual(admin_response.status_code, 200)

    def test_me_cannot_self_grant_dvr_access(self):
        user = self._user(dvr_access=DVR_ACCESS_NONE)
        self.client.force_authenticate(user=user)
        response = self.client.patch(
            "/api/accounts/users/me/",
            {"custom_properties": {"dvr_access": DVR_ACCESS_MANAGE}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        props = user.custom_properties or {}
        self.assertEqual(props.get("dvr_access"), DVR_ACCESS_NONE)
