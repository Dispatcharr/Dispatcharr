"""Channel read endpoints that Standard users can call apply the shared
channel visibility rules (level, hide-adult preference, assigned profiles)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.channels.models import (
    Channel,
    ChannelProfile,
    ChannelProfileMembership,
    Stream,
)

User = get_user_model()

PROVIDER_URL = "http://provider.example/live/secret"


def _make_user(username, level, **custom_properties):
    user = User.objects.create_user(username=username, password="testpass123")
    user.user_level = level
    user.custom_properties = custom_properties
    user.save()
    return user


class ChannelReadEndpointVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.allowed = Channel.objects.create(channel_number=1, name="Allowed")
        self.other_profile = Channel.objects.create(
            channel_number=2, name="Other profile"
        )
        self.adult = Channel.objects.create(
            channel_number=3, name="Adult", is_adult=True
        )
        self.high_level = Channel.objects.create(
            channel_number=4, name="High level", user_level=5
        )
        self.stream = Stream.objects.create(name="Provider", url=PROVIDER_URL)
        for channel in (
            self.allowed,
            self.other_profile,
            self.adult,
            self.high_level,
        ):
            channel.streams.add(self.stream)

        # Only "Other profile" is switched off in the assigned profile, so the
        # adult and high level channels are excluded by their own rules.
        self.profile = ChannelProfile.objects.create(name="Assigned")
        ChannelProfileMembership.objects.filter(
            channel_profile=self.profile, channel=self.other_profile
        ).update(enabled=False)

        self.standard = _make_user("standard-streams", 1, hide_adult_content=True)
        self.standard.channel_profiles.add(self.profile)
        self.unrestricted = _make_user("unrestricted-streams", 1)
        self.admin = _make_user("admin-streams", 10)

    def _get(self, user, path):
        self.client.force_authenticate(user=user)
        return self.client.get(path)

    def _streams_path(self, channel, suffix=""):
        return f"/api/channels/channels/{channel.id}/streams/{suffix}"

    def test_streams_on_an_accessible_channel(self):
        response = self._get(self.standard, self._streams_path(self.allowed))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["url"], PROVIDER_URL)

    def test_streams_outside_assigned_profiles_are_not_found(self):
        response = self._get(self.standard, self._streams_path(self.other_profile))
        self.assertEqual(response.status_code, 404)

    def test_streams_of_adult_channel_are_not_found_with_the_preference(self):
        response = self._get(self.standard, self._streams_path(self.adult))
        self.assertEqual(response.status_code, 404)

    def test_streams_above_user_level_are_not_found(self):
        response = self._get(self.standard, self._streams_path(self.high_level))
        self.assertEqual(response.status_code, 404)

    def test_user_without_profiles_can_read_streams_within_level(self):
        response = self._get(self.unrestricted, self._streams_path(self.other_profile))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_read_streams_for_any_channel(self):
        for channel in (self.other_profile, self.adult, self.high_level):
            response = self._get(self.admin, self._streams_path(channel))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data), 1)

    def test_stream_stats_follow_the_same_visibility(self):
        stats = lambda channel: self._streams_path(channel, "stats/")
        self.assertEqual(self._get(self.standard, stats(self.allowed)).status_code, 200)
        self.assertEqual(
            self._get(self.standard, stats(self.other_profile)).status_code, 404
        )
        self.assertEqual(
            self._get(self.admin, stats(self.other_profile)).status_code, 200
        )

    def test_by_uuids_returns_only_accessible_channels(self):
        self.client.force_authenticate(user=self.standard)
        uuids = [
            str(channel.uuid)
            for channel in (
                self.allowed,
                self.other_profile,
                self.adult,
                self.high_level,
            )
        ]
        response = self.client.post(
            "/api/channels/channels/by-uuids/?include_streams=true",
            {"uuids": uuids},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["id"] for row in response.data}, {self.allowed.id})

    def test_numbers_in_range_lists_only_accessible_channels(self):
        path = "/api/channels/channels/numbers-in-range/?start=1&end=10"
        names = {
            row["name"]
            for row in self._get(self.standard, path).data["occupants"]
        }
        self.assertEqual(names, {"Allowed"})
        admin_names = {
            row["name"] for row in self._get(self.admin, path).data["occupants"]
        }
        self.assertEqual(
            admin_names, {"Allowed", "Other profile", "Adult", "High level"}
        )
