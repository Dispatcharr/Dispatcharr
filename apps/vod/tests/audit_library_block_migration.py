"""Run only in an empty disposable database: 0011 -> 0012 -> 0011 -> 0012."""

import os

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def run():
    executor = MigrationExecutor(connection)
    current = executor.loader.project_state().apps
    if os.environ.get("DISPATCHARR_ISOLATED_MIGRATION_AUDIT") != "1" or any(
        current.get_model("vod", kind).objects.exists() for kind in ("Movie", "Series")
    ):
        raise RuntimeError(
            "This migration audit requires an empty disposable database."
        )
    others = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "vod"]
    old_target = [*others, ("vod", "0011_library_pending_enrichment")]
    new_target = [*others, ("vod", "0012_library_blocked")]
    executor.migrate(old_target)
    old = executor.loader.project_state(old_target).apps
    rows = []
    for kind in ("Movie", "Series"):
        row = old.get_model("vod", kind).objects.create(
            name=f"Synthetic {kind}",
            clean_title="Kept title",
            tmdb_lookup_excluded=True,
            tmdb_metadata={"localized": {"en-US": {"title": "Kept metadata"}}},
        )
        rows.append((kind, row.pk, row.uuid, row.library_added_at))
    for target in (new_target, old_target, new_target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        state = executor.loader.project_state(target).apps
        for kind, pk, uuid, added in rows:
            row = state.get_model("vod", kind).objects.get(pk=pk)
            assert row.uuid == uuid and row.library_added_at == added
            assert row.clean_title == "Kept title" and row.tmdb_lookup_excluded
            assert row.tmdb_metadata["localized"]["en-US"]["title"] == "Kept metadata"
            if target == new_target:
                assert row.library_blocked is False
    for kind in ("Movie", "Series"):
        row = old.get_model("vod", kind).objects.create(name="Old writer")
        assert (
            state.get_model("vod", kind).objects.get(pk=row.pk).library_blocked is False
        )
        state.get_model("vod", kind).objects.filter(pk=row.pk).update(
            library_blocked=True
        )
        assert (
            state.get_model("vod", kind).objects.get(pk=row.pk).library_blocked is True
        )
