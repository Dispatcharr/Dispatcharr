"""Executable upgrade/rollback audit; requires an empty test_* PostgreSQL DB."""

from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


def run():
    if connection.vendor != "postgresql" or not connection.settings_dict[
        "NAME"
    ].startswith("test_"):
        raise RuntimeError(
            "Library migration audit requires isolated test_* PostgreSQL."
        )
    executor = MigrationExecutor(connection)
    if ("vod", "0009_library_metadata") in executor.loader.applied_migrations:
        raise RuntimeError("Start the library audit before VOD 0009.")
    head = executor.loader.graph.leaf_nodes()
    before = [target for target in head if target[0] != "vod"] + [
        ("vod", "0008_category_ignored")
    ]
    executor.migrate(before)
    old = executor.loader.project_state(before).apps
    account = old.get_model("m3u", "M3UAccount").objects.create(
        name="Synthetic Library migration", account_type="XC"
    )
    category = old.get_model("vod", "VODCategory").objects.create(
        name="Migration", category_type="movie"
    )
    category_relation = old.get_model("vod", "M3UVODCategoryRelation").objects.create(
        m3u_account=account,
        category=category,
        enabled=True,
        metadata_defaults={
            "audio_languages": ["ger", "eng"],
            "video_features": ["hdr"],
        },
        custom_properties={"marker": True},
    )
    date = timezone.now() - timedelta(days=365)
    originals = []
    for name in ("Movie", "Series"):
        model = old.get_model("vod", name)
        item = model.objects.create(
            name=f"Provider {name}", tmdb_id="123", custom_properties={"retained": True}
        )
        model.objects.filter(pk=item.pk).update(created_at=date)
        originals.append((name, item.pk, item.uuid))
    source = old.get_model("vod", "M3UMovieRelation").objects.create(
        m3u_account=account,
        movie_id=originals[0][1],
        category=category,
        stream_id="retained-id",
        manual_metadata={"subtitle_languages": ["fre"]},
    )
    MigrationExecutor(connection).migrate(head)
    state = MigrationExecutor(connection).loader.project_state(head).apps
    for name, pk, public_uuid in originals:
        item = state.get_model("vod", name).objects.get(pk=pk)
        assert item.uuid == public_uuid and item.name == f"Provider {name}"
        assert item.library_added_at == date
        assert item.tmdb_metadata == {} and item.display_name == ""
        assert not item.tmdb_lookup_excluded
    current_source = state.get_model("vod", "M3UMovieRelation").objects.get(
        pk=source.pk
    )
    assert current_source.stream_id == "retained-id"
    assert current_source.manual_metadata == {"subtitle_languages": ["fre"]}
    current_category = state.get_model("vod", "M3UVODCategoryRelation").objects.get(
        pk=category_relation.pk
    )
    assert current_category.custom_properties == {"marker": True}
    assert current_category.metadata_defaults["audio_languages"] == ["ger", "eng"]
    # The previous application schema can still insert rows after upgrading:
    # every newly required field has a database default.
    compatible = old.get_model("vod", "Movie").objects.create(
        name="Previous application insert"
    )
    assert (
        state.get_model("vod", "Movie").objects.get(pk=compatible.pk).display_name == ""
    )
    MigrationExecutor(connection).migrate(before)
    assert (
        old.get_model("vod", "M3UMovieRelation").objects.get(pk=source.pk).movie_id
        == originals[0][1]
    )
    MigrationExecutor(connection).migrate(head)
    assert (
        state.get_model("vod", "Movie").objects.get(pk=originals[0][1]).uuid
        == originals[0][2]
    )
