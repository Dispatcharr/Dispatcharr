from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import cleanup_stale_group_relationships, process_groups


class XCGroupRenameTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Provider",
            server_url="http://example.com",
            account_type="XC",
            stale_stream_days=7,
            custom_properties={"auto_enable_new_groups_live": False},
        )
        self.group = ChannelGroup.objects.create(name="Sports (Old)")
        self.relation = ChannelGroupM3UAccount.objects.create(
            channel_group=self.group,
            m3u_account=self.account,
            custom_properties={"xc_id": "648", "channel_numbering_mode": "fixed"},
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=100,
        )

    def relation_named(self, name, account=None):
        return ChannelGroupM3UAccount.objects.get(
            m3u_account=account or self.account,
            channel_group__name=name,
        )

    def test_renamed_category_keeps_its_relationship_and_settings(self):
        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})

        relation = self.relation_named("Sports (New)")
        self.assertEqual(relation.id, self.relation.id)
        self.assertTrue(relation.enabled)
        self.assertTrue(relation.auto_channel_sync)
        self.assertEqual(relation.auto_sync_channel_start, 100)
        self.assertEqual(relation.custom_properties["channel_numbering_mode"], "fixed")
        self.assertFalse(relation.is_stale)
        self.assertEqual(
            ChannelGroupM3UAccount.objects.filter(m3u_account=self.account).count(), 1
        )

    def test_renamed_category_survives_stale_cleanup(self):
        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})
        ChannelGroupM3UAccount.objects.filter(id=self.relation.id).update(
            last_seen=timezone.now() - timezone.timedelta(days=8)
        )
        scan = timezone.now()
        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}}, scan)

        cleanup_stale_group_relationships(self.account, scan)

        self.assertTrue(self.relation_named("Sports (New)").enabled)

    def test_group_used_only_by_this_account_is_renamed_with_its_channels(self):
        channel = Channel.objects.create(
            name="Channel",
            channel_number=100,
            channel_group=self.group,
            auto_created=True,
            auto_created_by=self.account,
        )

        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})

        self.group.refresh_from_db()
        channel.refresh_from_db()
        self.assertEqual(self.group.name, "Sports (New)")
        self.assertEqual(channel.channel_group_id, self.group.id)

    def test_group_with_a_manual_channel_keeps_its_name_and_channel(self):
        channel = Channel.objects.create(
            name="Manual", channel_number=100, channel_group=self.group
        )

        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})

        channel.refresh_from_db()
        self.assertEqual(channel.channel_group.name, "Sports (Old)")
        self.assertEqual(self.relation_named("Sports (New)").id, self.relation.id)

    def test_group_shared_with_another_account_keeps_its_name(self):
        other = M3UAccount.objects.create(
            name="Other", server_url="http://other.example.com", account_type="XC"
        )
        ChannelGroupM3UAccount.objects.create(
            channel_group=self.group,
            m3u_account=other,
            custom_properties={"xc_id": "1"},
        )

        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})

        self.assertTrue(self.relation_named("Sports (Old)", other))
        relation = self.relation_named("Sports (New)")
        self.assertEqual(relation.id, self.relation.id)
        self.assertTrue(relation.enabled)

    def test_manual_group_keeps_its_name(self):
        ChannelGroup.objects.mark_custom(self.group)

        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})

        self.assertTrue(ChannelGroup.objects.filter(name="Sports (Old)").exists())
        self.assertTrue(self.relation_named("Sports (New)").enabled)

    def test_new_name_already_used_by_another_group_moves_auto_channels(self):
        target = ChannelGroup.objects.create_manual(name="Sports (New)")
        auto_channel = Channel.objects.create(
            name="Auto",
            channel_number=100,
            channel_group=self.group,
            auto_created=True,
            auto_created_by=self.account,
        )
        manual_channel = Channel.objects.create(
            name="Manual", channel_number=101, channel_group=self.group
        )
        stream = Stream.objects.create(
            name="Stream",
            url="http://example.com/1.ts",
            m3u_account=self.account,
            channel_group=self.group,
        )

        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})

        auto_channel.refresh_from_db()
        manual_channel.refresh_from_db()
        stream.refresh_from_db()
        self.assertEqual(self.relation_named("Sports (New)").channel_group_id, target.id)
        self.assertEqual(auto_channel.channel_group_id, target.id)
        self.assertEqual(stream.channel_group_id, target.id)
        self.assertEqual(manual_channel.channel_group_id, self.group.id)

    def test_emptied_group_is_removed_when_moving_to_an_existing_one(self):
        ChannelGroup.objects.create_manual(name="Sports (New)")

        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})

        self.assertFalse(ChannelGroup.objects.filter(name="Sports (Old)").exists())

    def test_old_name_still_offered_is_not_a_rename(self):
        process_groups(
            self.account,
            {"Sports (Old)": {"xc_id": "700"}, "Sports (New)": {"xc_id": "648"}},
        )

        old = self.relation_named("Sports (Old)")
        new = self.relation_named("Sports (New)")
        self.assertEqual(old.id, self.relation.id)
        self.assertEqual(old.custom_properties["xc_id"], "700")
        self.assertFalse(new.enabled)

    def test_new_name_with_its_own_relationship_is_left_alone(self):
        existing = ChannelGroupM3UAccount.objects.create(
            channel_group=ChannelGroup.objects.create(name="Sports (New)"),
            m3u_account=self.account,
            custom_properties={"xc_id": "648"},
            enabled=False,
        )

        process_groups(self.account, {"Sports (New)": {"xc_id": "648"}})

        self.assertFalse(ChannelGroupM3UAccount.objects.get(id=existing.id).enabled)
        self.assertTrue(self.relation_named("Sports (Old)").enabled)

    def test_integer_category_id_matches_string_id(self):
        process_groups(self.account, {"Sports (New)": {"xc_id": 648}})

        self.assertEqual(self.relation_named("Sports (New)").id, self.relation.id)

    def test_group_without_category_id_is_not_followed(self):
        ChannelGroupM3UAccount.objects.filter(id=self.relation.id).update(custom_properties={})

        process_groups(self.account, {"Sports (New)": {}})

        self.assertTrue(self.relation_named("Sports (Old)").enabled)
        self.assertFalse(self.relation_named("Sports (New)").enabled)
