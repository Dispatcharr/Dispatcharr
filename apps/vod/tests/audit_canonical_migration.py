"""Executable integration audit for an empty, isolated PostgreSQL database.

Run via manage.py shell with dispatcharr.settings_test and a test_* database.
Never run this audit against a deployed application database.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone


def run():
    if connection.vendor != "postgresql" or not connection.settings_dict[
        "NAME"
    ].startswith("test_"):
        raise RuntimeError(
            "Migration audit requires an isolated test_* PostgreSQL database."
        )
    executor = MigrationExecutor(connection)
    if (
        "vod",
        "0007_source_metadata_and_canonical_identity",
    ) in executor.loader.applied_migrations:
        raise RuntimeError("Migration audit must start before VOD 0007.")
    head = executor.loader.graph.leaf_nodes()
    before = [target for target in head if target[0] != "vod"] + [
        ("vod", "0006_movie_series_language")
    ]
    executor.migrate(before)
    state = executor.loader.project_state(before).apps
    Account = state.get_model("m3u", "M3UAccount")
    Movie = state.get_model("vod", "Movie")
    Series = state.get_model("vod", "Series")
    Episode = state.get_model("vod", "Episode")
    Category = state.get_model("vod", "VODCategory")
    CategoryRelation = state.get_model("vod", "M3UVODCategoryRelation")
    MovieSource = state.get_model("vod", "M3UMovieRelation")
    SeriesSource = state.get_model("vod", "M3USeriesRelation")
    EpisodeSource = state.get_model("vod", "M3UEpisodeRelation")
    accounts, movies, series, episodes, movie_sources, episode_sources = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for index, language in enumerate(("de", "en")):
        account = Account.objects.create(
            name=f"Synthetic migration provider {index}",
            account_type="XC",
            is_active=True,
        )
        accounts.append(account)
        movie_category = Category.objects.create(
            name=f"Migration movies {language}", category_type="movie"
        )
        series_category = Category.objects.create(
            name=f"Migration series {language}", category_type="series"
        )
        for category in (movie_category, series_category):
            CategoryRelation.objects.create(
                m3u_account=account,
                category=category,
                enabled=True,
                custom_properties={
                    "language": language,
                    "quality": "1080p",
                    "provider_marker": index,
                },
            )
        movie = Movie.objects.create(
            name="Shared movie",
            year=2020,
            tmdb_id="101",
            language=language,
            is_adult=bool(index),
            custom_properties={f"marker_{language}": True},
        )
        source = MovieSource.objects.create(
            movie=movie,
            m3u_account=account,
            category=movie_category,
            stream_id="same-provider-id",
            custom_properties={"basic_data": {"marker": index}},
        )
        movies.append((movie.pk, movie.uuid))
        movie_sources.append(source.pk)
        show = Series.objects.create(
            name="Shared series", year=2020, tmdb_id="202", language=language
        )
        show_source = SeriesSource.objects.create(
            series=show,
            m3u_account=account,
            category=series_category,
            external_series_id="series-id",
        )
        episode = Episode.objects.create(
            series=show,
            name="Episode one",
            season_number=1,
            episode_number=1,
            tmdb_id="303",
        )
        episode_source = EpisodeSource.objects.create(
            episode=episode,
            series_relation=show_source,
            m3u_account=account,
            stream_id="episode-id",
            custom_properties={
                "marker": index,
                "info": {
                    "id": "episode-id",
                    "info": {
                        "audio_languages": [language],
                        "subtitle_languages": ["fr"],
                        "resolution": "2160p",
                        "video_features": ["hdr"],
                    },
                },
            },
        )
        series.append((show.pk, show.uuid))
        episodes.append((episode.pk, episode.uuid))
        episode_sources.append(episode_source.pk)
    # A genuinely conflicting cross-ID group must roll back the entire DDL
    # and data migration, not silently merge unrelated titles.
    conflicts = [
        Movie.objects.create(
            name="Conflicting A", tmdb_id="501", imdb_id="tt-conflict", language="de"
        ),
        Movie.objects.create(
            name="Conflicting B", tmdb_id="502", imdb_id="tt-conflict", language="en"
        ),
    ]
    old_count = Movie.objects.count()
    highest_historical_id = max(row.pk for row in conflicts)
    try:
        MigrationExecutor(connection).migrate(head)
    except RuntimeError as exc:
        if "Conflicting VOD external identifiers" not in str(exc):
            raise
    else:
        raise AssertionError("Conflicting identifiers were not rejected.")
    assert Movie.objects.count() == old_count
    assert (
        "vod",
        "0007_source_metadata_and_canonical_identity",
    ) not in MigrationRecorder(connection).applied_migrations()
    assert "vod_vodcontentalias" not in connection.introspection.table_names()
    columns = {
        column.name
        for column in connection.introspection.get_table_description(
            connection.cursor(), "vod_movie"
        )
    }
    assert "language" in columns
    for row in conflicts:
        row.delete()
    print("ATOMIC_CONFLICT_ROLLBACK_OK")
    MigrationExecutor(connection).migrate(head)

    from apps.vod.models import Movie as CanonicalMovie, Series as CanonicalSeries
    from apps.vod.models import (
        Episode as CanonicalEpisode,
        M3UMovieRelation,
        M3UEpisodeRelation,
        VODContentAlias,
    )
    from apps.vod.references import output_reference
    from apps.vod.selection import resolve_content, source_candidates

    canonical = CanonicalMovie.objects.get(tmdb_id="101")
    assert canonical.pk > highest_historical_id
    assert canonical.pk not in {row[0] for row in movies}
    assert canonical.is_adult
    assert (
        canonical.custom_properties["marker_de"]
        and canonical.custom_properties["marker_en"]
    )
    assert (
        list(
            M3UMovieRelation.objects.filter(movie=canonical)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        == movie_sources
    )
    for index, (old_id, old_uuid) in enumerate(movies):
        obj, requirements = resolve_content("movie", old_id)
        assert obj.pk == canonical.pk
        assert requirements == {"audio_languages": ["ger" if index == 0 else "eng"]}
        assert resolve_content("movie", old_uuid, by_uuid=True)[0].pk == canonical.pk
        eligible = source_candidates(
            canonical.m3u_relations.order_by("pk"), requirements=requirements
        )
        assert len(eligible) == 1 and eligible[0].m3u_account_id == accounts[index].pk
    assert CanonicalSeries.objects.filter(tmdb_id="202").count() == 1
    assert CanonicalEpisode.objects.filter(tmdb_id="303").count() == 1
    episode = CanonicalEpisode.objects.get(tmdb_id="303")
    assert episode.pk not in {row[0] for row in episodes}
    assert set(
        M3UEpisodeRelation.objects.filter(episode=episode).values_list("pk", flat=True)
    ) == set(episode_sources)
    for index, source_id in enumerate(episode_sources):
        source = M3UEpisodeRelation.objects.select_related("series_relation").get(
            pk=source_id
        )
        effective = source.effective_metadata()
        assert effective["values"] == {
            "audio_languages": ["ger" if index == 0 else "eng"],
            "subtitle_languages": ["fre"],
            "resolution": "2160p",
            "video_features": ["hdr"],
        }
        assert all(value == "provider" for value in effective["provenance"].values())
        assert source.custom_properties["marker"] == index
    for index, (old_id, old_uuid) in enumerate(episodes):
        obj, requirements = resolve_content("episode", old_id)
        assert obj.pk == episode.pk
        assert requirements["audio_languages"] == ["ger" if index == 0 else "eng"]
    reference = output_reference(
        "movie", canonical.pk, {"audio_languages": ["ger"], "resolution": "1080p"}
    )
    future = CanonicalMovie.objects.create(name="Future canonical film")
    assert future.pk > reference.legacy_id
    assert VODContentAlias.objects.count() >= 7
    print("CANONICAL_MOVIE_SERIES_EPISODE_MIGRATION_OK")
    print("SOURCE_IDS_PAYLOADS_AND_OLD_PUBLIC_IDS_PRESERVED_OK")
    print("NESTED_EPISODE_METADATA_PRESERVED_AND_READ_WITHOUT_REFRESH_OK")
    print("PUBLIC_ID_COLLISION_GUARD_OK")


run()
