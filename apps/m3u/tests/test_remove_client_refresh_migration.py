from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.test import TransactionTestCase
from importlib import import_module


class RemoveClientRefreshMigrationTests(TransactionTestCase):
    old_target = [("m3u", "0024_m3uaccount_setup_navigation")]
    new_target = [("m3u", "0025_remove_client_live_refresh_cooldown")]

    def test_fresh_install_uses_only_rules_and_setup_operations(self):
        migration = import_module(
            "apps.m3u.migrations.0021_source_setup_squashed"
        ).Migration
        self.assertEqual(len(migration.replaces), 5)
        self.assertEqual(
            [operation.name.lower() for operation in migration.operations],
            ["m3ugrouprule", "setup_step"],
        )

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        # Exercise the historical, partially applied path even when a fresh
        # installation has already used the squashed migration.
        executor.loader = MigrationLoader(connection, replace_migrations=False)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def test_removal_and_reverse_preserve_other_account_settings(self):
        try:
            old_apps = self.migrate(self.old_target)
            account_model = old_apps.get_model("m3u", "M3UAccount")
            account = account_model.objects.create(
                name="migration-fixture",
                account_type="XC",
                server_url="https://provider.example",
                setup_step="categories",
                vod_refresh_after_live=False,
                xc_live_refresh_min_age_minutes=55,
                custom_properties={
                    "enable_vod": True,
                    "setup_categories_reviewed": True,
                    "live_catalog_counts": {"selected_total": 12},
                },
            )
            expected = account_model.objects.filter(pk=account.pk).values().get()
            expected.pop("xc_live_refresh_min_age_minutes")

            new_apps = self.migrate(self.new_target)
            new_model = new_apps.get_model("m3u", "M3UAccount")
            self.assertEqual(
                new_model.objects.filter(pk=account.pk).values().get(), expected
            )
            with connection.cursor() as cursor:
                columns = connection.introspection.get_table_description(
                    cursor, new_model._meta.db_table
                )
            self.assertNotIn(
                "xc_live_refresh_min_age_minutes", {column.name for column in columns}
            )

            old_apps = self.migrate(self.old_target)
            restored = (
                old_apps.get_model("m3u", "M3UAccount")
                .objects.filter(pk=account.pk)
                .values()
                .get()
            )
            self.assertEqual(restored.pop("xc_live_refresh_min_age_minutes"), 30)
            self.assertEqual(restored, expected)
        finally:
            self.migrate(self.new_target)
