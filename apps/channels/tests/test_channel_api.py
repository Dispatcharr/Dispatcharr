from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.channels.models import Channel, ChannelGroup

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
