"""A stream batch that fails to write must not lead to stale marking of its streams."""
import tempfile
import threading
from unittest import skipUnless
from unittest.mock import patch

from django.db import OperationalError, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import (
    _bulk_update_stream_refresh_batches,
    _refresh_single_m3u_account_impl,
    process_m3u_batch_direct,
)


class ProcessBatchWriteFailureTests(TransactionTestCase):
    # process_m3u_batch_direct closes all connections on entry, which a
    # TestCase transaction cannot survive.

    def _make_account_and_group(self):
        account = M3UAccount.objects.create(
            name="Test XC Provider",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        group = ChannelGroup.objects.create(name="Sports")
        return account, group

    def test_bulk_write_failure_propagates(self):
        account, group = self._make_account_and_group()
        batch = [{
            "name": "ESPN",
            "url": "http://example.com/espn.m3u8",
            "attributes": {"group-title": "Sports", "stream_id": "1"},
        }]

        with patch.object(
            Stream.objects, "bulk_create",
            side_effect=OperationalError("deadlock detected"),
        ), patch.object(connections, "close_all", wraps=connections.close_all) as close_all:
            with self.assertRaises(OperationalError):
                process_m3u_batch_direct(
                    account.id, batch, {"Sports": group.id}, [""], [],
                )

        # Once on entry, once before re-raising.
        self.assertEqual(close_all.call_count, 2)


@skipUnless(
    connection.vendor == "postgresql",
    "The refresh thread pool needs a database shared across threads, and the "
    "bad-row and deadlock cases need PostgreSQL.",
)
class RealBatchWriteFailureTests(TransactionTestCase):
    """Runs the real process_m3u_batch_direct against PostgreSQL write failures, injected or real."""

    def setUp(self):
        # Refresh reads MEDIA_ROOT/cached_m3u/<account_id>.json when present
        # and deletes it afterward. Point at an empty temp dir so a colliding
        # account id cannot load (or remove) a real cache file from the host.
        self._m3u_cache_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._m3u_cache_dir.cleanup)
        m3u_dir_patcher = patch("apps.m3u.tasks.m3u_dir", self._m3u_cache_dir.name)
        m3u_dir_patcher.start()
        self.addCleanup(m3u_dir_patcher.stop)

    def _setup(self, account_type):
        account = M3UAccount.objects.create(
            name="Test Provider",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=account_type,
            is_active=True,
        )
        group = ChannelGroup.objects.create(name="Sports")
        ChannelGroupM3UAccount.objects.create(
            m3u_account=account,
            channel_group=group,
            enabled=True,
            custom_properties={"xc_id": "123"},
        )
        return account, group

    @staticmethod
    def _provider_stream(name, stream_id):
        return {
            "name": name,
            "url": f"http://example.com/{name}.m3u8",
            "attributes": {"group-title": "Sports", "stream_id": str(stream_id)},
        }

    @staticmethod
    def _existing_stream(account, group, name, stream_id, last_seen):
        url = f"http://example.com/{name}.m3u8"
        return Stream.objects.create(
            name=name,
            url=url,
            m3u_account=account,
            channel_group=group,
            last_seen=last_seen,
            stream_id=stream_id,
            stream_hash=Stream.generate_hash_key(
                name, url, "", ["name"], m3u_id=account.id, group="Sports",
                account_type="XC", stream_id=stream_id,
            ),
        )

    @staticmethod
    def _flaky_bulk_update(exc, fail_times):
        real = _bulk_update_stream_refresh_batches
        state = {"calls": 0}

        def flaky(changed, touch, *, batch_size):
            if any(s.name == "FailStream" for s in [*changed, *touch]):
                state["calls"] += 1
                if state["calls"] <= fail_times:
                    raise exc
            return real(changed, touch, batch_size=batch_size)

        flaky.state = state
        return flaky

    def _refresh(self, account, group, provider_streams, bulk_update=None, batch_size=2):
        is_standard = account.account_type == M3UAccount.Types.STADNARD
        with patch("apps.m3u.tasks.BATCH_SIZE", batch_size), patch(
            "apps.m3u.tasks.CoreSettings.get_m3u_hash_key", return_value="name"
        ), patch(
            "apps.m3u.tasks.refresh_m3u_groups",
            return_value=(provider_streams if is_standard else [], {"Sports": group.id}),
        ), patch(
            "apps.m3u.tasks.collect_xc_streams", return_value=provider_streams
        ), patch("apps.m3u.tasks.log_system_event") as mock_log, patch(
            "apps.m3u.tasks.cleanup_stale_group_relationships"
        ) as mock_groups, patch(
            "apps.m3u.tasks.sync_auto_channels", return_value={"status": "ok"}
        ) as mock_sync, patch(
            "apps.m3u.tasks.rollup_channel_catchup_fields"
        ) as mock_rollup, patch(
            "apps.output.streaming_chunk_cache.invalidate_output_caches_after_m3u_refresh"
        ) as mock_invalidate:
            self.mock_rollup, self.mock_invalidate = mock_rollup, mock_invalidate
            if bulk_update:
                with patch(
                    "apps.m3u.tasks._bulk_update_stream_refresh_batches",
                    side_effect=bulk_update,
                ):
                    _refresh_single_m3u_account_impl(account.id)
            else:
                _refresh_single_m3u_account_impl(account.id)
        return mock_log, mock_groups, mock_sync

    def _run_failed_batch_scenario(self, account_type, exc, fail_times):
        account, group = self._setup(account_type)
        old_seen = timezone.now() - timezone.timedelta(hours=1)
        failed = self._existing_stream(account, group, "FailStream", 3, old_seen)
        absent = self._existing_stream(account, group, "AbsentStream", 9, old_seen)
        provider_streams = [
            self._provider_stream("Ok1", 1),
            self._provider_stream("Ok2", 2),
            self._provider_stream("FailStream", 3),
            self._provider_stream("NewInFail", 4),
        ]
        flaky = self._flaky_bulk_update(exc, fail_times)
        mocks = self._refresh(account, group, provider_streams, bulk_update=flaky)
        self.write_attempts = flaky.state["calls"]
        for stream in (failed, absent):
            stream.refresh_from_db()
        account.refresh_from_db()
        return account, failed, absent, old_seen, mocks

    def _assert_incomplete_refresh(self, account_type, exc):
        account, failed, absent, old_seen, (mock_log, mock_groups, mock_sync) = (
            self._run_failed_batch_scenario(account_type, exc, fail_times=99)
        )

        self.assertFalse(failed.is_stale)
        self.assertLess(failed.last_seen, old_seen + timezone.timedelta(seconds=1))
        self.assertFalse(absent.is_stale)
        # The failed batch's create rolled back together with its update.
        self.assertFalse(Stream.objects.filter(name="NewInFail").exists())
        # The other batch kept its writes.
        self.assertEqual(Stream.objects.filter(name__in=["Ok1", "Ok2"]).count(), 2)
        # One pooled attempt and exactly one retry.
        self.assertEqual(self.write_attempts, 2)
        mock_sync.assert_not_called()
        mock_groups.assert_not_called()
        self.mock_rollup.assert_called_once_with(account.id)
        self.mock_invalidate.assert_called_once_with()
        self.assertEqual(account.status, M3UAccount.Status.ERROR)
        self.assertIn("incomplete", account.last_message.lower())
        self.assertEqual(
            [c.kwargs["event_type"] for c in mock_log.call_args_list], ["m3u_error"]
        )

    def test_xc_write_failure_skips_stale_marking_and_cleanup(self):
        self._assert_incomplete_refresh(
            M3UAccount.Types.XC, OperationalError("deadlock detected")
        )

    def test_standard_write_failure_skips_stale_marking_and_cleanup(self):
        self._assert_incomplete_refresh(
            M3UAccount.Types.STADNARD, OperationalError("deadlock detected")
        )

    def test_non_database_write_failure_also_fails_the_batch(self):
        self._assert_incomplete_refresh(M3UAccount.Types.XC, ValueError("bad row"))

    def test_batch_recovered_on_retry_is_written_once(self):
        for account_type in (M3UAccount.Types.XC, M3UAccount.Types.STADNARD):
            with self.subTest(account_type=account_type):
                Stream.objects.all().delete()
                M3UAccount.objects.all().delete()
                ChannelGroup.objects.all().delete()
                account, failed, absent, old_seen, (_log, mock_groups, mock_sync) = (
                    self._run_failed_batch_scenario(
                        account_type, OperationalError("deadlock detected"), fail_times=1
                    )
                )

                self.assertEqual(self.write_attempts, 2)
                self.assertFalse(failed.is_stale)
                self.assertGreater(failed.last_seen, old_seen)
                self.assertEqual(Stream.objects.filter(name="NewInFail").count(), 1)
                self.assertTrue(absent.is_stale)
                mock_sync.assert_called_once()
                mock_groups.assert_called_once()
                self.mock_rollup.assert_called_once_with(account.id)
                self.mock_invalidate.assert_called_once_with()
                self.assertEqual(account.status, M3UAccount.Status.SUCCESS)
                self.assertIn("Total processed: 4", account.last_message)

    def test_progress_update_failure_does_not_requeue_a_committed_batch(self):
        account, group = self._setup(M3UAccount.Types.XC)
        provider_streams = [self._provider_stream(f"S{i}", i) for i in range(4)]
        real_process = process_m3u_batch_direct

        def progress_fails(*args, **kwargs):
            if "status" not in kwargs:
                raise RuntimeError("websocket down")

        with patch(
            "apps.m3u.tasks.process_m3u_batch_direct", wraps=real_process
        ) as process, patch("apps.m3u.tasks.send_m3u_update", side_effect=progress_fails):
            self._refresh(account, group, provider_streams)

        self.assertEqual(process.call_count, 2)
        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.SUCCESS)
        self.assertIn("Total processed: 4", account.last_message)

    def test_row_the_database_rejects_makes_the_refresh_incomplete(self):
        account, group = self._setup(M3UAccount.Types.XC)
        old_seen = timezone.now() - timezone.timedelta(hours=1)
        absent = self._existing_stream(account, group, "AbsentStream", 9, old_seen)
        bad = self._provider_stream("Bad", 2)
        bad["attributes"]["tvg-id"] = "x" * 300
        provider_streams = [
            self._provider_stream("Ok1", 1), bad,
            self._provider_stream("Ok2", 3), self._provider_stream("Ok3", 4),
        ]

        with self.assertLogs("apps.m3u.tasks", "ERROR") as logs:
            self._refresh(account, group, provider_streams)

        absent.refresh_from_db()
        account.refresh_from_db()
        self.assertFalse(absent.is_stale)
        self.assertFalse(Stream.objects.filter(name__in=["Ok1", "Bad"]).exists())
        self.assertEqual(Stream.objects.filter(name__in=["Ok2", "Ok3"]).count(), 2)
        self.assertEqual(account.status, M3UAccount.Status.ERROR)
        self.assertEqual(
            account.last_message, "Refresh incomplete: 1 batch(es) failed to process."
        )
        self.assertTrue(any("value too long" in line for line in logs.output))
        self.assertTrue(any("failed again on retry" in line for line in logs.output))

    def test_complete_refresh_marks_absent_stale_and_removes_past_retention(self):
        account, group = self._setup(M3UAccount.Types.XC)
        recent = timezone.now() - timezone.timedelta(hours=1)
        expired = timezone.now() - timezone.timedelta(days=account.stale_stream_days + 1)
        returned = self._existing_stream(account, group, "Ok1", 1, recent)
        absent = self._existing_stream(account, group, "AbsentStream", 9, recent)
        removed = self._existing_stream(account, group, "ExpiredStream", 10, expired)

        self._refresh(account, group, [self._provider_stream("Ok1", 1)])

        returned.refresh_from_db()
        absent.refresh_from_db()
        self.assertFalse(returned.is_stale)
        self.assertGreater(returned.last_seen, recent)
        self.assertTrue(absent.is_stale)
        self.assertFalse(Stream.objects.filter(pk=removed.pk).exists())
        self.mock_rollup.assert_called_once_with(account.id)
        self.mock_invalidate.assert_called_once_with()
        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.SUCCESS)

    def _in_sync_stream(self, account, group, provider_stream, last_seen):
        attributes = provider_stream["attributes"]
        return Stream.objects.create(
            name=provider_stream["name"],
            url=provider_stream["url"],
            m3u_account=account,
            channel_group=group,
            last_seen=last_seen,
            stream_id=int(attributes["stream_id"]),
            custom_properties=attributes,
            logo_url="",
            tvg_id="",
            is_adult=False,
            is_catchup=False,
            catchup_days=0,
            stream_hash=Stream.generate_hash_key(
                provider_stream["name"], provider_stream["url"], "", ["name"],
                m3u_id=account.id, group="Sports", account_type="XC",
                stream_id=int(attributes["stream_id"]),
            ),
        )

    def test_deadlocked_batch_is_retried_and_its_streams_stay_current(self):
        # Two concurrent batches touch one shared stream and change the other,
        # taking the row locks in opposite order; PostgreSQL aborts one.
        account, group = self._setup(M3UAccount.Types.XC)
        old_seen = timezone.now() - timezone.timedelta(hours=1)
        shared_1 = self._provider_stream("Shared1", 1)
        shared_2 = self._provider_stream("Shared2", 2)
        only_a = self._provider_stream("OnlyA", 3)
        only_b = self._provider_stream("OnlyB", 4)
        rows = [
            self._in_sync_stream(account, group, s, old_seen)
            for s in (shared_1, shared_2, only_a, only_b)
        ]
        shared_1_changed = {**shared_1, "url": "http://example.com/changed1.m3u8"}
        shared_2_changed = {**shared_2, "url": "http://example.com/changed2.m3u8"}
        # Batch A touches Shared1 and changes Shared2; batch B does the reverse.
        provider_streams = [
            shared_1, only_a, shared_2_changed,
            shared_2, only_b, shared_1_changed,
        ]

        real_bulk_update = Stream.objects.bulk_update
        lock = threading.Lock()
        barrier = threading.Barrier(2, timeout=30)
        waited = threading.local()
        state = {"waits": 0}

        def bulk_update_after_first_statement(*args, **kwargs):
            real_bulk_update(*args, **kwargs)
            with lock:
                wait = not hasattr(waited, "done") and state["waits"] < 2
                waited.done = True
                state["waits"] += wait
            if wait:
                barrier.wait()

        with patch.object(
            Stream.objects, "bulk_update", side_effect=bulk_update_after_first_statement
        ), patch("apps.m3u.tasks.process_m3u_batch_direct", wraps=process_m3u_batch_direct) as process:
            self._refresh(account, group, provider_streams, batch_size=3)

        for row in rows:
            row.refresh_from_db()
        account.refresh_from_db()
        self.assertFalse(any(row.is_stale for row in rows))
        self.assertTrue(all(row.last_seen > old_seen for row in rows))
        self.assertEqual(account.status, M3UAccount.Status.SUCCESS)
        self.assertEqual(process.call_count, 3)  # two batches plus one retry
