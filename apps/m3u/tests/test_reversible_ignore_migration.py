"""Exercise additive Ignore migrations and legacy-rule pausing in isolation."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ReversibleIgnoreMigrationTests(TransactionTestCase):
    old = [
        ("m3u", "0023_m3ufilter_enabled"),
        ("dispatcharr_channels", "0040_channel_auto_created_from"),
        ("vod", "0007_source_metadata_and_canonical_identity"),
    ]
    new = [("m3u", "0024_reversible_category_ignore")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_migrations_preserve_selections_and_pause_legacy_ignore(self):
        try:
            old = self.migrate(self.old)
            account = old.get_model("m3u", "M3UAccount").objects.create(
                name="Synthetic ignore migration"
            )
            Rule = old.get_model("m3u", "M3UGroupRule")
            rule = Rule.objects.create(
                m3u_account_id=account.pk, scope="movie", regex_pattern="EN",
                action="ignore", enabled=True,
            )
            group = old.get_model("dispatcharr_channels", "ChannelGroup").objects.create(
                name="Synthetic ignored group"
            )
            live = old.get_model(
                "dispatcharr_channels", "ChannelGroupM3UAccount"
            ).objects.create(
                channel_group_id=group.pk, m3u_account_id=account.pk, enabled=True,
            )
            category = old.get_model("vod", "VODCategory").objects.create(
                name="Synthetic ignored category", category_type="movie"
            )
            vod = old.get_model("vod", "M3UVODCategoryRelation").objects.create(
                category_id=category.pk, m3u_account_id=account.pk, enabled=True,
                metadata_defaults={"audio_languages": ["eng"]},
            )
            for _ in range(2):
                new = self.migrate(self.new)
                self.assertFalse(
                    new.get_model("m3u", "M3UGroupRule").objects.get(pk=rule.pk).enabled
                )
                live_row = new.get_model(
                    "dispatcharr_channels", "ChannelGroupM3UAccount"
                ).objects.get(pk=live.pk)
                vod_row = new.get_model(
                    "vod", "M3UVODCategoryRelation"
                ).objects.get(pk=vod.pk)
                self.assertTrue(live_row.enabled and vod_row.enabled)
                self.assertFalse(live_row.ignored or vod_row.ignored)
                self.assertEqual(vod_row.metadata_defaults, {"audio_languages": ["eng"]})
                old = self.migrate(self.old)
                self.assertFalse(
                    old.get_model("m3u", "M3UGroupRule").objects.get(pk=rule.pk).enabled
                )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
