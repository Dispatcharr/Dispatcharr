"""Radio classification on refresh and auto-sync (issue #1683)."""
from datetime import timedelta
from unittest.mock import patch

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
from apps.m3u.tasks import process_m3u_batch_direct, sync_auto_channels


def _scan_start_time():
    return (timezone.now() - timedelta(minutes=1)).isoformat()


class RefreshSetsStreamRadioTests(TestCase):
    """process_m3u_batch_direct is the refresh path for both account types."""

    def setUp(self):
        self.group = ChannelGroup.objects.create(name="Radio")
        self.groups = {"Radio": self.group.id}

    def _account(self, account_type):
        return M3UAccount.objects.create(
            name=f"{account_type} Provider",
            server_url="http://example.com/list.m3u",
            account_type=account_type,
        )

    def _refresh(self, account, name, attributes):
        attrs = {"group-title": "Radio", **attributes}
        batch = [{
            "name": name,
            "url": f"http://example.com/{name}",
            "attributes": attrs,
            "vlc_opts": {},
        }]
        with patch("django.db.connections"):
            process_m3u_batch_direct(
                account.id, batch, self.groups, ["name", "url"], compiled_filters=[],
            )
        return Stream.objects.get(m3u_account=account, name=name)

    def test_xc_radio_streams_marks_stream_radio(self):
        account = self._account(M3UAccount.Types.XC)
        stream = self._refresh(
            account, "radio1", {"stream_id": "1", "stream_type": "radio_streams"}
        )
        self.assertTrue(stream.is_radio)

    def test_xc_live_and_created_live_stay_tv(self):
        account = self._account(M3UAccount.Types.XC)
        live = self._refresh(account, "tv1", {"stream_id": "2", "stream_type": "live"})
        created = self._refresh(
            account, "loop1", {"stream_id": "3", "stream_type": "created_live"}
        )
        self.assertFalse(live.is_radio)
        self.assertFalse(created.is_radio)

    def test_m3u_radio_attribute_is_case_insensitive(self):
        account = self._account(M3UAccount.Types.STADNARD)
        upper = self._refresh(account, "r-upper", {"RADIO": "TRUE"})
        one = self._refresh(account, "r-one", {"radio": "1"})
        other = self._refresh(account, "r-no", {"radio": "false"})
        self.assertTrue(upper.is_radio)
        self.assertTrue(one.is_radio)
        self.assertFalse(other.is_radio)

    def test_existing_stream_is_updated_both_ways(self):
        account = self._account(M3UAccount.Types.XC)
        stream = self._refresh(account, "flip", {"stream_id": "4", "stream_type": "live"})
        self.assertFalse(stream.is_radio)

        stream = self._refresh(
            account, "flip", {"stream_id": "4", "stream_type": "radio_streams"}
        )
        self.assertTrue(stream.is_radio)

        stream = self._refresh(account, "flip", {"stream_id": "4", "stream_type": "live"})
        self.assertFalse(stream.is_radio)
        self.assertEqual(
            Stream.objects.filter(m3u_account=account, name="flip").count(), 1
        )


class AutoSyncCopiesRadioTests(TestCase):
    """Auto-sync copies is_radio from the source stream, never an override."""

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Sync Provider",
            server_url="http://example.com/sync.m3u",
        )
        self.group = ChannelGroup.objects.create(name="Sync Radio")
        ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account,
            channel_group=self.group,
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=100,
            auto_sync_channel_end=199,
        )

    def _stream(self, name, is_radio):
        return Stream.objects.create(
            name=name,
            url=f"http://example.com/{name}",
            m3u_account=self.account,
            channel_group=self.group,
            tvg_id=name,
            is_radio=is_radio,
            last_seen=timezone.now(),
        )

    def _auto_channel(self, stream, is_radio=False, extra_streams=()):
        channel = Channel.objects.create(
            name=stream.name,
            channel_number=100,
            channel_group=self.group,
            tvg_id=stream.tvg_id,
            auto_created=True,
            auto_created_by=self.account,
            is_radio=is_radio,
        )
        for order, s in enumerate((stream, *extra_streams)):
            ChannelStream.objects.create(channel=channel, stream=s, order=order)
        return channel

    def test_new_auto_channel_copies_stream_radio(self):
        stream = self._stream("NewRadio", is_radio=True)

        sync_auto_channels(self.account.id, scan_start_time=_scan_start_time())

        channel = Channel.objects.get(channelstream__stream=stream)
        self.assertTrue(channel.is_radio)

    def test_existing_auto_channel_follows_stream_change(self):
        stream = self._stream("Changed", is_radio=True)
        channel = self._auto_channel(stream, is_radio=False)

        sync_auto_channels(self.account.id, scan_start_time=_scan_start_time())
        channel.refresh_from_db()
        self.assertTrue(channel.is_radio)

        Stream.objects.filter(pk=stream.pk).update(is_radio=False)
        sync_auto_channels(self.account.id, scan_start_time=_scan_start_time())
        channel.refresh_from_db()
        self.assertFalse(channel.is_radio)

    def test_sync_does_not_touch_override(self):
        stream = self._stream("Overridden", is_radio=True)
        channel = self._auto_channel(stream, is_radio=True)
        ChannelOverride.objects.create(channel=channel, is_radio=False)

        sync_auto_channels(self.account.id, scan_start_time=_scan_start_time())

        channel.refresh_from_db()
        self.assertTrue(channel.is_radio)
        self.assertIs(ChannelOverride.objects.get(channel=channel).is_radio, False)

    def test_only_source_stream_sets_radio(self):
        """A TV channel with a radio stream further down the list stays TV."""
        tv = self._stream("Mixed", is_radio=False)
        radio = self._stream("Mixed Radio", is_radio=True)
        channel = self._auto_channel(tv, is_radio=False, extra_streams=(radio,))

        sync_auto_channels(self.account.id, scan_start_time=_scan_start_time())

        channel.refresh_from_db()
        self.assertFalse(channel.is_radio)
