from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
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
        data = response.json()
        row = next(r for r in data if r["id"] == self.channel.id)
        self.assertEqual(row["name"], "Override Name")
        self.assertEqual(row["channel_number"], 99.0)
        self.assertEqual(row["channel_group_id"], self.other_group.id)


class ChannelListEffectiveOrderingTests(TestCase):
    """
    Channels tab sorting uses ?ordering=channel_number / name, but the
    table displays effective_* values. Ordering must follow the override
    coalesced numbers and names, not the raw provider columns.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="order_admin", password="x"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.group = ChannelGroup.objects.create(name="Order Group")
        # Raw order would be B (2), C (10), A (500). Effective order is
        # A (1), B (2), C (3).
        self.channel_a = Channel.objects.create(
            channel_number=500.0,
            name="Zebra Provider",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(
            channel=self.channel_a,
            channel_number=1.0,
            name="Alpha Override",
        )
        self.channel_b = Channel.objects.create(
            channel_number=2.0,
            name="Beta Channel",
            channel_group=self.group,
            auto_created=True,
        )
        self.channel_c = Channel.objects.create(
            channel_number=10.0,
            name="Y Provider",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(
            channel=self.channel_c,
            channel_number=3.0,
            name="Charlie Override",
        )

    def test_list_orders_by_effective_channel_number(self):
        response = self.client.get(
            "/api/channels/channels/",
            {"ordering": "channel_number", "page_size": 50},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["results"]
        ordered_ids = [row["id"] for row in rows]
        self.assertEqual(
            ordered_ids,
            [self.channel_a.id, self.channel_b.id, self.channel_c.id],
        )
        self.assertEqual(
            [row["effective_channel_number"] for row in rows],
            [1.0, 2.0, 3.0],
        )

    def test_list_orders_by_effective_name(self):
        response = self.client.get(
            "/api/channels/channels/",
            {"ordering": "name", "page_size": 50},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["results"]
        self.assertEqual(
            [row["id"] for row in rows],
            [self.channel_a.id, self.channel_b.id, self.channel_c.id],
        )
        self.assertEqual(
            [row["effective_name"] for row in rows],
            ["Alpha Override", "Beta Channel", "Charlie Override"],
        )

    def test_get_ids_orders_by_effective_channel_number(self):
        response = self.client.get(
            "/api/channels/channels/ids/",
            {"ordering": "channel_number"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            [self.channel_a.id, self.channel_b.id, self.channel_c.id],
        )

    def _page_ids(self, **params):
        response = self.client.get("/api/channels/channels/", params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return [row["id"] for row in response.data["results"]]

    def test_pages_follow_effective_order_across_page_boundary(self):
        base = {"ordering": "channel_number", "page_size": 2}
        self.assertEqual(
            self._page_ids(page=1, **base),
            [self.channel_a.id, self.channel_b.id],
        )
        self.assertEqual(
            self._page_ids(page=2, **base), [self.channel_c.id]
        )

    def test_descending_effective_order(self):
        self.assertEqual(
            self._page_ids(ordering="-channel_number", page_size=50),
            [self.channel_c.id, self.channel_b.id, self.channel_a.id],
        )

    def test_default_order_is_descending_effective_number(self):
        self.assertEqual(
            self._page_ids(page_size=50),
            [self.channel_c.id, self.channel_b.id, self.channel_a.id],
        )

    def test_effective_order_with_profile_filter_has_no_duplicates(self):
        from apps.channels.models import ChannelProfile

        profile = ChannelProfile.objects.create(name="Order Profile")
        base = {
            "ordering": "channel_number",
            "channel_profile_id": profile.id,
            "page_size": 2,
        }
        first = self._page_ids(page=1, **base)
        second = self._page_ids(page=2, **base)
        self.assertEqual(
            first + second,
            [self.channel_a.id, self.channel_b.id, self.channel_c.id],
        )

    def test_unsortable_field_is_ignored(self):
        self.assertEqual(
            self._page_ids(ordering="uuid", page_size=50),
            [self.channel_c.id, self.channel_b.id, self.channel_a.id],
        )

    def test_other_ordering_fields_still_work(self):
        self.assertEqual(
            len(self._page_ids(ordering="channel_group__name", page_size=50)),
            3,
        )

    def test_list_orders_by_effective_group_name(self):
        # Raw group names would put A last (ZZZ), but its override pin lands
        # in AAA, so effective group order must put A first.
        early = ChannelGroup.objects.create(name="AAA Override Group")
        mid = ChannelGroup.objects.create(name="MMM Provider Group")
        late = ChannelGroup.objects.create(name="ZZZ Provider Group")
        self.channel_a.channel_group = late
        self.channel_a.save(update_fields=["channel_group"])
        self.channel_b.channel_group = mid
        self.channel_b.save(update_fields=["channel_group"])
        self.channel_c.channel_group = late
        self.channel_c.save(update_fields=["channel_group"])
        ChannelOverride.objects.filter(channel=self.channel_a).update(
            channel_group=early
        )

        self.assertEqual(
            self._page_ids(ordering="channel_group__name", page_size=50),
            [self.channel_a.id, self.channel_b.id, self.channel_c.id],
        )


class ChannelEffectiveWriteAPITests(TestCase):
    """
    Drag-reorder, assign, and from-stream must operate on effective
    channel numbers so override pins stay consistent with the UI.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="write_admin", password="x"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.group = ChannelGroup.objects.create(name="Write Group")

    def test_reorder_moves_using_effective_numbers(self):
        # Visible order by effective #: A(1), B(2), C(3). Raw would be
        # B(2), C(10), A(500). Drag A after C should place A at 3 and
        # shift C to 2; A is auto-synced so the new pin lands on override.
        channel_a = Channel.objects.create(
            channel_number=500.0,
            name="A",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel_a, channel_number=1.0)
        channel_b = Channel.objects.create(
            channel_number=2.0,
            name="B",
            channel_group=self.group,
        )
        channel_c = Channel.objects.create(
            channel_number=10.0,
            name="C",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel_c, channel_number=3.0)

        response = self.client.post(
            f"/api/channels/channels/{channel_a.id}/reorder/",
            {"insert_after_id": channel_c.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["channel"]["effective_channel_number"], 3.0)

        channel_a.refresh_from_db()
        channel_b.refresh_from_db()
        channel_c.refresh_from_db()
        # Provider raw numbers for auto-synced rows stay put; visible
        # order becomes B(1), C(2), A(3).
        self.assertEqual(channel_a.channel_number, 500.0)
        self.assertEqual(
            ChannelOverride.objects.get(channel=channel_a).channel_number, 3.0
        )
        self.assertEqual(
            ChannelOverride.objects.get(channel=channel_c).channel_number, 2.0
        )
        self.assertEqual(channel_b.channel_number, 1.0)

        ordered = self.client.get(
            "/api/channels/channels/",
            {"ordering": "channel_number", "page_size": 50},
        )
        self.assertEqual(
            [row["id"] for row in ordered.data["results"]],
            [channel_b.id, channel_c.id, channel_a.id],
        )

    def test_reorder_leaves_pinned_raw_number_outside_the_visible_gap(self):
        # Visible order is A(1), B(2), C(3). Spectator's raw 2 sits in the
        # numeric window, but its pin is 100, so the drag must not move it.
        channel_a = Channel.objects.create(
            channel_number=500.0,
            name="A",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel_a, channel_number=1.0)
        Channel.objects.create(
            channel_number=2.0, name="B", channel_group=self.group
        )
        channel_c = Channel.objects.create(
            channel_number=10.0,
            name="C",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel_c, channel_number=3.0)
        spectator = Channel.objects.create(
            channel_number=2.0,
            name="Spectator",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=spectator, channel_number=100.0)

        response = self.client.post(
            f"/api/channels/channels/{channel_a.id}/reorder/",
            {"insert_after_id": channel_c.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        spectator.refresh_from_db()
        self.assertEqual(spectator.channel_number, 2.0)
        self.assertEqual(
            ChannelOverride.objects.get(channel=spectator).channel_number, 100.0
        )

    def test_reorder_creates_override_for_auto_created_without_one(self):
        first = Channel.objects.create(
            channel_number=1.0, name="First", channel_group=self.group
        )
        second = Channel.objects.create(
            channel_number=2.0, name="Second", channel_group=self.group
        )
        synced = Channel.objects.create(
            channel_number=3.0,
            name="Synced",
            channel_group=self.group,
            auto_created=True,
        )
        self.assertFalse(ChannelOverride.objects.filter(channel=synced).exists())

        response = self.client.post(
            f"/api/channels/channels/{synced.id}/reorder/",
            {"insert_after_id": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["channel"]["effective_channel_number"], 1.0)

        synced.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(synced.channel_number, 3.0)
        self.assertEqual(
            ChannelOverride.objects.get(channel=synced).channel_number, 1.0
        )
        self.assertEqual((first.channel_number, second.channel_number), (2.0, 3.0))

    def test_reorder_rejects_unknown_target(self):
        channel = Channel.objects.create(
            channel_number=1.0, name="Only", channel_group=self.group
        )
        for bad_target in (999999, "not-an-id", ""):
            response = self.client.post(
                f"/api/channels/channels/{channel.id}/reorder/",
                {"insert_after_id": bad_target},
                format="json",
            )
            self.assertEqual(
                response.status_code, status.HTTP_404_NOT_FOUND, bad_target
            )

    def test_assign_rejects_invalid_channel_ids(self):
        response = self.client.post(
            "/api/channels/channels/assign/",
            {"channel_ids": ["nope"], "starting_number": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_duplicate_ids_do_not_crash(self):
        auto = Channel.objects.create(
            channel_number=50.0,
            name="Dup Auto",
            channel_group=self.group,
            auto_created=True,
        )
        response = self.client.post(
            "/api/channels/channels/assign/",
            {"channel_ids": [auto.id, auto.id], "starting_number": 7},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            ChannelOverride.objects.get(channel=auto).channel_number, 8.0
        )

    def test_assign_writes_override_for_auto_created(self):
        auto = Channel.objects.create(
            channel_number=50.0,
            name="Auto",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=auto, channel_number=9.0)
        manual = Channel.objects.create(
            channel_number=2.0,
            name="Manual",
            channel_group=self.group,
        )

        response = self.client.post(
            "/api/channels/channels/assign/",
            {"channel_ids": [auto.id, manual.id], "starting_number": 100},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        auto.refresh_from_db()
        manual.refresh_from_db()
        self.assertEqual(auto.channel_number, 50.0)
        self.assertEqual(
            ChannelOverride.objects.get(channel=auto).channel_number, 100.0
        )
        self.assertEqual(manual.channel_number, 101.0)

    def test_assign_matching_provider_number_keeps_other_overrides(self):
        auto = Channel.objects.create(
            channel_number=5.0,
            name="Provider",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(
            channel=auto,
            name="Kept Name",
            channel_number=9.0,
        )

        response = self.client.post(
            "/api/channels/channels/assign/",
            {"channel_ids": [auto.id], "starting_number": 5},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        override = ChannelOverride.objects.get(channel=auto)
        self.assertEqual(override.name, "Kept Name")
        self.assertIsNone(override.channel_number)

    def test_from_stream_highest_and_collision_use_overrides(self):
        from apps.channels.models import Stream
        from apps.m3u.models import M3UAccount

        Channel.objects.create(
            channel_number=1.0,
            name="Low raw",
            channel_group=self.group,
            auto_created=True,
        )
        pinned = Channel.objects.create(
            channel_number=2.0,
            name="Pinned high",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=pinned, channel_number=50.0)

        account = M3UAccount.objects.create(
            name="from-stream-acct",
            account_type="STD",
        )
        stream = Stream.objects.create(
            name="New Stream",
            url="http://example.com/new.ts",
            m3u_account=account,
            channel_group=self.group,
            stream_chno=50.0,
        )

        # Provider #50 is reserved by override; from-stream should skip it.
        response = self.client.post(
            "/api/channels/channels/from-stream/",
            {"stream_id": stream.id, "channel_number": 50},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.data["channel_number"], 50.0)

        stream2 = Stream.objects.create(
            name="Highest Stream",
            url="http://example.com/high.ts",
            m3u_account=account,
            channel_group=self.group,
        )
        response = self.client.post(
            "/api/channels/channels/from-stream/",
            {"stream_id": stream2.id, "channel_number": -1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Highest effective is at least 50; new channel should be > 50.
        self.assertGreater(response.data["channel_number"], 50.0)

    def test_search_matches_override_name(self):
        channel = Channel.objects.create(
            channel_number=1.0,
            name="Provider Name",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel, name="UniqueOverrideLabel")

        response = self.client.get(
            "/api/channels/channels/",
            {"search": "UniqueOverrideLabel", "page_size": 50},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids, [channel.id])

        ordered = self.client.get(
            "/api/channels/channels/",
            {"search": "UniqueOverrideLabel", "ordering": "channel_number", "page_size": 50},
        )
        self.assertEqual(ordered.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["id"] for row in ordered.data["results"]],
            [channel.id],
        )

    def test_bulk_create_reserves_override_pins(self):
        from apps.channels.models import Stream
        from apps.channels.tasks import bulk_create_channels_from_streams
        from apps.m3u.models import M3UAccount

        pinned = Channel.objects.create(
            channel_number=1.0,
            name="Pinned",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=pinned, channel_number=7.0)
        account = M3UAccount.objects.create(
            name="bulk-reserve-acct", account_type="STD"
        )
        stream = Stream.objects.create(
            name="Bulk Stream",
            url="http://example.com/bulk.ts",
            m3u_account=account,
            channel_group=self.group,
            stream_chno=7.0,
        )

        result = bulk_create_channels_from_streams.run(
            [stream.id], starting_channel_number=None
        )
        self.assertEqual(result["created_count"], 1)
        created = Channel.objects.exclude(id=pinned.id).get(name="Bulk Stream")
        self.assertNotEqual(created.channel_number, 7.0)


class ChannelListEffectiveFilterTests(TestCase):
    """
    Name, group, and EPG filters must match what the Channels table
    displays (override first, provider value as fallback).
    """

    def setUp(self):
        from apps.epg.models import EPGData, EPGSource

        self.user = User.objects.create_user(
            username="filter_admin", password="x"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.provider_group = ChannelGroup.objects.create(name="Provider Group")
        self.override_group = ChannelGroup.objects.create(name="Override Group")
        source = EPGSource.objects.create(name="Filter Src", source_type="xmltv")
        self.epg = EPGData.objects.create(
            tvg_id="filter.epg", name="Filter EPG", epg_source=source
        )

        self.overridden = Channel.objects.create(
            channel_number=1.0,
            name="Provider Name",
            channel_group=self.provider_group,
            auto_created=True,
        )
        ChannelOverride.objects.create(
            channel=self.overridden,
            name="Shown Name",
            channel_group=self.override_group,
            epg_data=self.epg,
        )
        self.plain = Channel.objects.create(
            channel_number=2.0,
            name="Plain Channel",
            channel_group=self.provider_group,
        )

    def _ids(self, **params):
        response = self.client.get(
            "/api/channels/channels/", {"page_size": 50, **params}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {row["id"] for row in response.data["results"]}

    def test_name_filter_uses_override_not_provider_name(self):
        self.assertEqual(self._ids(name="Shown"), {self.overridden.id})
        self.assertEqual(self._ids(name="Provider Name"), set())
        self.assertEqual(self._ids(name="Plain"), {self.plain.id})

    def test_channel_group_filter_uses_override_group(self):
        self.assertEqual(
            self._ids(channel_group="Override Group"), {self.overridden.id}
        )
        self.assertEqual(
            self._ids(channel_group="Provider Group"), {self.plain.id}
        )
        self.assertEqual(
            self._ids(channel_group="Override Group,Provider Group"),
            {self.overridden.id, self.plain.id},
        )

    def test_epg_filter_uses_override_epg(self):
        self.assertEqual(self._ids(epg="Filter Src"), {self.overridden.id})
        self.assertEqual(self._ids(epg="null"), {self.plain.id})

    def test_unassigned_epg_flag_ignores_override_only_assignment(self):
        self.plain.epg_data = self.epg
        self.plain.save(update_fields=["epg_data"])
        response = self.client.get("/api/channels/channels/", {"page_size": 50})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["has_unassigned_epg_channels"])

    def test_search_covers_effective_name_and_group(self):
        self.assertEqual(self._ids(search="Shown"), {self.overridden.id})
        self.assertEqual(self._ids(search="Override Group"), {self.overridden.id})
        self.assertEqual(
            self._ids(search="Provider Group"), {self.plain.id}
        )


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


class EpgIdsMappedToChannelsTests(TestCase):
    """Programme import must treat ChannelOverride.epg_data as a mapping."""

    def test_includes_override_only_assignment(self):
        from apps.channels.managers import (
            epg_ids_mapped_to_channels,
            is_epg_mapped_to_channel,
        )
        from apps.epg.models import EPGSource, EPGData

        group = ChannelGroup.objects.create(name="Mapped Override Group")
        source = EPGSource.objects.create(name="Mapped Override Src", source_type="xmltv")
        epg = EPGData.objects.create(
            name="Override Station",
            epg_source=source,
            tvg_id="override.map",
        )
        channel = Channel.objects.create(
            channel_number=1.0,
            name="Provider",
            channel_group=group,
            epg_data=None,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel, epg_data=epg)

        self.assertEqual(epg_ids_mapped_to_channels(epg_source=source), {epg.id})
        self.assertTrue(is_epg_mapped_to_channel(epg))

    def test_excludes_unmapped_epg(self):
        from apps.channels.managers import (
            epg_ids_mapped_to_channels,
            is_epg_mapped_to_channel,
        )
        from apps.epg.models import EPGSource, EPGData

        source = EPGSource.objects.create(name="Unmapped Src", source_type="xmltv")
        epg = EPGData.objects.create(
            name="Unmapped Station",
            epg_source=source,
            tvg_id="unmapped.map",
        )

        self.assertEqual(epg_ids_mapped_to_channels(epg_source=source), set())
        self.assertFalse(is_epg_mapped_to_channel(epg))


class SeriesRuleAPITests(TestCase):
    """API tests for series rule CRUD and bulk-remove endpoints."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin_sr", password="pass")
        self.admin.user_level = 10
        self.admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

        from core.models import CoreSettings
        CoreSettings.set_dvr_series_rules([])

        self.rules_url = "/api/channels/series-rules/"
        self.bulk_remove_url = "/api/channels/series-rules/bulk-remove/"

    # --- POST (create/upsert) ---

    def test_create_rule_with_tvg_id(self):
        resp = self.client.post(self.rules_url, {
            "tvg_id": "some.channel", "title": "My Show", "mode": "all",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["rules"]), 1)
        self.assertEqual(resp.data["rules"][0]["tvg_id"], "some.channel")

    def test_create_title_only_rule_no_tvg_id(self):
        """A rule with no tvg_id (title-only) is accepted when title is provided."""
        resp = self.client.post(self.rules_url, {
            "tvg_id": "", "title": "Untethered Show", "mode": "all",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rule = resp.data["rules"][0]
        self.assertEqual(rule["tvg_id"], "")
        self.assertEqual(rule["title"], "Untethered Show")

    def test_create_rule_requires_title_or_description(self):
        resp = self.client.post(self.rules_url, {
            "tvg_id": "some.channel", "title": "", "description": "",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upsert_key_is_tvg_id_and_title(self):
        """Two POST requests with same tvg_id but different titles create two rules."""
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
        }, format="json")
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show B", "mode": "all",
        }, format="json")
        resp = self.client.get(self.rules_url)
        self.assertEqual(len(resp.data["rules"]), 2)

    def test_upsert_updates_existing_rule(self):
        """POSTing with an existing (tvg_id, title) pair updates in place."""
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
        }, format="json")
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "new",
        }, format="json")
        resp = self.client.get(self.rules_url)
        self.assertEqual(len(resp.data["rules"]), 1)
        self.assertEqual(resp.data["rules"][0]["mode"], "new")

    def test_create_rule_stores_epg_source_id(self):
        resp = self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
            "epg_source_id": 11,
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["rules"][0]["epg_source_id"], 11)

    def test_saving_sourced_rule_upgrades_legacy_unsourced_rule(self):
        """Re-saving a legacy (tvg_id, title) rule with epg_source_id updates it."""
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
        }, format="json")
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
            "epg_source_id": 11,
        }, format="json")
        resp = self.client.get(self.rules_url)
        self.assertEqual(len(resp.data["rules"]), 1)
        self.assertEqual(resp.data["rules"][0]["epg_source_id"], 11)

    def test_two_sources_same_title_are_distinct_rules(self):
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
            "epg_source_id": 11,
        }, format="json")
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
            "epg_source_id": 12,
        }, format="json")
        resp = self.client.get(self.rules_url)
        self.assertEqual(len(resp.data["rules"]), 2)

    # --- DELETE (query params) ---

    def test_delete_rule_by_tvg_id_and_title(self):
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
        }, format="json")
        resp = self.client.delete(
            self.rules_url + "?tvg_id=ch.1&title=Show+A"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["rules"], [])

    def test_delete_title_only_rule(self):
        """Title-only rules (tvg_id='') are deleted via empty tvg_id query param."""
        self.client.post(self.rules_url, {
            "tvg_id": "", "title": "Untethered Show", "mode": "all",
        }, format="json")
        resp = self.client.delete(
            self.rules_url + "?tvg_id=&title=Untethered+Show"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["rules"], [])

    def test_delete_with_epg_source_id_removes_legacy_unsourced_rule(self):
        """DVR card deletes pass program.epg_source_id even when the rule has none."""
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
        }, format="json")
        resp = self.client.delete(
            self.rules_url + "?tvg_id=ch.1&title=Show+A&epg_source_id=11"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["rules"], [])

    def test_delete_with_epg_source_id_leaves_other_source(self):
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
            "epg_source_id": 11,
        }, format="json")
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
            "epg_source_id": 12,
        }, format="json")
        resp = self.client.delete(
            self.rules_url + "?tvg_id=ch.1&title=Show+A&epg_source_id=11"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["rules"]), 1)
        self.assertEqual(resp.data["rules"][0]["epg_source_id"], 12)

    def test_delete_sourced_rule_leaves_other_source_recordings(self):
        """Deleting one sourced rule does not remove the other source's upcoming list."""
        from apps.channels.models import Recording

        group = ChannelGroup.objects.create(name="G-src")
        channel = Channel.objects.create(
            channel_number=11, name="ChSrc", channel_group=group
        )
        now = timezone.now()
        keep = Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            custom_properties={
                "program": {
                    "tvg_id": "ch.1",
                    "title": "Show A",
                    "epg_source_id": 12,
                }
            },
        )
        Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=4),
            custom_properties={
                "program": {
                    "tvg_id": "ch.1",
                    "title": "Show A",
                    "epg_source_id": 11,
                }
            },
        )
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
            "epg_source_id": 11,
        }, format="json")
        self.client.post(self.rules_url, {
            "tvg_id": "ch.1", "title": "Show A", "mode": "all",
            "epg_source_id": 12,
        }, format="json")
        resp = self.client.delete(
            self.rules_url + "?tvg_id=ch.1&title=Show+A&epg_source_id=11"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["removed"], 1)
        self.assertEqual(list(Recording.objects.values_list("id", flat=True)), [keep.id])

    def test_bulk_remove_sourced_leaves_other_source_recordings(self):
        from apps.channels.models import Recording

        group = ChannelGroup.objects.create(name="G-bulk-src")
        channel = Channel.objects.create(
            channel_number=12, name="ChBulkSrc", channel_group=group
        )
        now = timezone.now()
        keep = Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            custom_properties={
                "program": {
                    "tvg_id": "ch.1",
                    "title": "Show A",
                    "epg_source_id": 12,
                }
            },
        )
        Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=4),
            custom_properties={
                "program": {
                    "tvg_id": "ch.1",
                    "title": "Show A",
                    "epg_source_id": 11,
                }
            },
        )
        resp = self.client.post(self.bulk_remove_url, {
            "tvg_id": "ch.1",
            "title": "Show A",
            "scope": "title",
            "epg_source_id": 11,
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["removed"], 1)
        self.assertEqual(list(Recording.objects.values_list("id", flat=True)), [keep.id])

    def test_delete_only_removes_matching_rule(self):
        """Delete by (tvg_id, title) leaves other rules intact."""
        self.client.post(self.rules_url, {"tvg_id": "ch.1", "title": "Show A", "mode": "all"}, format="json")
        self.client.post(self.rules_url, {"tvg_id": "ch.1", "title": "Show B", "mode": "all"}, format="json")
        self.client.delete(self.rules_url + "?tvg_id=ch.1&title=Show+A")
        resp = self.client.get(self.rules_url)
        self.assertEqual(len(resp.data["rules"]), 1)
        self.assertEqual(resp.data["rules"][0]["title"], "Show B")

    def test_delete_removes_future_recordings(self):
        """DELETE cleans up future recordings that matched the rule."""
        from apps.channels.models import Recording

        group = ChannelGroup.objects.create(name="G")
        channel = Channel.objects.create(channel_number=1, name="Ch", channel_group=group)
        now = timezone.now()
        Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            custom_properties={"program": {"tvg_id": "ch.1", "title": "Show A"}},
        )

        self.client.post(self.rules_url, {"tvg_id": "ch.1", "title": "Show A", "mode": "all"}, format="json")
        self.client.delete(self.rules_url + "?tvg_id=ch.1&title=Show+A")
        self.assertEqual(Recording.objects.count(), 0)

    # --- POST bulk-remove ---

    def test_bulk_remove_with_tvg_id(self):
        from apps.channels.models import Recording

        group = ChannelGroup.objects.create(name="G2")
        channel = Channel.objects.create(channel_number=2, name="Ch2", channel_group=group)
        now = timezone.now()
        Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            custom_properties={"program": {"tvg_id": "ch.x", "title": "Show X"}},
        )
        resp = self.client.post(self.bulk_remove_url, {"tvg_id": "ch.x"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["removed"], 1)
        self.assertEqual(Recording.objects.count(), 0)

    def test_bulk_remove_title_only_no_tvg_id(self):
        """Bulk-remove accepts title alone (no tvg_id) for title-only rules."""
        from apps.channels.models import Recording

        group = ChannelGroup.objects.create(name="G3")
        channel = Channel.objects.create(channel_number=3, name="Ch3", channel_group=group)
        now = timezone.now()
        Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            custom_properties={"program": {"tvg_id": "ch.a", "title": "Cross Show"}},
        )
        Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=4),
            custom_properties={"program": {"tvg_id": "ch.b", "title": "Cross Show"}},
        )
        resp = self.client.post(self.bulk_remove_url, {"title": "Cross Show"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["removed"], 2)

    def test_bulk_remove_requires_tvg_id_or_title(self):
        resp = self.client.post(self.bulk_remove_url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class ChannelListIncludeStreamsQueryTests(TestCase):
    """include_streams=true must not issue one stream query per channel."""

    def setUp(self):
        from apps.channels.models import ChannelStream, Stream
        from apps.m3u.models import M3UAccount

        self.user = User.objects.create_user(username="list_admin", password="x")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.account = M3UAccount.objects.create(
            name="list-test-account",
            account_type="XC",
            username="user",
            password="pass",
        )
        self.group = ChannelGroup.objects.create(name=f"List Group {self.id}")

    def _add_channel_with_stream(self, number):
        from apps.channels.models import ChannelStream, Stream

        channel = Channel.objects.create(
            channel_number=float(number),
            name=f"Channel {number}",
            channel_group=self.group,
        )
        stream = Stream.objects.create(
            name=f"Stream {number}",
            url=f"http://example.com/{number}.ts",
            m3u_account=self.account,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        return channel

    def _query_count_for_list(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                "/api/channels/channels/",
                {"page": 1, "page_size": 50, "include_streams": "true"},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return len(ctx.captured_queries)

    def test_include_streams_query_count_stable_as_channels_grow(self):
        self._add_channel_with_stream(1)
        self._add_channel_with_stream(2)
        self._add_channel_with_stream(3)
        q_small = self._query_count_for_list()

        self._add_channel_with_stream(4)
        self._add_channel_with_stream(5)
        self._add_channel_with_stream(6)
        self._add_channel_with_stream(7)
        q_large = self._query_count_for_list()

        self.assertEqual(
            q_small,
            q_large,
            "include_streams list should use prefetched channelstream_set, "
            "not one streams M2M query per channel",
        )


class ChannelAssignedProfileScopeTests(TestCase):
    """Non-admin with assigned profiles: list, summary, get_ids, and retrieve
    by id are limited to enabled memberships in those profiles.
    """

    def setUp(self):
        from apps.channels.models import ChannelProfile, ChannelProfileMembership

        self.group = ChannelGroup.objects.create(name="Profile Scope Group")
        self.in_profile = Channel.objects.create(
            channel_number=1.0, name="In Profile", channel_group=self.group,
        )
        self.out_of_profile = Channel.objects.create(
            channel_number=2.0, name="Out Of Profile", channel_group=self.group,
        )

        # Profile creation auto-adds enabled memberships for every existing
        # channel; disable the one we want excluded.
        self.profile = ChannelProfile.objects.create(name="Assigned Profile")
        ChannelProfileMembership.objects.filter(
            channel_profile=self.profile, channel=self.out_of_profile,
        ).update(enabled=False)

        self.user = User.objects.create_user(username="profile_scoped", password="x")
        self.user.user_level = User.UserLevel.STANDARD
        self.user.save()
        self.user.channel_profiles.add(self.profile)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_summary_limited_to_assigned_profile_union(self):
        response = self.client.get("/api/channels/channels/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.json()}
        self.assertEqual(ids, {self.in_profile.id})

    def test_list_limited_to_assigned_profile_union(self):
        response = self.client.get(
            "/api/channels/channels/", {"page": 1, "page_size": 50}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.in_profile.id})

    def test_retrieve_reaches_channel_inside_assigned_profile(self):
        response = self.client.get(f"/api/channels/channels/{self.in_profile.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.in_profile.id)

    def test_retrieve_hides_channel_outside_assigned_profile(self):
        response = self.client.get(
            f"/api/channels/channels/{self.out_of_profile.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_with_streams_does_not_expose_provider_urls_outside_profile(self):
        from apps.channels.models import Stream

        stream = Stream.objects.create(
            name="Provider", url="http://provider.example/live/secret"
        )
        self.out_of_profile.streams.add(stream)
        response = self.client.get(
            f"/api/channels/channels/{self.out_of_profile.id}/",
            {"include_streams": "true"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn(b"provider.example", response.content)

    def test_unassigned_profile_id_returns_nothing(self):
        from apps.channels.models import ChannelProfile

        other = ChannelProfile.objects.create(name="Not Assigned")
        response = self.client.get(
            "/api/channels/channels/summary/", {"channel_profile_id": other.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])

    def test_show_disabled_does_not_escape_assigned_profiles(self):
        response = self.client.get(
            "/api/channels/channels/summary/",
            {"channel_profile_id": self.profile.id, "show_disabled": "true"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.json()}
        self.assertEqual(ids, {self.in_profile.id})

    def test_explicit_profile_id_still_scopes_by_membership(self):
        response = self.client.get(
            "/api/channels/channels/summary/",
            {"channel_profile_id": self.profile.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.json()}
        self.assertEqual(ids, {self.in_profile.id})

    def test_profile_id_all_uses_assigned_profile_union(self):
        response = self.client.get(
            "/api/channels/channels/summary/",
            {"channel_profile_id": "all"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.json()}
        self.assertEqual(ids, {self.in_profile.id})


class ChannelGroupVisibilityTests(TestCase):
    """Non-admin group list is scoped by user_level / adult hide, not profiles."""

    def setUp(self):
        from apps.channels.models import ChannelProfile, ChannelProfileMembership

        self.sports = ChannelGroup.objects.create(name="Sports")
        self.adult = ChannelGroup.objects.create(name="Adult")
        self.premium = ChannelGroup.objects.create(name="Premium")
        self.empty = ChannelGroup.objects.create(name="Empty Unused")

        self.sports_ch = Channel.objects.create(
            channel_number=1.0,
            name="Sports 1",
            channel_group=self.sports,
            user_level=0,
            is_adult=False,
        )
        self.adult_ch = Channel.objects.create(
            channel_number=2.0,
            name="Adult 1",
            channel_group=self.adult,
            user_level=0,
            is_adult=True,
        )
        self.premium_ch = Channel.objects.create(
            channel_number=3.0,
            name="Premium 1",
            channel_group=self.premium,
            user_level=5,
            is_adult=False,
        )

        # Profile only enables sports; groups API must still expose other
        # activatable groups (not profile-limited).
        self.profile = ChannelProfile.objects.create(name="Sports Only")
        ChannelProfileMembership.objects.filter(
            channel_profile=self.profile,
            channel__in=[self.adult_ch, self.premium_ch],
        ).update(enabled=False)

        self.user = User.objects.create_user(username="group_viewer", password="x")
        self.user.user_level = 1
        self.user.custom_properties = {"hide_adult_content": True}
        self.user.save()
        self.user.channel_profiles.add(self.profile)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_standard_user_sees_groups_for_activatable_channels_only(self):
        response = self.client.get("/api/channels/groups/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in response.data}
        self.assertIn("Sports", names)
        self.assertNotIn("Adult", names)
        self.assertNotIn("Premium", names)
        self.assertNotIn("Empty Unused", names)
        sports = next(row for row in response.data if row["name"] == "Sports")
        self.assertEqual(sports["channel_count"], 1)
        self.assertEqual(sports["m3u_accounts"], [])
        self.assertEqual(sports["m3u_account_count"], 0)

    def test_standard_user_groups_not_limited_by_assigned_profiles(self):
        # Raise level so Premium is activatable; still only Sports is in profile.
        self.user.user_level = 5
        self.user.save()
        response = self.client.get("/api/channels/groups/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in response.data}
        self.assertIn("Sports", names)
        self.assertIn("Premium", names)
        self.assertNotIn("Adult", names)

    def test_admin_sees_all_groups(self):
        admin = User.objects.create_user(username="group_admin", password="x")
        admin.user_level = 10
        admin.save()
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get("/api/channels/groups/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in response.data}
        self.assertTrue(
            {"Sports", "Adult", "Premium", "Empty Unused"}.issubset(names)
        )


class ChannelListOnlyCatchupFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="catchup_filter", password="x")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.catchup_channel = Channel.objects.create(
            channel_number=1.0,
            name="Catch-up Channel",
            is_catchup=True,
            catchup_days=7,
        )
        self.live_channel = Channel.objects.create(
            channel_number=2.0,
            name="Live Channel",
            is_catchup=False,
        )

    def test_only_catchup_returns_catchup_channels(self):
        response = self.client.get(
            "/api/channels/channels/",
            {"only_catchup": "true", "page": 1, "page_size": 50},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.catchup_channel.id})

    def test_only_catchup_does_not_force_distinct(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                "/api/channels/channels/",
                {"only_catchup": "true", "page": 1, "page_size": 50},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sql = " ".join(q["sql"] for q in ctx.captured_queries).upper()
        self.assertNotIn("DISTINCT", sql)


class ChannelListOnlyRadioFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="radio_filter", password="x")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.radio_channel = Channel.objects.create(
            channel_number=1.0,
            name="Radio Channel",
            is_radio=True,
        )
        self.tv_channel = Channel.objects.create(
            channel_number=2.0,
            name="TV Channel",
            is_radio=False,
        )

    def test_only_radio_returns_radio_channels(self):
        response = self.client.get(
            "/api/channels/channels/",
            {"only_radio": "true", "page": 1, "page_size": 50},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.radio_channel.id})

    def test_only_radio_uses_override(self):
        ChannelOverride.objects.create(channel=self.radio_channel, is_radio=False)
        ChannelOverride.objects.create(channel=self.tv_channel, is_radio=True)

        response = self.client.get(
            "/api/channels/channels/",
            {"only_radio": "true", "page": 1, "page_size": 50},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.tv_channel.id})


class ChannelRadioEditTests(TestCase):
    """Radio edits: override row on auto-synced channels, column on manual ones."""

    def setUp(self):
        from apps.m3u.models import M3UAccount

        self.user = User.objects.create_user(username="radio_edit", password="x")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.account = M3UAccount.objects.create(
            name="radio-edit-account",
            server_url="http://example.com/list.m3u",
        )

    def _stream(self, is_radio):
        from apps.channels.models import Stream

        return Stream.objects.create(
            name="Radio Stream",
            url="http://example.com/radio.ts",
            m3u_account=self.account,
            is_radio=is_radio,
        )

    def test_from_stream_copies_radio(self):
        stream = self._stream(is_radio=True)

        response = self.client.post(
            "/api/channels/channels/from-stream/",
            {"stream_id": stream.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Channel.objects.get(pk=response.data["id"]).is_radio)

    def test_override_false_is_stored_and_reported(self):
        channel = Channel.objects.create(
            channel_number=1.0,
            name="Auto Radio",
            auto_created=True,
            auto_created_by=self.account,
            is_radio=True,
        )

        response = self.client.patch(
            f"/api/channels/channels/{channel.id}/",
            {"override": {"is_radio": False}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(ChannelOverride.objects.get(channel=channel).is_radio, False)
        channel.refresh_from_db()
        self.assertTrue(channel.is_radio)
        detail = self.client.get(f"/api/channels/channels/{channel.id}/")
        self.assertIs(detail.data["effective_is_radio"], False)

    def test_bulk_edit_routes_radio_like_the_editor(self):
        auto = Channel.objects.create(
            channel_number=3.0,
            name="Auto Bulk",
            auto_created=True,
            auto_created_by=self.account,
            is_radio=True,
        )
        manual = Channel.objects.create(channel_number=4.0, name="Manual Bulk")

        response = self.client.patch(
            "/api/channels/channels/edit/bulk/",
            [
                {"id": auto.id, "override": {"is_radio": False}},
                {"id": manual.id, "is_radio": True},
            ],
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIs(ChannelOverride.objects.get(channel=auto).is_radio, False)
        manual.refresh_from_db()
        self.assertTrue(manual.is_radio)

    def test_manual_channel_saves_column(self):
        channel = Channel.objects.create(channel_number=2.0, name="Manual")

        response = self.client.patch(
            f"/api/channels/channels/{channel.id}/",
            {"is_radio": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        channel.refresh_from_db()
        self.assertTrue(channel.is_radio)
        self.assertFalse(ChannelOverride.objects.filter(channel=channel).exists())
