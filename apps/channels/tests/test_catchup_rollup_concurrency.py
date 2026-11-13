"""Concurrent catch-up rollups must not deadlock on channel rows."""

import random
import threading
import time
import uuid

from django.db import connection, connections, transaction
from django.test import TransactionTestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.channels.utils import rollup_catchup_for_channels
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import rollup_channel_catchup_fields

CHANNEL_COUNT = 60
ACCOUNT_ROLLUPS_PER_WORKER = 25
CHANNEL_ROLLUPS_PER_WORKER = 20


class CatchupRollupConcurrencyTests(TransactionTestCase):
    """Account-wide and per-channel rollups run side by side with real changes."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Row lock behavior requires PostgreSQL")

        suffix = uuid.uuid4().hex[:8]
        self.accounts = [
            M3UAccount.objects.create(
                name=f"rollup-{label}-{suffix}",
                server_url=f"http://{label}.test",
                account_type="XC",
                is_active=True,
            )
            for label in ("a", "b")
        ]
        self.channel_ids = []
        self.toggle_stream_ids = []
        for i in range(CHANNEL_COUNT):
            channel = Channel.objects.create(
                name=f"rollup-ch-{suffix}-{i}", channel_number=7000 + i
            )
            toggled = Stream.objects.create(
                name=f"rollup-a-{suffix}-{i}",
                url=f"http://a.test/{suffix}/{i}",
                m3u_account=self.accounts[0],
                is_catchup=True,
                catchup_days=7,
            )
            plain = Stream.objects.create(
                name=f"rollup-b-{suffix}-{i}",
                url=f"http://b.test/{suffix}/{i}",
                m3u_account=self.accounts[1],
                is_catchup=False,
            )
            ChannelStream.objects.create(channel=channel, stream=toggled, order=0)
            ChannelStream.objects.create(channel=channel, stream=plain, order=1)
            self.channel_ids.append(channel.id)
            self.toggle_stream_ids.append(toggled.id)

    def tearDown(self):
        # Worker threads open their own connections; drop them so the table
        # flush that follows is not blocked by leftover sessions.
        connections.close_all()
        super().tearDown()

    def test_account_and_channel_rollups_do_not_deadlock(self):
        errors = []

        def account_worker(account_id):
            try:
                for _ in range(ACCOUNT_ROLLUPS_PER_WORKER):
                    rollup_channel_catchup_fields(account_id)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        def channel_worker(parity):
            # Disjoint stream halves so workers contend only on channel rows.
            owned = self.toggle_stream_ids[parity::2]
            rng = random.Random(parity)
            try:
                for step in range(CHANNEL_ROLLUPS_PER_WORKER):
                    Stream.objects.filter(pk__in=owned).update(
                        is_catchup=bool(step % 2)
                    )
                    sample = rng.sample(self.channel_ids, 20)
                    rollup_catchup_for_channels(sample)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=account_worker, args=(self.accounts[0].id,)),
            threading.Thread(target=account_worker, args=(self.accounts[1].id,)),
            threading.Thread(target=channel_worker, args=(0,)),
            threading.Thread(target=channel_worker, args=(1,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
            self.assertFalse(thread.is_alive(), "rollup worker timed out")

        self.assertEqual(errors, [], f"concurrent rollups failed: {errors!r}")

        rollup_channel_catchup_fields(self.accounts[0].id)
        for channel in Channel.objects.filter(id__in=self.channel_ids):
            has_catchup = Stream.objects.filter(
                channels=channel, is_catchup=True, m3u_account__is_active=True
            ).exists()
            self.assertEqual(channel.is_catchup, has_catchup)
            self.assertEqual(channel.catchup_days, 7 if has_catchup else 0)

    def test_rollup_row_lock_does_not_block_stream_link_inserts(self):
        """FOR NO KEY UPDATE must not stall ChannelStream FK inserts."""
        channel_id = self.channel_ids[0]
        extra = Stream.objects.create(
            name="rollup-extra",
            url="http://b.test/extra",
            m3u_account=self.accounts[1],
            is_catchup=False,
        )
        # Force a write so the rollup holds a row lock.
        Channel.objects.filter(pk=channel_id).update(is_catchup=False, catchup_days=0)

        locked = threading.Event()
        release = threading.Event()
        outcome = {}

        def holder():
            try:
                with transaction.atomic():
                    rollup_catchup_for_channels([channel_id])
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
                # bulk_create skips the signal, so no second rollup runs here.
                ChannelStream.objects.bulk_create(
                    [ChannelStream(channel_id=channel_id, stream=extra, order=5)]
                )
                outcome["waited"] = time.monotonic() - started
            except Exception as exc:
                outcome["inserter"] = exc
            finally:
                release.set()
                connections.close_all()

        threads = [threading.Thread(target=holder), threading.Thread(target=inserter)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            self.assertFalse(thread.is_alive(), "worker timed out")

        self.assertNotIn("holder", outcome, outcome.get("holder"))
        self.assertNotIn("inserter", outcome, outcome.get("inserter"))
        self.assertLess(outcome["waited"], 1.0)
