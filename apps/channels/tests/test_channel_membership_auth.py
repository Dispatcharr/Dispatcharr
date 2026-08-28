from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelGroup, ChannelProfile, ChannelProfileMembership

User = get_user_model()


class UpdateChannelMembershipAuthTests(TestCase):
    """Regression: PATCH membership must enforce ChannelProfile ownership."""

    def setUp(self):
        self.client = APIClient()
        self.group = ChannelGroup.objects.create(name="Membership Auth Group")
        self.channel = Channel.objects.create(
            channel_number=1.0,
            name="Membership Auth Channel",
            channel_group=self.group,
        )
        self.owner_profile = ChannelProfile.objects.create(name="Owner Profile")
        self.other_profile = ChannelProfile.objects.create(name="Other Profile")

        self.owner = User.objects.create_user(
            username="profile_owner",
            password="testpass123",
            user_level=User.UserLevel.STANDARD,
        )
        self.owner.channel_profiles.add(self.owner_profile)

        self.outsider = User.objects.create_user(
            username="profile_outsider",
            password="testpass123",
            user_level=User.UserLevel.STANDARD,
        )

        self.admin = User.objects.create_user(
            username="profile_admin",
            password="testpass123",
            user_level=User.UserLevel.ADMIN,
        )

        self.owner_membership = ChannelProfileMembership.objects.get(
            channel_profile=self.owner_profile,
            channel=self.channel,
        )
        self.other_membership = ChannelProfileMembership.objects.get(
            channel_profile=self.other_profile,
            channel=self.channel,
        )
        self.owner_membership.enabled = False
        self.owner_membership.save(update_fields=["enabled"])
        self.other_membership.enabled = False
        self.other_membership.save(update_fields=["enabled"])

    def _url(self, profile_id, channel_id=None):
        channel_id = channel_id or self.channel.id
        return f"/api/channels/profiles/{profile_id}/channels/{channel_id}/"

    def test_non_owner_cannot_modify_foreign_profile_membership(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.patch(
            self._url(self.owner_profile.id),
            {"enabled": True},
            format="json",
        )

        # Scoped queryset hides foreign profiles rather than returning 403.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.owner_membership.refresh_from_db()
        self.assertFalse(self.owner_membership.enabled)

    def test_owner_can_modify_own_profile_membership(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            self._url(self.owner_profile.id),
            {"enabled": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_membership.refresh_from_db()
        self.assertTrue(self.owner_membership.enabled)

    def test_admin_can_modify_any_profile_membership(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            self._url(self.other_profile.id),
            {"enabled": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.other_membership.refresh_from_db()
        self.assertTrue(self.other_membership.enabled)
