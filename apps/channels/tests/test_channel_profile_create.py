from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.channels.models import Channel, ChannelProfile, ChannelProfileMembership

User = get_user_model()


class ChannelProfileCreateAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testadmin", password="testpass123")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.profiles_url = "/api/channels/profiles/"

        self.channel1 = Channel.objects.create(channel_number=1.0, name="Channel 1")
        self.channel2 = Channel.objects.create(channel_number=2.0, name="Channel 2")

        # After channels so the membership signal backfills both.
        self.all_profile = ChannelProfile.objects.create(name="All")

    def test_create_profile_defaults_to_all_channels(self):
        response = self.client.post(
            self.profiles_url, {"name": "Default Profile"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        profile = ChannelProfile.objects.get(id=response.data["id"])
        memberships = ChannelProfileMembership.objects.filter(channel_profile=profile)

        self.assertEqual(memberships.count(), 2)
        self.assertTrue(memberships.filter(channel=self.channel1, enabled=True).exists())
        self.assertTrue(memberships.filter(channel=self.channel2, enabled=True).exists())
        self.assertEqual(sorted(response.data["channels"]), sorted([self.channel1.id, self.channel2.id]))

    def test_create_profile_with_start_empty_has_zero_channels(self):
        response = self.client.post(
            self.profiles_url,
            {"name": "Empty Profile", "start_empty": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        profile = ChannelProfile.objects.get(id=response.data["id"])

        self.assertEqual(
            ChannelProfileMembership.objects.filter(channel_profile=profile).count(), 0
        )
        self.assertEqual(response.data["channels"], [])

    def test_create_empty_profile_does_not_modify_all_profile(self):
        all_memberships_before = list(
            ChannelProfileMembership.objects.filter(
                channel_profile=self.all_profile
            ).values_list("channel_id", "enabled")
        )

        response = self.client.post(
            self.profiles_url,
            {"name": "Empty Profile 2", "start_empty": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        all_memberships_after = list(
            ChannelProfileMembership.objects.filter(
                channel_profile=self.all_profile
            ).values_list("channel_id", "enabled")
        )
        self.assertEqual(sorted(all_memberships_before), sorted(all_memberships_after))

    def test_duplicate_action_still_copies_channels(self):
        response = self.client.post(
            f"{self.profiles_url}{self.all_profile.id}/duplicate/",
            {"name": "All Copy"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        profile = ChannelProfile.objects.get(id=response.data["id"])
        self.assertEqual(
            ChannelProfileMembership.objects.filter(channel_profile=profile).count(), 2
        )
