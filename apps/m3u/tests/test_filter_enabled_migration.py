"""Check filter activation migration against synthetic, isolated data."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class FilterEnabledMigrationTests(TransactionTestCase):
    def migrate(self, name):
        target = [("m3u", name)]
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def test_existing_filters_remain_active_after_forward_reverse_and_reapply(self):
        try:
            old = self.migrate("0022_group_rule_metadata_defaults")
            account = old.get_model("m3u", "M3UAccount").objects.create(
                name="Synthetic filter migration", account_type="XC"
            )
            Filter = old.get_model("m3u", "M3UFilter")
            saved = Filter.objects.create(
                m3u_account_id=account.pk, regex_pattern="News", exclude=True,
                order=7, custom_properties={"case_sensitive": False},
            )
            expected = Filter.objects.filter(pk=saved.pk).values().get()
            for _ in range(2):
                new = self.migrate("0023_m3ufilter_enabled")
                Filter = new.get_model("m3u", "M3UFilter")
                migrated = Filter.objects.filter(pk=saved.pk).values().get()
                self.assertTrue(migrated.pop("enabled"))
                self.assertEqual(migrated, expected)
                Filter.objects.filter(pk=saved.pk).update(enabled=False)
                old = self.migrate("0022_group_rule_metadata_defaults")
                self.assertEqual(
                    old.get_model("m3u", "M3UFilter")
                    .objects.filter(pk=saved.pk).values().get(),
                    expected,
                )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
