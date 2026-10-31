"""Isolated 0010 -> 0011 -> 0010 -> 0011 job-state compatibility audit."""

import os

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def run():
    if (
        os.environ.get("DISPATCHARR_ISOLATED_MIGRATION_AUDIT") != "1"
        or connection.vendor != "postgresql"
        or not connection.settings_dict["NAME"].startswith("test_04_")
    ):
        raise RuntimeError("An isolated test_04_* PostgreSQL database is required.")
    executor = MigrationExecutor(connection)
    others = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "vod"]
    before = [*others, ("vod", "0010_source_tmdb_assignment")]
    after = [*others, ("vod", "0011_library_pending_enrichment")]
    executor.migrate(before)
    old = executor.loader.project_state(before).apps.get_model(
        "vod", "VODMetadataState"
    )
    if old.objects.exists():
        raise RuntimeError("The migration audit requires an empty job-state table.")
    state = old.objects.create(
        pk=1,
        status="running",
        task_id="synthetic-job",
        selection=[["movie", 1]],
        progress={"operation": "enrich", "processed": 0},
    )
    for target in (after, before, after):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        model = executor.loader.project_state(target).apps.get_model(
            "vod", "VODMetadataState"
        )
        current = model.objects.get(pk=state.pk)
        assert current.task_id == "synthetic-job"
        assert current.status == "running"
        assert current.selection == [["movie", 1]]
        assert current.progress == {"operation": "enrich", "processed": 0}
        if target == after:
            assert current.pending_enrichment == []
            assert current.refreshing_accounts == []
            assert current.job_heartbeat is not None
    # Old application inserts remain valid while the additive columns exist.
    old.objects.create(pk=2, status="idle")
    compatible = model.objects.get(pk=2)
    assert compatible.pending_enrichment == []
    assert compatible.refreshing_accounts == []
    assert compatible.job_heartbeat is not None
