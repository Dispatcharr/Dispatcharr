"""The coalesced ``channels_updated`` event: every write path reports its
channels, and one event carries what changed."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.channels import change_events
from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelOverride,
    ChannelStream,
    Stream,
)
from apps.connect.models import SUPPORTED_EVENTS, EventSubscription
from core.models import SystemEvent

User = get_user_model()


class FakeRedis:
    """The few Redis commands change_events uses, in memory."""

    def __init__(self):
        self.data = {}

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def sadd(self, key, *values):
        self.ops.append(("sadd", key, values))

    def set(self, key, value, nx=False, ex=None):
        self.ops.append(("set", key, value, nx))

    def smembers(self, key):
        self.ops.append(("smembers", key))

    def delete(self, key):
        self.ops.append(("delete", key))

    def execute(self):
        data, out = self.redis.data, []
        for op in self.ops:
            if op[0] == "sadd":
                data.setdefault(op[1], set()).update(str(v) for v in op[2])
                out.append(len(op[2]))
            elif op[0] == "set":
                if op[3] and op[1] in data:
                    out.append(None)
                else:
                    data[op[1]] = op[2]
                    out.append(True)
            elif op[0] == "smembers":
                out.append(set(data.get(op[1], set())))
            elif op[0] == "delete":
                out.append(1 if data.pop(op[1], None) is not None else 0)
        return out


class RecordedChangesMixin:
    """Captures what each write reports, as the on_commit callbacks run."""

    def setUp(self):
        super().setUp()
        self.recorded = []
        patcher = patch.object(
            change_events,
            "_record",
            side_effect=lambda c, u, d: self.recorded.append((set(c), set(u), set(d))),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def changes(self, fn):
        """Run fn, commit, and return the union of what it reported."""
        self.recorded.clear()
        with self.captureOnCommitCallbacks(execute=True):
            fn()
        created, updated, deleted = set(), set(), set()
        for c, u, d in self.recorded:
            created |= c
            updated |= u
            deleted |= d
        return created, updated, deleted


class ChannelWritesAreReportedTests(RecordedChangesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.group = ChannelGroup.objects.create(name="Change Events")
        self.channel = Channel.objects.create(
            channel_number=1, name="One", channel_group=self.group
        )
        self.stream = Stream.objects.create(name="Feed", url="http://example.com/1")

    def test_create_save_and_delete(self):
        holder = {}

        def create():
            holder["ch"] = Channel.objects.create(channel_number=2, name="Two")

        created, _, _ = self.changes(create)
        self.assertEqual(created, {holder["ch"].pk})

        def rename():
            self.channel.name = "Renamed"
            self.channel.save()

        self.assertEqual(self.changes(rename)[1], {self.channel.pk})

        uuid = str(holder["ch"].uuid)
        self.assertEqual(self.changes(holder["ch"].delete)[2], {uuid})

    def test_queryset_delete_reports_each_channel(self):
        other = Channel.objects.create(channel_number=3, name="Three")
        expected = {str(self.channel.uuid), str(other.uuid)}
        deleted = self.changes(
            lambda: Channel.objects.filter(pk__in=[self.channel.pk, other.pk]).delete()
        )[2]
        self.assertEqual(deleted, expected)

    def test_bulk_writes_skip_post_save_and_are_still_reported(self):
        holder = {}

        def bulk_create():
            holder["chs"] = Channel.objects.bulk_create(
                [Channel(channel_number=10, name="A"), Channel(channel_number=11, name="B")]
            )

        created = self.changes(bulk_create)[0]
        self.assertEqual(created, {c.pk for c in holder["chs"]})

        def bulk_update():
            for c in holder["chs"]:
                c.name += "!"
            Channel.objects.bulk_update(holder["chs"], ["name"])

        self.assertEqual(self.changes(bulk_update)[1], {c.pk for c in holder["chs"]})

        updated = self.changes(
            lambda: Channel.objects.filter(pk=self.channel.pk).update(name="Direct")
        )[1]
        self.assertEqual(updated, {self.channel.pk})

    def test_stream_list_changes_update_the_channel(self):
        self.assertEqual(
            self.changes(lambda: self.channel.streams.add(self.stream))[1],
            {self.channel.pk},
        )

        def reorder():
            rows = list(ChannelStream.objects.filter(channel=self.channel))
            for r in rows:
                r.order = 5
            ChannelStream.objects.bulk_update(rows, ["order"])

        self.assertEqual(self.changes(reorder)[1], {self.channel.pk})
        self.assertEqual(
            self.changes(lambda: self.channel.streams.remove(self.stream))[1],
            {self.channel.pk},
        )

    def test_an_override_updates_its_channel(self):
        self.assertEqual(
            self.changes(
                lambda: ChannelOverride.objects.create(channel=self.channel, name="Mine")
            )[1],
            {self.channel.pk},
        )

    def test_a_rolled_back_change_is_not_reported(self):
        def failed_edit():
            try:
                with transaction.atomic():
                    Channel.objects.create(channel_number=9, name="Never")
                    raise RuntimeError("rolled back")
            except RuntimeError:
                pass

        self.assertEqual(self.changes(failed_edit), (set(), set(), set()))


class ChannelAPIWritesAreReportedTests(RecordedChangesMixin, TestCase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user(username="editor", password="testpass123")
        user.user_level = 10
        user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.a = Channel.objects.create(channel_number=1, name="A")
        self.b = Channel.objects.create(channel_number=2, name="B")

    def test_patch(self):
        updated = self.changes(
            lambda: self.client.patch(
                f"/api/channels/channels/{self.a.id}/", {"name": "A2"}, format="json"
            )
        )[1]
        self.assertEqual(updated, {self.a.pk})

    def test_bulk_edit(self):
        def edit():
            response = self.client.patch(
                "/api/channels/channels/edit/bulk/",
                [{"id": self.a.id, "name": "A3"}, {"id": self.b.id, "name": "B3"}],
                format="json",
            )
            self.assertLess(response.status_code, 300, response.content)

        self.assertEqual(self.changes(edit)[1], {self.a.pk, self.b.pk})


class SendPendingChangesTests(TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        patcher = patch("core.utils.RedisClient.get_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.a = Channel.objects.create(channel_number=1, name="A")
        self.b = Channel.objects.create(channel_number=2, name="B")

    @patch("apps.channels.tasks.send_channels_updated_event.apply_async")
    def test_changes_within_the_window_schedule_one_event(self, apply_async):
        change_events._record([self.a.pk], [], [])
        change_events._record([], [self.b.pk], [])
        apply_async.assert_called_once_with(countdown=change_events.DEBOUNCE_SECONDS)

    @patch("core.utils.log_system_event")
    @patch("apps.channels.tasks.send_channels_updated_event.apply_async")
    def test_one_event_carries_the_changes(self, apply_async, log_event):
        gone = Channel.objects.create(channel_number=3, name="Gone")
        gone_uuid = str(gone.uuid)
        gone_pk = gone.pk
        gone.delete()
        change_events._record([self.a.pk, gone_pk], [self.a.pk, self.b.pk, 999999], [])
        change_events._record([], [], [gone_uuid])

        counts = change_events.send_pending_changes()

        self.assertEqual(counts, {"created": 1, "updated": 1, "deleted": 1})
        log_event.assert_called_once()
        args, kwargs = log_event.call_args
        self.assertEqual(args, ("channels_updated",))
        # Created and then edited: reported as created only. Created and then
        # deleted: deleted only. A channel that no longer exists is dropped.
        self.assertEqual(kwargs["created_channel_ids"], [str(self.a.uuid)])
        self.assertEqual(kwargs["updated_channel_ids"], [str(self.b.uuid)])
        self.assertEqual(kwargs["deleted_channel_ids"], [gone_uuid])
        self.assertFalse(kwargs["truncated"])

        # Sent and cleared: the next change schedules the next event.
        self.assertIsNone(change_events.send_pending_changes())
        change_events._record([], [self.a.pk], [])
        self.assertEqual(apply_async.call_count, 2)

    @patch("core.utils.log_system_event")
    @patch("apps.channels.tasks.send_channels_updated_event.apply_async")
    def test_long_lists_are_truncated_counts_are_not(self, apply_async, log_event):
        change_events._record([], [self.a.pk, self.b.pk], [])
        with patch.object(change_events, "MAX_IDS", 1):
            change_events.send_pending_changes()
        kwargs = log_event.call_args.kwargs
        self.assertEqual(kwargs["updated"], 2)
        self.assertEqual(len(kwargs["updated_channel_ids"]), 1)
        self.assertTrue(kwargs["truncated"])

    @patch("core.utils.log_system_event")
    def test_nothing_pending_sends_nothing(self, log_event):
        self.assertIsNone(change_events.send_pending_changes())
        log_event.assert_not_called()

    def test_redis_failure_never_fails_the_write(self):
        with patch("core.utils.RedisClient.get_client", side_effect=ConnectionError):
            change_events._record([self.a.pk], [], [])


class ChannelsUpdatedIsSubscribableTests(SimpleTestCase):
    def test_registered(self):
        self.assertIn("channels_updated", SUPPORTED_EVENTS)
        self.assertIn(
            "channels_updated",
            dict(EventSubscription._meta.get_field("event").choices),
        )
        self.assertIn("channels_updated", dict(SystemEvent.EVENT_TYPES))
