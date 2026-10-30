"""Join upstream custom groups to already-deployed 03 category policies."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CurrentDevCategoryMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_existing_03_policies_and_ownership_survive_upstream_custom_group_backfill(self):
        after = MigrationExecutor(connection).loader.graph.leaf_nodes()
        before = [node for node in after if node[0] != "dispatcharr_channels"] + [
            ("dispatcharr_channels", "0041_category_ignored")
        ]
        try:
            # Both branches start at 0039. Targeting only the old 03 leaf
            # does not unapply an already-applied parallel upstream branch.
            self.migrate([("dispatcharr_channels", "0039_add_radio_fields")])
            apps = self.migrate(before)
            self.assertNotIn(
                ("dispatcharr_channels", "0040_channelgroup_custom_relation"),
                MigrationExecutor(connection).loader.applied_migrations,
            )
            Account = apps.get_model("m3u", "M3UAccount")
            Group = apps.get_model("dispatcharr_channels", "ChannelGroup")
            Membership = apps.get_model("dispatcharr_channels", "ChannelGroupM3UAccount")
            Channel = apps.get_model("dispatcharr_channels", "Channel")
            account = Account.objects.create(name="Synthetic provider", is_active=False)
            manual_group = Group.objects.create(name="Synthetic manual group")
            provider_group = Group.objects.create(name="Synthetic provider group")
            membership = Membership.objects.create(
                m3u_account=account,
                channel_group=provider_group,
                enabled=False,
                ignored=True,
                custom_properties={"orphan_channel_cleanup": "never"},
            )
            Channel.objects.create(name="Manual", channel_group=manual_group)
            channel = Channel.objects.create(
                name="Provider",
                channel_group=provider_group,
                auto_created=True,
                auto_created_by=account,
                auto_created_from=membership,
            )
            expected = Membership.objects.filter(pk=membership.pk).values().get()

            apps = self.migrate(after)
            Membership = apps.get_model("dispatcharr_channels", "ChannelGroupM3UAccount")
            Channel = apps.get_model("dispatcharr_channels", "Channel")
            self.assertEqual(Membership.objects.filter(pk=membership.pk).values().get(), expected)
            self.assertEqual(Channel.objects.get(pk=channel.pk).auto_created_from_id, membership.pk)
            self.assertTrue(Membership.objects.filter(
                channel_group_id=manual_group.pk,
                m3u_account__name="custom",
                m3u_account__locked=True,
            ).exists())
            self.assertFalse(Membership.objects.filter(
                channel_group_id=provider_group.pk,
                m3u_account__name="custom",
                m3u_account__locked=True,
            ).exists())
            self.assertEqual(MigrationExecutor(connection).migration_plan(after), [])
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
