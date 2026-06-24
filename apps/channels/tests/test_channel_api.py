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
