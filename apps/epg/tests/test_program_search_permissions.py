"""Program search honors IsStandardUser via @action permission_classes and
only returns programs on channels the user may access."""

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelProfile, ChannelProfileMembership
from apps.epg.models import EPGData, ProgramData

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


class ProgramSearchChannelScopeTests(TestCase):
    """Search results follow the same channel visibility as the channel list."""

    def setUp(self):
        self.client = APIClient()
        now = timezone.now()

        def channel_with_program(number, name, **channel_kwargs):
            epg = EPGData.objects.create(tvg_id=f"scope-{number}", name=name)
            channel = Channel.objects.create(
                channel_number=number, name=name, epg_data=epg, **channel_kwargs
            )
            program = ProgramData.objects.create(
                epg=epg,
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
                title=f"Needle on {name}",
            )
            return channel, program

        self.allowed, self.allowed_program = channel_with_program(1, "Allowed")
        self.outside, self.outside_program = channel_with_program(2, "Outside")
        self.adult, self.adult_program = channel_with_program(
            3, "Adult", is_adult=True
        )
        self.high, self.high_program = channel_with_program(
            4, "High", user_level=5
        )
        # A second channel on the same guide as "Allowed". The program is
        # returned because the user can reach "Allowed", but this channel must
        # not be listed alongside it.
        self.shared_outside = Channel.objects.create(
            channel_number=5, name="SharedOutside", epg_data=self.allowed.epg_data
        )

        self.profile = ChannelProfile.objects.create(name="Search profile")
        ChannelProfileMembership.objects.filter(
            channel_profile=self.profile,
            channel__in=[self.outside, self.shared_outside],
        ).update(enabled=False)

        self.user = User.objects.create_user(
            username=f"scope-search-{uuid4().hex[:8]}",
            password="pass",
            user_level=User.UserLevel.STANDARD,
            custom_properties={"hide_adult_content": True},
        )
        self.user.channel_profiles.add(self.profile)

    def _search(self, user):
        self.client.force_authenticate(user=user)
        response = self.client.get("/api/epg/programs/search/", {"title": "Needle"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        rows = data["results"] if isinstance(data, dict) else data
        return rows

    def test_results_only_include_accessible_channels(self):
        rows = self._search(self.user)
        self.assertEqual({row["id"] for row in rows}, {self.allowed_program.id})

    def test_mapped_channels_exclude_inaccessible_ones(self):
        rows = self._search(self.user)
        channel_ids = {
            channel["id"] for row in rows for channel in row.get("channels", [])
        }
        self.assertEqual(channel_ids, {self.allowed.id})

    def test_admin_sees_programs_on_every_channel(self):
        admin = User.objects.create_user(
            username=f"scope-search-admin-{uuid4().hex[:8]}",
            password="pass",
            user_level=User.UserLevel.ADMIN,
        )
        rows = self._search(admin)
        self.assertEqual(
            {row["id"] for row in rows},
            {
                self.allowed_program.id,
                self.outside_program.id,
                self.adult_program.id,
                self.high_program.id,
            },
        )
