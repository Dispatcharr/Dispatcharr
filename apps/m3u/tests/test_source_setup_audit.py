"""Keep the standalone historical migration audit executable on current leaves."""

import io
import runpy
from contextlib import redirect_stdout
from pathlib import Path
from unittest import skipUnless

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL migrations")
class SourceSetupAuditTests(TransactionTestCase):
    def test_fresh_and_historical_audit_preserves_later_migrations(self):
        targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                runpy.run_path(
                    str(Path(__file__).with_name("audit_source_setup_migration.py"))
                )
            for marker in (
                "FRESH_SOURCE_SETUP_WITHOUT_RETIRED_FIELD_OK",
                "PARTIAL_LEGACY_SETUP_AND_RULES_PRESERVED_OK",
                "COMPLETE_LEGACY_SETUP_REPLACEMENT_IS_NOOP_OK",
                "CHANNEL_CATEGORY_PROVENANCE_AND_CLEANUP_BACKFILL_OK",
            ):
                self.assertIn(marker, output.getvalue())
        finally:
            MigrationExecutor(connection).migrate(targets)
        self.assertEqual(MigrationExecutor(connection).migration_plan(targets), [])
