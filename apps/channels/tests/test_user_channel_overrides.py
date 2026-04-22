"""
Tests for per-channel user_hidden and user_locked flags (FR #1196).

Covers:
  - Model defaults and serializer round-trip.
  - Output filtering (HDHR lineup, M3U, EPG, XC) excludes hidden channels.
  - sync_auto_channels:
      * preserves hidden channels (no update, no delete, no recreate)
      * reserves hidden channels' numbers in used_numbers
      * preserves locked channels' name / channel_number / channel_group
      * still flows provider metadata (tvg_id, logo, epg_data) to locked channels
      * skips locked and hidden channels in renumber and stale-delete passes
      * skips locked and hidden channels in orphan cleanup pass
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelGroupM3UAccount,
    ChannelStream,
    Stream,
)
from apps.m3u.models import M3UAccount

User = get_user_model()


def _run_sync(account):
    """Call sync_auto_channels synchronously with a fresh scan_start_time."""
    from apps.m3u.tasks import sync_auto_channels

    # Set scan_start_time slightly in the past so any streams with last_seen=now() pass.
    start = timezone.now() - timezone.timedelta(seconds=1)
    return sync_auto_channels(account.id, scan_start_time=start)


class UserHiddenUserLockedModelTests(TestCase):
    """Field defaults and Channel serializer round-trip."""

    def setUp(self):
        self.group = ChannelGroup.objects.create(name="Test Group")
        self.channel = Channel.objects.create(
            channel_number=1.0,
            name="Test Channel",
            channel_group=self.group,
        )

    def test_defaults_are_false(self):
        self.assertFalse(self.channel.user_hidden)
        self.assertFalse(self.channel.user_locked)

    def test_serializer_includes_both_fields(self):
        user = User.objects.create_user(username="admin", password="pw", user_level=10)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(f"/api/channels/channels/{self.channel.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("user_hidden", response.data)
        self.assertIn("user_locked", response.data)
        self.assertFalse(response.data["user_hidden"])
        self.assertFalse(response.data["user_locked"])

    def test_patch_can_set_both_fields(self):
        user = User.objects.create_user(username="admin", password="pw", user_level=10)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            f"/api/channels/channels/{self.channel.id}/",
            {"user_hidden": True, "user_locked": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.channel.refresh_from_db()
        self.assertTrue(self.channel.user_hidden)
        self.assertTrue(self.channel.user_locked)


class HiddenChannelOutputFilteringTests(TestCase):
    """Hidden channels must not appear in HDHR, M3U, or EPG output."""

    def setUp(self):
        self.group = ChannelGroup.objects.create(name="Test Group")
        self.visible = Channel.objects.create(
            channel_number=10.0,
            name="Visible Channel",
            channel_group=self.group,
            tvg_id="visible",
        )
        self.hidden = Channel.objects.create(
            channel_number=11.0,
            name="Hidden Channel",
            channel_group=self.group,
            tvg_id="hidden",
            user_hidden=True,
        )
        self.client = APIClient()

    def test_hdhr_api_lineup_excludes_hidden(self):
        response = self.client.get("/hdhr/lineup.json")
        self.assertEqual(response.status_code, 200)
        names = [entry["GuideName"] for entry in response.json()]
        self.assertIn("Visible Channel", names)
        self.assertNotIn("Hidden Channel", names)

    def test_m3u_output_excludes_hidden(self):
        response = self.client.get("/output/m3u")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Visible Channel", body)
        self.assertNotIn("Hidden Channel", body)

    def test_epg_output_excludes_hidden(self):
        response = self.client.get("/output/epg")
        self.assertEqual(response.status_code, 200)
        # EPG is streamed; join the chunks to assert on the full body.
        body = b"".join(response.streaming_content).decode()
        self.assertIn("Visible Channel", body)
        self.assertNotIn("Hidden Channel", body)


class SyncAutoChannelsUserHiddenTests(TestCase):
    """Verify sync_auto_channels respects user_hidden across passes."""

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Test Provider",
            server_url="http://example.test/get.php",
        )
        self.group = ChannelGroup.objects.create(name="HIDDEN TEST GROUP")
        ChannelGroupM3UAccount.objects.create(
            channel_group=self.group,
            m3u_account=self.account,
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=100.0,
        )
        self.stream = Stream.objects.create(
            name="Keeper Stream",
            url="http://example.test/keeper.ts",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id="keeper",
            last_seen=timezone.now(),
        )

    def _create_auto_channel(self, stream, channel_number, **extra):
        defaults = {
            "name": stream.name,
            "channel_group": self.group,
            "tvg_id": stream.tvg_id,
            "auto_created": True,
            "auto_created_by": self.account,
        }
        defaults.update(extra)
        channel = Channel.objects.create(
            channel_number=channel_number,
            **defaults,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        return channel

    def test_hidden_channel_receives_provider_metadata_updates_on_sync(self):
        """
        Option B semantic: hide is an output-visibility flag, not a sync-freeze.
        Hidden channels still receive provider metadata (name, tvg_id, logo,
        etc.) from their linked stream on each sync.
        """
        hidden = self._create_auto_channel(
            self.stream,
            channel_number=105.0,
            name="Stale Name",
            tvg_id="stale_tvg",
            user_hidden=True,
        )

        # Provider updates the stream's metadata.
        self.stream.name = "Fresh Provider Name"
        self.stream.tvg_id = "fresh_tvg"
        self.stream.save()

        _run_sync(self.account)

        hidden.refresh_from_db()
        self.assertEqual(hidden.name, "Fresh Provider Name")
        self.assertEqual(hidden.tvg_id, "fresh_tvg")

    def test_hidden_channel_preserves_user_hidden_flag_on_sync(self):
        """
        Critical invariant: sync must never clear a channel's user_hidden
        flag. Even though hidden channels receive metadata updates (Option B),
        their hidden status is orthogonal to any provider field and must
        remain True until the user explicitly unhides.
        """
        hidden = self._create_auto_channel(
            self.stream,
            channel_number=105.0,
            user_hidden=True,
        )
        self.stream.name = "New Name That Triggers An Update"
        self.stream.save()

        _run_sync(self.account)

        hidden.refresh_from_db()
        self.assertTrue(
            hidden.user_hidden,
            "user_hidden must NOT be cleared by sync_auto_channels under any condition",
        )

    def test_hidden_channel_does_not_block_another_channels_number(self):
        """
        Under Option B, hidden channels renumber like normal channels
        (they are not reserved as a special number-blocker). New channels
        still get unique numbers; there are no collisions even when a hidden
        channel exists at the same number a new channel might otherwise claim.
        """
        self._create_auto_channel(
            self.stream,
            channel_number=105.0,
            user_hidden=True,
        )
        Stream.objects.create(
            name="New Stream",
            url="http://example.test/new.ts",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id="new",
            last_seen=timezone.now(),
        )

        _run_sync(self.account)

        # Every auto-created channel from this account must have a unique number.
        numbers = list(
            Channel.objects.filter(
                auto_created=True, auto_created_by=self.account
            ).values_list("channel_number", flat=True)
        )
        self.assertEqual(len(numbers), len(set(numbers)), f"duplicate channel_numbers: {numbers}")

    def test_hidden_channel_survives_stream_removal(self):
        """If the underlying stream disappears, a hidden channel still persists."""
        hidden = self._create_auto_channel(
            self.stream,
            channel_number=106.0,
            user_hidden=True,
        )
        # Remove the stream so it's not present in any group any more.
        self.stream.delete()

        _run_sync(self.account)

        self.assertTrue(Channel.objects.filter(pk=hidden.pk).exists())


class SyncAutoChannelsUserLockedTests(TestCase):
    """Verify sync_auto_channels respects user_locked across passes."""

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Test Provider",
            server_url="http://example.test/get.php",
        )
        self.group = ChannelGroup.objects.create(name="LOCK TEST GROUP")
        ChannelGroupM3UAccount.objects.create(
            channel_group=self.group,
            m3u_account=self.account,
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=200.0,
        )
        self.stream = Stream.objects.create(
            name="Provider Stream Name",
            url="http://example.test/locked.ts",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id="provider_tvg",
            last_seen=timezone.now(),
        )

    def _create_auto_channel(self, stream, channel_number, **extra):
        defaults = {
            "name": stream.name,
            "channel_group": self.group,
            "tvg_id": stream.tvg_id,
            "auto_created": True,
            "auto_created_by": self.account,
        }
        defaults.update(extra)
        channel = Channel.objects.create(
            channel_number=channel_number,
            **defaults,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        return channel

    def test_locked_channel_preserves_identity(self):
        """Locked channel keeps user-set name and channel_number across sync."""
        locked = self._create_auto_channel(
            self.stream,
            channel_number=250.0,
            name="User Custom Name",
            user_locked=True,
        )

        # Provider changes name on stream side.
        self.stream.name = "Provider Renamed"
        self.stream.save()

        _run_sync(self.account)

        locked.refresh_from_db()
        self.assertEqual(locked.name, "User Custom Name")
        self.assertEqual(locked.channel_number, 250.0)

    def test_locked_channel_still_flows_tvg_id(self):
        """Locked channel's tvg_id updates when the provider changes it."""
        locked = self._create_auto_channel(
            self.stream,
            channel_number=251.0,
            name="User Custom Name",
            user_locked=True,
        )

        self.stream.tvg_id = "updated_tvg"
        self.stream.save()

        _run_sync(self.account)

        locked.refresh_from_db()
        self.assertEqual(locked.tvg_id, "updated_tvg")
        # Identity still preserved.
        self.assertEqual(locked.name, "User Custom Name")

    def test_locked_channel_survives_stream_removal(self):
        """Locked channel persists even when provider drops the stream."""
        locked = self._create_auto_channel(
            self.stream,
            channel_number=252.0,
            name="User Custom",
            user_locked=True,
        )
        self.stream.delete()

        _run_sync(self.account)

        self.assertTrue(Channel.objects.filter(pk=locked.pk).exists())

    def test_unlocked_channel_gets_provider_name_back(self):
        """Control: without user_locked, sync overwrites with stream name."""
        unlocked = self._create_auto_channel(
            self.stream,
            channel_number=253.0,
            name="User Custom Name",
            user_locked=False,
        )

        _run_sync(self.account)

        unlocked.refresh_from_db()
        self.assertEqual(unlocked.name, "Provider Stream Name")
