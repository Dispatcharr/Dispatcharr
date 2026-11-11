"""Catch-up rollup semantics, write avoidance, and deadlock retry rules."""

from unittest.mock import MagicMock, patch

import psycopg
from django.db import connection
from django.db.utils import OperationalError
from django.test import SimpleTestCase, TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.channels.utils import (
    retry_on_deadlock,
    rollup_catchup_for_account,
    rollup_catchup_for_channels,
)
from apps.m3u.models import M3UAccount


def _deadlock_error():
    exc = OperationalError("deadlock detected")
    exc.__cause__ = psycopg.errors.DeadlockDetected("deadlock detected")
    return exc


class RetryOnDeadlockTests(SimpleTestCase):
    @patch("apps.channels.utils.time.sleep")
    def test_retries_a_deadlock_then_succeeds(self, sleep):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise _deadlock_error()
            return "ok"

        self.assertEqual(retry_on_deadlock(flaky, base_delay=0.5), "ok")
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(0.5)

    @patch("apps.channels.utils.time.sleep")
    def test_backs_off_and_gives_up_after_the_attempt_limit(self, sleep):
        calls = []

        def always():
            calls.append(1)
            raise _deadlock_error()

        with self.assertRaises(OperationalError):
            retry_on_deadlock(always, attempts=3, base_delay=1)
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    @patch("apps.channels.utils.time.sleep")
    def test_other_operational_errors_are_not_retried(self, sleep):
        def boom():
            raise OperationalError("connection reset by peer")

        with self.assertRaises(OperationalError):
            retry_on_deadlock(boom)
        sleep.assert_not_called()

    @patch("apps.channels.utils.time.sleep")
    def test_message_text_alone_is_not_treated_as_a_deadlock(self, sleep):
        def boom():
            raise OperationalError("deadlock detected")

        with self.assertRaises(OperationalError):
            retry_on_deadlock(boom)
        sleep.assert_not_called()


class RollupRetryDispatchTests(TestCase):
    def test_no_retry_inside_an_open_transaction(self):
        # TestCase wraps each test in atomic(), like channel-save API views.
        with patch("apps.channels.utils.retry_on_deadlock") as retry:
            rollup_catchup_for_channels([1])
        retry.assert_not_called()

    def test_retry_is_used_when_the_rollup_owns_its_transaction(self):
        autocommit = MagicMock(in_atomic_block=False)
        with patch("apps.channels.utils.connection", autocommit), patch(
            "apps.channels.utils.retry_on_deadlock"
        ) as retry:
            rollup_catchup_for_channels([1])
        retry.assert_called_once()


class CatchupRollupBehaviorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.account = M3UAccount.objects.create(
            name="rollup-behavior",
            server_url="http://example.test",
            account_type="XC",
            is_active=True,
        )

    def _channel(self, name, *, days=5, catchup=True):
        channel = Channel.objects.create(name=name)
        stream = Stream.objects.create(
            name=f"{name}-stream",
            url=f"http://example.test/{name}",
            m3u_account=self.account,
            is_catchup=catchup,
            catchup_days=days,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        return channel, stream

    @staticmethod
    def _ctid(channel):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT ctid::text FROM dispatcharr_channels_channel WHERE id = %s",
                [channel.id],
            )
            return cur.fetchone()[0]

    def test_id_list_rollup_takes_the_largest_days_per_channel(self):
        first, _ = self._channel("days-a", days=4)
        second, _ = self._channel("days-b", days=11)
        extra = Stream.objects.create(
            name="days-a-extra",
            url="http://example.test/days-a-extra",
            m3u_account=self.account,
            is_catchup=True,
            catchup_days=9,
        )
        ChannelStream.objects.create(channel=first, stream=extra, order=1)
        Channel.objects.filter(pk__in=[first.pk, second.pk]).update(
            is_catchup=False, catchup_days=0
        )

        rollup_catchup_for_channels([first.id, second.id])

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.is_catchup, first.catchup_days), (True, 9))
        self.assertEqual((second.is_catchup, second.catchup_days), (True, 11))

    def test_channel_with_no_streams_is_reset(self):
        channel = Channel.objects.create(name="no-streams")
        Channel.objects.filter(pk=channel.pk).update(is_catchup=True, catchup_days=9)

        rollup_catchup_for_channels([channel.id])

        channel.refresh_from_db()
        self.assertEqual((channel.is_catchup, channel.catchup_days), (False, 0))

    def test_zero_day_catchup_stream_still_marks_the_channel(self):
        channel, _ = self._channel("zero-days", days=0)
        Channel.objects.filter(pk=channel.pk).update(is_catchup=False)

        rollup_catchup_for_channels([channel.id])

        channel.refresh_from_db()
        self.assertEqual((channel.is_catchup, channel.catchup_days), (True, 0))

    def test_unchanged_channels_are_not_rewritten(self):
        channel, stream = self._channel("steady", days=6)
        before = self._ctid(channel)

        rollup_catchup_for_channels([channel.id])
        rollup_catchup_for_account(self.account.id)
        self.assertEqual(self._ctid(channel), before)

        Stream.objects.filter(pk=stream.pk).update(is_catchup=False)
        rollup_catchup_for_channels([channel.id])

        channel.refresh_from_db()
        self.assertEqual((channel.is_catchup, channel.catchup_days), (False, 0))
        self.assertNotEqual(self._ctid(channel), before)

    def test_account_rollup_corrects_stale_flags_and_skips_unlinked_channels(self):
        linked, stream = self._channel("linked", days=3)
        unlinked = Channel.objects.create(name="unlinked")
        Stream.objects.filter(pk=stream.pk).update(is_catchup=False)
        Channel.objects.filter(pk=linked.pk).update(is_catchup=True, catchup_days=3)
        Channel.objects.filter(pk=unlinked.pk).update(is_catchup=True, catchup_days=8)

        rollup_catchup_for_account(self.account.id)

        linked.refresh_from_db()
        unlinked.refresh_from_db()
        self.assertEqual((linked.is_catchup, linked.catchup_days), (False, 0))
        self.assertEqual((unlinked.is_catchup, unlinked.catchup_days), (True, 8))
