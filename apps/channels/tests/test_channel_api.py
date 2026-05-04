from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.channels.models import Channel, ChannelGroup, ChannelOverride

User = get_user_model()


class ChannelBulkEditAPITests(TestCase):
    def setUp(self):
        # Create a test admin user (user_level >= 10) and authenticate
        self.user = User.objects.create_user(username="testuser", password="testpass123")
        self.user.user_level = 10  # Set admin level
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.bulk_edit_url = "/api/channels/channels/edit/bulk/"

        # Create test channel group
        self.group1 = ChannelGroup.objects.create(name="Test Group 1")
        self.group2 = ChannelGroup.objects.create(name="Test Group 2")

        # Create test channels
        self.channel1 = Channel.objects.create(
            channel_number=1.0,
            name="Channel 1",
            tvg_id="channel1",
            channel_group=self.group1
        )
        self.channel2 = Channel.objects.create(
            channel_number=2.0,
            name="Channel 2",
            tvg_id="channel2",
            channel_group=self.group1
        )
        self.channel3 = Channel.objects.create(
            channel_number=3.0,
            name="Channel 3",
            tvg_id="channel3"
        )

    def test_bulk_edit_success(self):
        """Test successful bulk update of multiple channels"""
        data = [
            {"id": self.channel1.id, "name": "Updated Channel 1"},
            {"id": self.channel2.id, "name": "Updated Channel 2", "channel_number": 22.0},
        ]

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Successfully updated 2 channels")
        self.assertEqual(len(response.data["channels"]), 2)

        # Verify database changes
        self.channel1.refresh_from_db()
        self.channel2.refresh_from_db()
        self.assertEqual(self.channel1.name, "Updated Channel 1")
        self.assertEqual(self.channel2.name, "Updated Channel 2")
        self.assertEqual(self.channel2.channel_number, 22.0)

    def test_bulk_edit_with_empty_validated_data_first(self):
        """
        Test the bug fix: when first channel has empty validated_data.
        This was causing: ValueError: Field names must be given to bulk_update()
        """
        # Create a channel with data that will be "unchanged" (empty validated_data)
        # We'll send the same data it already has
        data = [
            # First channel: no actual changes (this would create empty validated_data)
            {"id": self.channel1.id},
            # Second channel: has changes
            {"id": self.channel2.id, "name": "Updated Channel 2"},
        ]

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        # Should not crash with ValueError
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Successfully updated 2 channels")

        # Verify the channel with changes was updated
        self.channel2.refresh_from_db()
        self.assertEqual(self.channel2.name, "Updated Channel 2")

    def test_bulk_edit_all_empty_updates(self):
        """Test when all channels have empty updates (no actual changes)"""
        data = [
            {"id": self.channel1.id},
            {"id": self.channel2.id},
        ]

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        # Should succeed without calling bulk_update
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Successfully updated 2 channels")

    def test_bulk_edit_mixed_fields(self):
        """Test bulk update where different channels update different fields"""
        data = [
            {"id": self.channel1.id, "name": "New Name 1"},
            {"id": self.channel2.id, "channel_number": 99.0},
            {"id": self.channel3.id, "tvg_id": "new_tvg_id", "name": "New Name 3"},
        ]

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Successfully updated 3 channels")

        # Verify all updates
        self.channel1.refresh_from_db()
        self.channel2.refresh_from_db()
        self.channel3.refresh_from_db()

        self.assertEqual(self.channel1.name, "New Name 1")
        self.assertEqual(self.channel2.channel_number, 99.0)
        self.assertEqual(self.channel3.tvg_id, "new_tvg_id")
        self.assertEqual(self.channel3.name, "New Name 3")

    def test_bulk_edit_with_channel_group(self):
        """Test bulk update with channel_group_id changes"""
        data = [
            {"id": self.channel1.id, "channel_group_id": self.group2.id},
            {"id": self.channel3.id, "channel_group_id": self.group1.id},
        ]

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify group changes
        self.channel1.refresh_from_db()
        self.channel3.refresh_from_db()
        self.assertEqual(self.channel1.channel_group, self.group2)
        self.assertEqual(self.channel3.channel_group, self.group1)

    def test_bulk_edit_nonexistent_channel(self):
        """Test bulk update with a channel that doesn't exist"""
        nonexistent_id = 99999
        data = [
            {"id": nonexistent_id, "name": "Should Fail"},
            {"id": self.channel1.id, "name": "Should Still Update"},
        ]

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        # Should return 400 with errors
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("errors", response.data)
        self.assertEqual(len(response.data["errors"]), 1)
        self.assertEqual(response.data["errors"][0]["channel_id"], nonexistent_id)
        self.assertEqual(response.data["errors"][0]["error"], "Channel not found")

        # The valid channel should still be updated
        self.assertEqual(response.data["updated_count"], 1)

    def test_bulk_edit_validation_error(self):
        """Test bulk update with invalid data (validation error)"""
        data = [
            {"id": self.channel1.id, "channel_number": "invalid_number"},
        ]

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        # Should return 400 with validation errors
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("errors", response.data)
        self.assertEqual(len(response.data["errors"]), 1)
        self.assertIn("channel_number", response.data["errors"][0]["errors"])

    def test_bulk_edit_empty_channel_updates(self):
        """Test bulk update with empty list"""
        data = []

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        # Empty list is accepted and returns success with 0 updates
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Successfully updated 0 channels")

    def test_bulk_edit_missing_channel_updates(self):
        """Test bulk update without proper format (dict instead of list)"""
        data = {"channel_updates": {}}

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Expected a list of channel updates")

    def test_bulk_edit_preserves_other_fields(self):
        """Test that bulk update only changes specified fields"""
        original_channel_number = self.channel1.channel_number
        original_tvg_id = self.channel1.tvg_id

        data = [
            {"id": self.channel1.id, "name": "Only Name Changed"},
        ]

        response = self.client.patch(self.bulk_edit_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify only name changed, other fields preserved
        self.channel1.refresh_from_db()
        self.assertEqual(self.channel1.name, "Only Name Changed")
        self.assertEqual(self.channel1.channel_number, original_channel_number)
        self.assertEqual(self.channel1.tvg_id, original_tvg_id)

    def test_bulk_swap_clear_and_assign_same_number(self):
        # User clears channel A's override (which currently pins #10) and
        # in the same bulk request sets channel B's override.channel_number
        # to #10. Both halves of the swap must succeed; the resulting
        # state has A unpinned and B pinned at #10.
        auto_a = Channel.objects.create(
            channel_number=1.0,
            name="Auto A",
            tvg_id="auto_a",
            channel_group=self.group1,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=auto_a, channel_number=10.0)
        auto_b = Channel.objects.create(
            channel_number=2.0,
            name="Auto B",
            tvg_id="auto_b",
            channel_group=self.group1,
            auto_created=True,
        )

        data = [
            {"id": auto_a.id, "override": None},
            {"id": auto_b.id, "override": {"channel_number": 10.0}},
        ]
        response = self.client.patch(self.bulk_edit_url, data, format="json")

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            f"Expected 200; got {response.status_code} body={response.data}",
        )
        self.assertFalse(
            ChannelOverride.objects.filter(channel=auto_a).exists()
        )
        b_override = ChannelOverride.objects.get(channel=auto_b)
        self.assertEqual(b_override.channel_number, 10.0)


