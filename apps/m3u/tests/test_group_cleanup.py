from importlib import import_module

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelGroup, ChannelGroupM3UAccount
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import cleanup_stale_group_relationships, process_groups


class GroupCleanupTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Provider", server_url="http://example.com/list.m3u"
        )
        self.custom_account = M3UAccount.get_custom_account()

    def has_custom_relation(self, group):
        return ChannelGroupM3UAccount.objects.filter(
            channel_group=group,
            m3u_account=self.custom_account,
        ).exists()

    def test_stale_provider_relationship_keeps_manual_group(self):
        manual_group = ChannelGroup.objects.create(name="Sports")
        self.assertTrue(self.has_custom_relation(manual_group))
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
        self.assertTrue(self.has_custom_relation(manual_group))
        self.assertFalse(
            ChannelGroupM3UAccount.objects.filter(id=relationship.id).exists()
        )

    def test_provider_deletion_keeps_manual_group(self):
        manual_group = ChannelGroup.objects.create(name="Sports")
        process_groups(self.account, {"Sports": {}})

        self.account.delete()

        self.assertTrue(ChannelGroup.objects.filter(id=manual_group.id).exists())
        self.assertTrue(self.has_custom_relation(manual_group))

    def test_custom_marker_is_not_stale_cleaned(self):
        manual_group = ChannelGroup.objects.create(name="Sports")
        marker = ChannelGroupM3UAccount.objects.get(
            channel_group=manual_group,
            m3u_account=self.custom_account,
        )
        marker.last_seen = timezone.now() - timezone.timedelta(days=30)
        marker.save(update_fields=["last_seen"])

        self.assertEqual(
            cleanup_stale_group_relationships(self.custom_account, timezone.now()),
            0,
        )
        self.assertTrue(self.has_custom_relation(manual_group))

    def test_stale_provider_group_is_removed(self):
        process_groups(self.account, {"Sports": {}})
        provider_group = ChannelGroup.objects.get(name="Sports")
        self.assertFalse(self.has_custom_relation(provider_group))
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
        self.assertFalse(self.has_custom_relation(provider_group))

        manual_group = ChannelGroup.objects.create(name="ESPN +")

        self.assertEqual(manual_group.id, provider_group.id)
        self.assertTrue(self.has_custom_relation(manual_group))

    def test_custom_relation_prevents_stale_provider_group_deletion(self):
        process_groups(self.account, {"ESPN +": {}})
        provider_group = ChannelGroup.objects.get(name="ESPN +")
        relationship = ChannelGroupM3UAccount.objects.get(
            channel_group=provider_group,
            m3u_account=self.account,
        )
        relationship.delete()

        ChannelGroup.objects.create(name="ESPN +")

        ChannelGroup.objects.filter(
            id=provider_group.id,
            m3u_accounts__isnull=True,
            channels__isnull=True,
        ).delete()

        self.assertTrue(ChannelGroup.objects.filter(id=provider_group.id).exists())

    def test_migration_marks_empty_and_manual_groups_as_custom(self):
        empty_group, manual_group, provider_group = ChannelGroup.objects.bulk_create(
            [
                ChannelGroup(name="Empty"),
                ChannelGroup(name="Manual"),
                ChannelGroup(name="Provider"),
            ]
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
            "apps.channels.migrations.0040_channelgroup_custom_relation"
        )
        migration.create_custom_group_relations(django_apps, None)

        self.assertTrue(self.has_custom_relation(empty_group))
        self.assertTrue(self.has_custom_relation(manual_group))
        self.assertFalse(self.has_custom_relation(provider_group))

    def test_group_api_hides_custom_marker_and_allows_manual_edits(self):
        user = get_user_model().objects.create_superuser(
            username="group-admin",
            password="pw",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        group = ChannelGroup.objects.create(name="Sports")

        response = client.get("/api/channels/groups/")
        self.assertEqual(response.status_code, 200)
        group_data = next(item for item in response.data if item["id"] == group.id)
        self.assertEqual(group_data["m3u_account_count"], 0)
        self.assertEqual(group_data["m3u_accounts"], [])

        response = client.patch(
            f"/api/channels/groups/{group.id}/",
            {"name": "Sports Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_group_cleanup_removes_empty_manual_group(self):
        user = get_user_model().objects.create_superuser(
            username="cleanup-admin",
            password="pw",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        group = ChannelGroup.objects.create(name="Empty Sports")

        response = client.post("/api/channels/groups/cleanup/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["deleted_count"], 1)
        self.assertEqual(response.data["deleted_groups"], ["Empty Sports"])
        self.assertFalse(ChannelGroup.objects.filter(id=group.id).exists())
