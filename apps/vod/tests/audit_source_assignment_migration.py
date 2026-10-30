"""Run only in an empty, disposable database: 0009 -> 0010 -> 0009 -> 0010."""

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
    other_leaves = [
        node for node in executor.loader.graph.leaf_nodes() if node[0] != "vod"
    ]
    old_target = [*other_leaves, ("vod", "0009_library_metadata")]
    new_target = [*other_leaves, ("vod", "0010_source_tmdb_assignment")]
    executor.migrate(old_target)
    old = executor.loader.project_state(old_target).apps
    account = old.get_model("m3u", "M3UAccount").objects.create(
        name="Synthetic migration account", account_type="XC"
    )
    expected = []
    for kind, provider_field in (
        ("Movie", "stream_id"),
        ("Series", "external_series_id"),
    ):
        content = old.get_model("vod", kind).objects.create(
            name=f"Synthetic {kind}",
            year=2020,
            tmdb_id="123",
            tmdb_match_id="123",
            tmdb_status="matched",
            tmdb_metadata={"localized": {"en-US": {"title": "Curated"}}},
        )
        source = old.get_model("vod", f"M3U{kind}Relation").objects.create(
            m3u_account_id=account.pk,
            **{f"{kind.lower()}_id": content.pk, provider_field: "10"},
            manual_metadata={"audio_languages": ["ger"]},
        )
        expected.append((kind, content.pk, content.uuid, source.pk))
    for target in (new_target, old_target, new_target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        state = executor.loader.project_state(target).apps
        for kind, content_id, uuid, source_id in expected:
            content = state.get_model("vod", kind).objects.get(pk=content_id)
            source = state.get_model("vod", f"M3U{kind}Relation").objects.get(
                pk=source_id
            )
            assert content.uuid == uuid
            assert getattr(source, f"{kind.lower()}_id") == content_id
            assert source.manual_metadata == {"audio_languages": ["ger"]}
            assert content.tmdb_metadata["localized"]["en-US"]["title"] == "Curated"
            if target == new_target:
                assert source.tmdb_override_id == "123"
    # Older application writers can still insert rows after the additive upgrade.
    old.get_model("vod", "M3UMovieRelation").objects.create(
        m3u_account_id=account.pk, movie_id=expected[0][1], stream_id="old-writer"
    )
    assert (
        state.get_model("vod", "M3UMovieRelation")
        .objects.get(stream_id="old-writer")
        .tmdb_override_id
        == ""
    )
