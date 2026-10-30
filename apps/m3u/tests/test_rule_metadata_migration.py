"""Exercise the additive rule migration against synthetic PostgreSQL data."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RuleMetadataMigrationTests(TransactionTestCase):
    old_target = [("m3u", "0021_source_setup_squashed")]
    new_target = [("m3u", "0022_group_rule_metadata_defaults")]

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def test_forward_reverse_and_reapply_preserve_existing_rules_and_accounts(self):
        try:
            old = self.migrate(self.old_target)
            account = old.get_model("m3u", "M3UAccount").objects.create(
                name="Synthetic metadata migration",
                account_type="XC",
                custom_properties={"enable_vod": True},
            )
            Rule = old.get_model("m3u", "M3UGroupRule")
            rule = Rule.objects.create(
                m3u_account_id=account.pk,
                scope="movie",
                regex_pattern="GER",
                action="enable",
                order=7,
                case_sensitive=True,
            )
            expected = Rule.objects.filter(pk=rule.pk).values().get()
            for _ in range(2):
                new = self.migrate(self.new_target)
                migrated = (
                    new.get_model("m3u", "M3UGroupRule")
                    .objects.filter(pk=rule.pk)
                    .values()
                    .get()
                )
                self.assertEqual(migrated.pop("metadata_defaults"), {})
                self.assertEqual(migrated, expected)
                self.assertEqual(
                    new.get_model("m3u", "M3UAccount")
                    .objects.get(pk=account.pk)
                    .custom_properties,
                    {"enable_vod": True},
                )
                old = self.migrate(self.old_target)
                self.assertEqual(
                    old.get_model("m3u", "M3UGroupRule")
                    .objects.filter(pk=rule.pk)
                    .values()
                    .get(),
                    expected,
                )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