class ChannelSummaryEffectiveValuesTests(TestCase):
    """
    The /api/channels/channels/summary/ endpoint feeds the TV Guide.
    Like every downstream output surface, it must reflect the user's
    overrides (name, channel_number, logo_id, epg_data_id,
    channel_group_id) instead of the raw provider values, otherwise
    the in-app guide would silently disagree with HDHR / M3U / EPG /
    XC clients on the same channel set.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        from apps.channels.models import ChannelOverride

        User = get_user_model()
        self.user = User.objects.create_user(
            username="summary_admin", password="x"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.group = ChannelGroup.objects.create(name="Summary Group")
        self.other_group = ChannelGroup.objects.create(name="Other")
        self.channel = Channel.objects.create(
            channel_number=10.0,
            name="Provider Name",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(
            channel=self.channel,
            name="Override Name",
            channel_number=99.0,
            channel_group=self.other_group,
        )

    def test_summary_returns_effective_values(self):
        response = self.client.get("/api/channels/channels/summary/")
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data if r["id"] == self.channel.id)
        self.assertEqual(row["name"], "Override Name")
        self.assertEqual(row["channel_number"], 99.0)
        self.assertEqual(row["channel_group_id"], self.other_group.id)


class ChannelManagerEffectiveValuesTests(TestCase):
    """
    The chainable ``Channel.objects.with_effective_values()`` shortcut
    must return rows with the same ``effective_*`` annotations the
    module-level helper produces, since both forms are documented
    entry points and a divergence would silently change output for
    one set of callers.
    """

    def test_manager_shortcut_matches_module_helper(self):
        from apps.channels.managers import with_effective_values

        group = ChannelGroup.objects.create(name="Manager Test")
        channel = Channel.objects.create(
            channel_number=42.0,
            name="Original Name",
            channel_group=group,
            auto_created=True,
        )
        ChannelOverride.objects.create(
            channel=channel,
            name="Renamed",
            channel_number=99.0,
        )

        helper_row = with_effective_values(
            Channel.objects.filter(id=channel.id)
        ).get()
        shortcut_row = (
            Channel.objects.with_effective_values()
            .filter(id=channel.id)
            .get()
        )

        self.assertEqual(helper_row.effective_name, "Renamed")
        self.assertEqual(shortcut_row.effective_name, "Renamed")
        self.assertEqual(helper_row.effective_channel_number, 99.0)
        self.assertEqual(shortcut_row.effective_channel_number, 99.0)
        self.assertEqual(
            helper_row.effective_channel_group_id,
            shortcut_row.effective_channel_group_id,
        )
