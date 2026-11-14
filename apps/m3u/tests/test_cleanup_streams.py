"""Stale/group-filter stream cleanup must not fail on deferred ChannelStream FKs."""

import threading
import time
import uuid

from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelGroupM3UAccount,
    ChannelStream,
    Stream,
)
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import _delete_streams_by_ids, cleanup_streams


class CleanupStreamsTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.account = M3UAccount.objects.create(
            name=f"cleanup-{suffix}",
            server_url="http://example.test",
            account_type="XC",
            is_active=True,
            stale_stream_days=7,
        )
        self.group = ChannelGroup.objects.create(name=f"cleanup-g-{suffix}")
        ChannelGroupM3UAccount.objects.create(
            channel_group=self.group,
            m3u_account=self.account,
            enabled=True,
        )

    def test_cleanup_removes_stale_stream_linked_to_channel_and_resets_catchup(self):
        channel = Channel.objects.create(name="cleanup-ch")
        stream = Stream.objects.create(
            name="cleanup-stale",
            url="http://example.test/stale",
            m3u_account=self.account,
            channel_group=self.group,
            last_seen=timezone.now() - timezone.timedelta(days=30),
            is_catchup=True,
            catchup_days=5,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        channel.refresh_from_db()
        self.assertTrue(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 5)

        deleted = cleanup_streams(self.account.id, timezone.now())

        self.assertEqual(deleted, 1)
        self.assertFalse(Stream.objects.filter(id=stream.id).exists())
        self.assertFalse(ChannelStream.objects.filter(channel=channel).exists())
        channel.refresh_from_db()
        self.assertFalse(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 0)

    def test_cleanup_removes_streams_outside_enabled_groups(self):
        disabled = ChannelGroup.objects.create(name="cleanup-disabled")
        ChannelGroupM3UAccount.objects.create(
            channel_group=disabled,
            m3u_account=self.account,
            enabled=False,
        )
        stream = Stream.objects.create(
            name="cleanup-disabled-group",
            url="http://example.test/disabled",
            m3u_account=self.account,
            channel_group=disabled,
            last_seen=timezone.now(),
        )

        deleted = cleanup_streams(self.account.id, timezone.now())

        self.assertEqual(deleted, 1)
        self.assertFalse(Stream.objects.filter(id=stream.id).exists())

    def test_cleanup_counts_overlapping_filters_once(self):
        disabled = ChannelGroup.objects.create(name="cleanup-overlap-g")
        ChannelGroupM3UAccount.objects.create(
            channel_group=disabled,
            m3u_account=self.account,
            enabled=False,
        )
        stream = Stream.objects.create(
            name="cleanup-overlap",
            url="http://example.test/overlap",
            m3u_account=self.account,
            channel_group=disabled,
            last_seen=timezone.now() - timezone.timedelta(days=30),
        )

        deleted = cleanup_streams(self.account.id, timezone.now())

        self.assertEqual(deleted, 1)
        self.assertFalse(Stream.objects.filter(id=stream.id).exists())

    def test_cleanup_keeps_fresh_streams_in_enabled_groups(self):
        stream = Stream.objects.create(
            name="cleanup-fresh",
            url="http://example.test/fresh",
            m3u_account=self.account,
            channel_group=self.group,
            last_seen=timezone.now(),
        )

        deleted = cleanup_streams(self.account.id, timezone.now())

        self.assertEqual(deleted, 0)
        self.assertTrue(Stream.objects.filter(id=stream.id).exists())

    def test_cleanup_keeps_catchup_from_a_stream_that_stays(self):
        channel = Channel.objects.create(name="cleanup-keep-catchup")
        stale = Stream.objects.create(
            name="cleanup-keep-stale",
            url="http://example.test/keep-stale",
            m3u_account=self.account,
            channel_group=self.group,
            last_seen=timezone.now() - timezone.timedelta(days=30),
            is_catchup=True,
            catchup_days=3,
        )
        fresh = Stream.objects.create(
            name="cleanup-keep-fresh",
            url="http://example.test/keep-fresh",
            m3u_account=self.account,
            channel_group=self.group,
            last_seen=timezone.now(),
            is_catchup=True,
            catchup_days=9,
        )
        ChannelStream.objects.create(channel=channel, stream=stale, order=0)
        ChannelStream.objects.create(channel=channel, stream=fresh, order=1)

        deleted = cleanup_streams(self.account.id, timezone.now())

        self.assertEqual(deleted, 1)
        self.assertFalse(Stream.objects.filter(id=stale.id).exists())
        self.assertTrue(Stream.objects.filter(id=fresh.id).exists())
        channel.refresh_from_db()
        self.assertTrue(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 9)


class CleanupStreamsConcurrencyTests(TransactionTestCase):
    """Deferred ChannelStream FKs must not abort cleanup under concurrent inserts."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("select_for_update race coverage requires PostgreSQL")

        suffix = uuid.uuid4().hex[:8]
        self.account = M3UAccount.objects.create(
            name=f"cleanup-race-{suffix}",
            server_url="http://example.test",
            account_type="XC",
            is_active=True,
            stale_stream_days=7,
        )
        self.group = ChannelGroup.objects.create(name=f"cleanup-race-g-{suffix}")
        ChannelGroupM3UAccount.objects.create(
            channel_group=self.group,
            m3u_account=self.account,
            enabled=True,
        )
        self.channel = Channel.objects.create(name=f"cleanup-race-ch-{suffix}")
        self.stream = Stream.objects.create(
            name=f"cleanup-race-s-{suffix}",
            url=f"http://example.test/race-{suffix}",
            m3u_account=self.account,
            channel_group=self.group,
            last_seen=timezone.now() - timezone.timedelta(days=30),
            is_catchup=True,
            catchup_days=5,
        )
        ChannelStream.objects.create(
            channel=self.channel, stream=self.stream, order=0
        )
        self.channel.refresh_from_db()
        self.assertTrue(self.channel.is_catchup)

    def tearDown(self):
        connections.close_all()
        super().tearDown()

    def test_select_for_update_blocks_concurrent_channelstream_insert(self):
        stream_id = self.stream.id
        locked = threading.Event()
        release = threading.Event()
        outcome = {}

        def holder():
            try:
                with transaction.atomic():
                    list(
                        Stream.objects.select_for_update()
                        .filter(id=stream_id)
                        .order_by("id")
                    )
                    locked.set()
                    release.wait(timeout=30)
            except Exception as exc:
                outcome["holder"] = exc
            finally:
                locked.set()
                connections.close_all()

        def inserter():
            try:
                locked.wait(timeout=30)
                with connection.cursor() as cur:
                    cur.execute("SET lock_timeout = '2s'")
                started = time.monotonic()
                try:
                    other = Channel.objects.create(name="cleanup-race-insert")
                    ChannelStream.objects.create(
                        channel=other, stream_id=stream_id, order=1
                    )
                    outcome["inserter"] = "inserted"
                except Exception as exc:
                    outcome["waited"] = time.monotonic() - started
                    outcome["inserter"] = exc
                finally:
                    release.set()
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=holder),
            threading.Thread(target=inserter),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            self.assertFalse(thread.is_alive(), "worker timed out")

        self.assertNotIn("holder", outcome, outcome.get("holder"))
        self.assertIsInstance(outcome.get("inserter"), Exception)
        self.assertGreaterEqual(outcome.get("waited", 0), 0.5)

    def test_delete_streams_by_ids_removes_all_links_then_stream(self):
        other = Channel.objects.create(name="cleanup-race-second-ch")
        ChannelStream.objects.create(channel=other, stream=self.stream, order=1)
        stream_id = self.stream.id

        deleted = _delete_streams_by_ids([stream_id])

        self.assertEqual(deleted, 1)
        self.assertFalse(Stream.objects.filter(id=stream_id).exists())
        self.assertEqual(
            ChannelStream.objects.filter(stream_id=stream_id).count(), 0
        )
        self.channel.refresh_from_db()
        other.refresh_from_db()
        self.assertFalse(self.channel.is_catchup)
        self.assertFalse(other.is_catchup)
