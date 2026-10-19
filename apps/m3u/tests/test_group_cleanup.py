from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase
from django.utils import timezone

from apps.channels.models import (
    ChannelGroup,
    ChannelGroupM3UAccount,
    Channel,
)
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import cleanup_stale_group_relationships, process_groups


class GroupCleanupTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Provider", server_url="http://example.com/list.m3u"
        )

    def test_stale_provider_relationship_keeps_manual_group(self):
        manual_group = ChannelGroup.objects.create(name="Sports")
        self.assertTrue(manual_group.is_manual)
        process_groups(self.account, {"Sports": {}})
        relationship = ChannelGroupM3UAccount.objects.get(
            channel_group=manual_group,
            m3u_account=self.account,
        )
        relationship.last_seen = timezone.now() - timezone.timedelta(days=2)
        relationship.save(update_fields=["last_seen"])
        self.account.stale_stream_days = 1
        self.account.save(update_fields=["stale_stream_days"])

        cleanup_stale_group_relationships(self.account, timezone.now())

        self.assertTrue(ChannelGroup.objects.filter(id=manual_group.id).exists())
        self.assertFalse(
            ChannelGroupM3UAccount.objects.filter(id=relationship.id).exists()
        )

    def test_provider_deletion_keeps_manual_group(self):
        manual_group = ChannelGroup.objects.create(name="Sports")
        process_groups(self.account, {"Sports": {}})

        self.account.delete()

        self.assertTrue(ChannelGroup.objects.filter(id=manual_group.id).exists())

    def test_stale_provider_group_is_removed(self):
        process_groups(self.account, {"Sports": {}})
        provider_group = ChannelGroup.objects.get(name="Sports")
        self.assertFalse(provider_group.is_manual)
        relationship = ChannelGroupM3UAccount.objects.get(
            channel_group=provider_group,
            m3u_account=self.account,
        )
        relationship.last_seen = timezone.now() - timezone.timedelta(days=2)
        relationship.save(update_fields=["last_seen"])
        self.account.stale_stream_days = 1
        self.account.save(update_fields=["stale_stream_days"])

        cleanup_stale_group_relationships(self.account, timezone.now())

        self.assertFalse(ChannelGroup.objects.filter(id=provider_group.id).exists())

    def test_manual_creation_reuses_provider_group(self):
        process_groups(self.account, {"ESPN +": {}})
        provider_group = ChannelGroup.objects.get(name="ESPN +")
        self.assertFalse(provider_group.is_manual)

        manual_group = ChannelGroup.objects.create(name="ESPN +")

        self.assertEqual(manual_group.id, provider_group.id)
        self.assertTrue(manual_group.is_manual)

    def test_manual_conversion_prevents_provider_cleanup_deletion(self):
        process_groups(self.account, {"ESPN +": {}})
        provider_group = ChannelGroup.objects.get(name="ESPN +")
        stale_group = ChannelGroupM3UAccount.objects.select_related(
            "channel_group"
        ).get(channel_group=provider_group).channel_group
        self.assertFalse(stale_group.is_manual)

        ChannelGroup.objects.create(name="ESPN +")
        provider_group.refresh_from_db()
        self.assertTrue(provider_group.is_manual)

        ChannelGroup.objects.filter(
            id=stale_group.id,
            source_type=ChannelGroupSource.PROVIDER,
        ).delete()

        self.assertTrue(ChannelGroup.objects.filter(id=provider_group.id).exists())

    def test_migration_classifies_manual_and_provider_groups(self):
        empty_group = ChannelGroup.objects.create(
            name="Empty", is_manual=False
        )
        manual_group = ChannelGroup.objects.create(
            name="Manual", is_manual=False
        )
        provider_group = ChannelGroup.objects.create(
            name="Provider", is_manual=False
        )
        Channel.objects.create(
            name="Manual Channel",
            channel_group=manual_group,
            auto_created=False,
        )
        Channel.objects.create(
            name="Provider Channel",
            channel_group=provider_group,
            auto_created=True,
        )

        migration = import_module(
            "apps.channels.migrations.0040_channelgroup_is_manual"
        )
        migration.classify_group_sources(django_apps, None)

        empty_group.refresh_from_db()
        manual_group.refresh_from_db()
        provider_group.refresh_from_db()
        self.assertTrue(empty_group.is_manual)
        self.assertTrue(manual_group.is_manual)
        self.assertFalse(provider_group.is_manual)
