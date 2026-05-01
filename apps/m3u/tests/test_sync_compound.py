"""
Compound-fixture sync tests.

Where individual sync tests cover one variation at a time (multi-stream,
hidden, override, manual), this module seeds all of them in the same
fixture and asserts the constraints still hold when sync sees the full
mix on a single account. The point is to catch interactions that pass
each isolated test but break when the conditions overlap.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelGroupM3UAccount,
    ChannelOverride,
    ChannelStream,
    Stream,
)
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import sync_auto_channels


def _scan_start_time():
    return (timezone.now() - timedelta(minutes=1)).isoformat()


class CompoundFixtureSyncTests(TestCase):
    """
    Single fixture covers: multi-stream auto channel, hidden auto channel,
    auto channel with channel_number override, manual channel that shares
    the group with auto-created rows. After sync runs, every channel must
    end up in the state its individual test would have asserted.
    """

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Compound Provider",
            server_url="http://example.com/compound.m3u",
        )
        self.group = ChannelGroup.objects.create(name="Compound Group")
        self.relation = ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account,
            channel_group=self.group,
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=100,
            auto_sync_channel_end=199,
        )
        now = timezone.now()

        # ── Multi-stream auto channel: two streams, one fresh, one stale.
        # The channel must survive the stale stream's disappearance because
        # the fresh one keeps the channel alive.
        self.multi_stream_a = Stream.objects.create(
            name="MultiCh HD",
            url="http://example.com/multi-a.m3u8",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id="multi",
            last_seen=now,
        )
        self.multi_stream_b = Stream.objects.create(
            name="MultiCh HD",
            url="http://example.com/multi-b.m3u8",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id="multi",
            last_seen=now - timedelta(days=2),
        )
        self.multi_channel = Channel.objects.create(
            name="MultiCh HD",
            channel_number=100,
            channel_group=self.group,
            auto_created=True,
            auto_created_by=self.account,
        )
        ChannelStream.objects.create(
            channel=self.multi_channel, stream=self.multi_stream_a, order=0
        )
        ChannelStream.objects.create(
            channel=self.multi_channel, stream=self.multi_stream_b, order=1
        )

        # ── Hidden auto channel: visible from the table's perspective only
        # to admins with the Hidden filter on. Sync must not reuse its
        # channel_number for a different channel just because it's hidden.
        self.hidden_stream = Stream.objects.create(
            name="HiddenCh",
            url="http://example.com/hidden.m3u8",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id="hidden",
            last_seen=now,
        )
        self.hidden_channel = Channel.objects.create(
            name="HiddenCh",
            channel_number=101,
            channel_group=self.group,
            auto_created=True,
            auto_created_by=self.account,
            user_hidden=True,
        )
        ChannelStream.objects.create(
            channel=self.hidden_channel, stream=self.hidden_stream, order=0
        )

        # ── Overridden auto channel: user pinned channel_number to 150 via
        # an override row. Sync must not clobber the override; the
        # effective channel_number stays 150 even though the raw column
        # may evolve.
        self.overridden_stream = Stream.objects.create(
            name="OverriddenCh",
            url="http://example.com/overridden.m3u8",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id="overridden",
            last_seen=now,
        )
        self.overridden_channel = Channel.objects.create(
            name="OverriddenCh",
            channel_number=102,
            channel_group=self.group,
            auto_created=True,
            auto_created_by=self.account,
        )
        ChannelStream.objects.create(
            channel=self.overridden_channel,
            stream=self.overridden_stream,
            order=0,
        )
        ChannelOverride.objects.create(
            channel=self.overridden_channel,
            channel_number=150,
            name="My Pinned Name",
        )

        # ── Manual channel sharing the group: auto_created=False, user
        # picked channel_number 175 themselves. Sync must not touch this
        # row at all.
        self.manual_channel = Channel.objects.create(
            name="ManualCh",
            channel_number=175,
            channel_group=self.group,
            auto_created=False,
        )

        # New stream that has no existing channel; sync should create a
        # fresh channel for it within the configured range and skip
        # 100-102 (in use), 150 (overridden), 175 (manual).
        self.new_stream = Stream.objects.create(
            name="FreshCh",
            url="http://example.com/fresh.m3u8",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id="fresh",
            last_seen=now,
        )

    def test_compound_fixture_each_invariant_holds_after_sync(self):
        sync_auto_channels(self.account.id, scan_start_time=_scan_start_time())

        # Multi-stream channel survives.
        self.assertTrue(
            Channel.objects.filter(id=self.multi_channel.id).exists(),
            "Multi-stream channel was deleted even though one stream is alive",
        )

        # Hidden channel survives and remains hidden.
        self.hidden_channel.refresh_from_db()
        self.assertTrue(self.hidden_channel.user_hidden)

        # Overridden channel: the override row is intact, not cleared by
        # sync. The pinned channel_number persists.
        override = ChannelOverride.objects.get(channel=self.overridden_channel)
        self.assertEqual(override.channel_number, 150)
        self.assertEqual(override.name, "My Pinned Name")

        # Manual channel is untouched.
        self.manual_channel.refresh_from_db()
        self.assertFalse(self.manual_channel.auto_created)
        self.assertEqual(self.manual_channel.channel_number, 175)

        # The fresh stream becomes a new auto channel; its channel_number
        # falls inside the configured range and must not collide with any
        # existing number (100-102 used by the auto channels, 150 pinned
        # by the override, 175 the manual channel).
        fresh_stream_id = self.new_stream.id
        new_channel_qs = Channel.objects.filter(
            channelstream__stream_id=fresh_stream_id,
            auto_created=True,
            auto_created_by=self.account,
        ).distinct()
        self.assertEqual(
            new_channel_qs.count(),
            1,
            "Sync did not create exactly one channel for the new stream",
        )
        new_number = new_channel_qs.first().channel_number
        self.assertIsNotNone(new_number)
        self.assertGreaterEqual(new_number, 100)
        self.assertLessEqual(new_number, 199)
        self.assertNotIn(new_number, {100, 101, 102, 150, 175})

    def test_hidden_channel_number_not_reassigned_to_new_stream(self):
        # Targeted assertion isolated from the broader fixture invariants
        # so the failure mode is unambiguous when this single property
        # regresses.
        sync_auto_channels(self.account.id, scan_start_time=_scan_start_time())

        new_channel = (
            Channel.objects.filter(
                channelstream__stream_id=self.new_stream.id,
                auto_created=True,
                auto_created_by=self.account,
            )
            .distinct()
            .first()
        )
        self.assertIsNotNone(new_channel)
        self.assertNotEqual(
            new_channel.channel_number,
            self.hidden_channel.channel_number,
            "Hidden channel's number was reassigned; hidden channels must "
            "still occupy their slot in the used_numbers set",
        )

    def test_override_channel_number_preserved_through_sync(self):
        # If a future regression caused sync to write to ChannelOverride
        # (it must not), this test catches it because the override would
        # change after refresh.
        original_pin = 150
        sync_auto_channels(self.account.id, scan_start_time=_scan_start_time())

        override = ChannelOverride.objects.get(channel=self.overridden_channel)
        self.assertEqual(override.channel_number, original_pin)
