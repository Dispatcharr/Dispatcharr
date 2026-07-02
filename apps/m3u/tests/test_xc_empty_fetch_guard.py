"""
Regression test for the Xtream Codes empty-fetch channel wipe.

Bug: when an XC provider returns no live streams on a routine refresh (a
transient upstream failure, a fetch exception, or no enabled category
matching), ``collect_xc_streams`` returns ``[]`` and the refresh used to fall
through to stale-marking and ``sync_auto_channels``. With nothing "seen" this
refresh, auto-sync deletes the account's entire auto-created channel lineup.

Fix: ``_refresh_single_m3u_account_impl`` aborts the XC branch when
``collect_xc_streams`` returns empty, setting the account to ERROR before any
stale-marking or auto-sync runs, mirroring the standard-path empty guards.
"""
from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase
from django.utils import timezone

from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelGroupM3UAccount,
    Stream,
)
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import _refresh_single_m3u_account_impl


class XCEmptyFetchGuardTests(TransactionTestCase):
    def _setup_xc_account_with_auto_channel(self):
        account = M3UAccount.objects.create(
            name="Test XC Provider",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        group = ChannelGroup.objects.create(name="Sports")
        ChannelGroupM3UAccount.objects.create(
            m3u_account=account,
            channel_group=group,
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=100,
            custom_properties={"xc_id": "123"},
        )
        # A pre-existing stream and the auto-created channel built from it on a
        # prior healthy refresh -- this is exactly what the bug deletes.
        stream = Stream.objects.create(
            name="ESPN",
            url="http://example.com/espn.m3u8",
            m3u_account=account,
            channel_group=group,
            last_seen=timezone.now(),
            is_stale=False,
        )
        channel = Channel.objects.create(
            channel_number=100,
            name="ESPN",
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        return account, group, stream, channel

    @patch("apps.m3u.tasks.sync_auto_channels")
    @patch("apps.m3u.tasks.collect_xc_streams", return_value=[])
    @patch("apps.m3u.tasks.refresh_m3u_groups")
    def test_empty_xc_fetch_aborts_before_sync_and_preserves_channels(
        self, mock_refresh_groups, _mock_collect, mock_sync
    ):
        account, group, stream, channel = self._setup_xc_account_with_auto_channel()
        # XC refresh: empty extinf_data is normal, groups must be present.
        mock_refresh_groups.return_value = ([], {"Sports": group.id})

        result = _refresh_single_m3u_account_impl(account.id)

        # The refresh aborts, so auto channel sync never runs.
        mock_sync.assert_not_called()
        # The auto-created channel survives the empty fetch.
        self.assertTrue(Channel.objects.filter(pk=channel.pk).exists())
        # The stream is not marked stale (stale-marking is skipped on abort).
        stream.refresh_from_db()
        self.assertFalse(stream.is_stale)
        # The account is surfaced as errored, not silently "successful".
        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.ERROR)
        self.assertIn("no streams returned from provider", result)

    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.tasks.cleanup_stale_group_relationships")
    @patch("apps.m3u.tasks.cleanup_streams", return_value=0)
    @patch("apps.m3u.tasks.process_m3u_batch_direct", return_value="1 created, 0 updated")
    @patch("apps.m3u.tasks.sync_auto_channels")
    @patch("apps.m3u.tasks.refresh_m3u_groups")
    def test_non_empty_xc_fetch_still_runs_sync(
        self,
        mock_refresh_groups,
        mock_sync,
        _mock_process,
        _mock_cleanup_streams,
        _mock_cleanup_groups,
        _mock_ws,
        _mock_log,
    ):
        # The guard must not fire on a healthy refresh: a non-empty fetch
        # proceeds to auto channel sync as before.
        account, group, _stream, _channel = self._setup_xc_account_with_auto_channel()
        mock_refresh_groups.return_value = ([], {"Sports": group.id})
        mock_sync.return_value = {
            "status": "ok",
            "channels_created": 1,
            "channels_updated": 0,
            "channels_deleted": 0,
            "channels_failed": 0,
            "failed_stream_details": [],
        }
        xc_stream = {
            "name": "ESPN",
            "url": "http://example.com/espn.m3u8",
            "attributes": {"group-title": "Sports", "stream_id": "1"},
        }

        with patch("apps.m3u.tasks.collect_xc_streams", return_value=[xc_stream]):
            _refresh_single_m3u_account_impl(account.id)

        mock_sync.assert_called_once()
        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.SUCCESS)
