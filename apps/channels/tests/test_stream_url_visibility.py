"""Provider stream URLs are admin-only; Standard users still see stream metadata.

The global stream list and by-ids stay unscoped by channel profiles so
Standard users can browse streams when building playlists. Adult and
user_level rules continue to apply on channel surfaces, not here.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelProfile, Stream

User = get_user_model()

PROVIDER_A = "http://provider-a.test/live/a_user/alice_secret/101.ts"
PROVIDER_B = "http://provider-b.test/live/b_user/bob_secret/101.ts"


def _make_user(username, level):
    user = User.objects.create_user(username=username, password="testpass123")
    user.user_level = level
    user.save()
    return user


class StreamUrlVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.stream_a = Stream.objects.create(name="Account A", url=PROVIDER_A)
        self.stream_b = Stream.objects.create(name="Account B", url=PROVIDER_B)
        self.channel_a = Channel.objects.create(
            channel_number=1, name="From A"
        )
        self.channel_a.streams.add(self.stream_a)

        # Assigned profile (channel A only in practice). Stream B must still
        # be listable as metadata so Standard users can build playlists.
        self.profile = ChannelProfile.objects.create(name="Profile A")
        self.standard = _make_user("standard-url", User.UserLevel.STANDARD)
        self.standard.channel_profiles.add(self.profile)
        self.admin = _make_user("admin-url", User.UserLevel.ADMIN)

    def test_standard_list_omits_provider_urls_but_returns_all_streams(self):
        self.client.force_authenticate(user=self.standard)
        response = self.client.get(
            "/api/channels/streams/", {"page_size": 50}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["results"]
        by_id = {row["id"]: row for row in rows}
        self.assertIn(self.stream_a.id, by_id)
        self.assertIn(self.stream_b.id, by_id)
        self.assertNotIn("url", by_id[self.stream_a.id])
        self.assertNotIn("url", by_id[self.stream_b.id])
        self.assertNotIn(b"alice_secret", response.content)
        self.assertNotIn(b"bob_secret", response.content)

    def test_standard_by_ids_omits_provider_urls(self):
        self.client.force_authenticate(user=self.standard)
        response = self.client.post(
            "/api/channels/streams/by-ids/",
            {"ids": [self.stream_a.id, self.stream_b.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = {row["id"]: row for row in response.data}
        self.assertEqual(set(by_id), {self.stream_a.id, self.stream_b.id})
        self.assertNotIn("url", by_id[self.stream_a.id])
        self.assertNotIn("url", by_id[self.stream_b.id])
        self.assertNotIn(b"alice_secret", response.content)
        self.assertNotIn(b"bob_secret", response.content)

    def test_admin_list_includes_provider_urls(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(
            "/api/channels/streams/", {"page_size": 50}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = {row["id"]: row for row in response.data["results"]}
        self.assertEqual(by_id[self.stream_a.id]["url"], PROVIDER_A)
        self.assertEqual(by_id[self.stream_b.id]["url"], PROVIDER_B)

    def test_admin_by_ids_includes_provider_urls(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/channels/streams/by-ids/",
            {"ids": [self.stream_a.id, self.stream_b.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = {row["id"]: row for row in response.data}
        self.assertEqual(by_id[self.stream_a.id]["url"], PROVIDER_A)
        self.assertEqual(by_id[self.stream_b.id]["url"], PROVIDER_B)

    def test_include_streams_on_accessible_channel_omits_url_for_standard(self):
        self.client.force_authenticate(user=self.standard)
        response = self.client.get(
            f"/api/channels/channels/{self.channel_a.id}/",
            {"include_streams": "true"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        streams = response.data["streams"]
        self.assertEqual(len(streams), 1)
        self.assertNotIn("url", streams[0])
        self.assertNotIn(b"alice_secret", response.content)
