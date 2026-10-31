"""Provider import identity and relation-exact Library filtering regressions."""

from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.vod import library
from apps.vod.canonical_import import CanonicalImportIndex, ImportTitleError
from apps.vod.models import (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
)
from apps.vod.tasks import process_movie_batch, process_series_batch


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryCompletionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.force_authenticate(
            User.objects.create_user(username="completion-admin", user_level=10)
        )
        self.account = M3UAccount.objects.create(
            name="Synthetic provider", account_type="XC", is_active=True
        )
        self.fixtures = {}
        for kind, model, relation_model, importer, provider_id in (
            ("movie", Movie, M3UMovieRelation, process_movie_batch, "stream_id"),
            ("series", Series, M3USeriesRelation, process_series_batch, "series_id"),
        ):
            category = VODCategory.objects.create(
                name=f"Synthetic {kind}", category_type=kind
            )
            defaults = M3UVODCategoryRelation.objects.create(
                m3u_account=self.account, category=category, enabled=True
            )
            self.fixtures[kind] = (
                model,
                relation_model,
                importer,
                provider_id,
                category,
                defaults,
            )

    def endpoint(self, action="list"):
        return reverse(f"api:vod:library-{action}")

    def import_rows(self, kind, rows, *, index=None):
        _model, source_model, importer, provider_id, category, defaults = self.fixtures[
            kind
        ]
        result = importer(
            self.account,
            [
                {provider_id: str(position + 1), "category_id": "1", **row}
                for position, row in enumerate(rows)
            ],
            {"1": category},
            {category.pk: defaults},
            identity_index=index,
        )
        self.assertNotIn("failed", str(result).lower())
        return source_model.objects.filter(m3u_account=self.account).order_by("pk")

    def source(self, **values):
        category = self.fixtures["movie"][4]
        movie = Movie.objects.create(
            name=f"Synthetic title {Movie.objects.count()}", year=2020
        )
        return M3UMovieRelation.objects.create(
            m3u_account=self.account,
            category=category,
            movie=movie,
            stream_id=str(M3UMovieRelation.objects.count() + 10),
            **values,
        )

    def test_global_and_category_cleanup_are_used_during_movie_and_series_import(self):
        library.save_library_settings(
            {
                "title_rules": ["NF - "],
                "year_rules": [{"value": "[YYYY]", "position": "end"}],
            }
        )
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                fixture[5].custom_properties = {
                    "title_cleanup": {"pattern": r"^(EN|DE)\s*\|\s*"}
                }
                fixture[5].save()
                sources = list(
                    self.import_rows(
                        kind,
                        [
                            {"name": "NF - EN | Film [2020]"},
                            {"name": "NF - DE | Film [2020]"},
                        ],
                    )
                )
                self.assertEqual(fixture[0].objects.count(), 1)
                self.assertEqual(
                    getattr(sources[0], f"{kind}_id"), getattr(sources[1], f"{kind}_id")
                )
                content = fixture[0].objects.get()
                self.assertEqual((content.clean_title, content.year), ("Film", 2020))
                self.assertEqual(
                    sources[0].custom_properties["basic_data"]["name"],
                    "NF - EN | Film [2020]",
                )

    def test_id_and_no_id_rows_coalesce_without_losing_sources(self):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                self.import_rows(
                    kind,
                    [
                        {"name": "Film (2020)", "tmdb_id": "123"},
                        {"name": "Film (2020)"},
                    ],
                )
                self.assertEqual(fixture[0].objects.count(), 1)
                self.assertEqual(fixture[1].objects.count(), 2)

    def test_translated_exact_title_year_reuses_existing_canonical_and_ids_win(self):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                target = fixture[0].objects.create(
                    name="Provider title",
                    year=2020,
                    tmdb_id="123",
                    display_name="Film",
                    tmdb_metadata={"localized": {"de-DE": {"title": "Der Film"}}},
                )
                sources = self.import_rows(
                    kind,
                    [
                        {"name": "Der Film (2020)"},
                        {"name": "Unrelated title", "year": 2020, "tmdb_id": "123"},
                    ],
                )
                self.assertEqual(
                    {getattr(source, f"{kind}_id") for source in sources}, {target.pk}
                )

    def test_conflicting_ids_ambiguous_names_and_missing_year_do_not_merge(self):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                first = fixture[0].objects.create(
                    name="One", clean_title="Film", year=2020, tmdb_id="123"
                )
                fixture[0].objects.create(
                    name="Two", clean_title="Film", year=2020, tmdb_id="456"
                )
                sources = list(
                    self.import_rows(
                        kind,
                        [
                            {"name": "Film (2020)"},
                            {"name": "Film (2020)", "tmdb_id": "789"},
                            {"name": "Unknown"},
                            {"name": "Unknown"},
                        ],
                    )
                )
                self.assertNotEqual(getattr(sources[0], f"{kind}_id"), first.pk)
                self.assertEqual(
                    len({getattr(source, f"{kind}_id") for source in sources}), 4
                )

    def test_year_cache_is_reused_across_batches_and_refresh_is_idempotent(self):
        settings = library.library_settings()
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                index = CanonicalImportIndex(fixture[0], settings)
                first = self.import_rows(
                    kind, [{"name": "Film (2020)"}], index=index
                ).get()
                original_pk = getattr(first, f"{kind}_id")
                self.import_rows(kind, [{"name": "Renamed Film (2020)"}], index=index)
                self.assertEqual(fixture[0].objects.count(), 1)
                first.refresh_from_db()
                self.assertEqual(getattr(first, f"{kind}_id"), original_pk)

    def test_manual_source_match_survives_provider_identity_changes(self):
        for kind in self.fixtures:
            with self.subTest(kind=kind):
                source = self.import_rows(kind, [{"name": "Film (2020)"}]).get()
                target = library.move_source_to_tmdb(
                    kind,
                    source.pk,
                    {
                        "id": "123",
                        "imdb_id": "tt123",
                        "localized": {"en-US": {"title": "Curated film"}},
                    },
                )
                self.import_rows(
                    kind,
                    [
                        {
                            "name": "Wrong provider title (2021)",
                            "tmdb_id": "999",
                            "imdb_id": "tt999",
                        }
                    ],
                )
                source.refresh_from_db()
                target.refresh_from_db()
                self.assertEqual(
                    (getattr(source, f"{kind}_id"), source.tmdb_override_id),
                    (target.pk, "123"),
                )
                self.assertEqual(
                    (target.tmdb_id, target.imdb_id, target.display_name),
                    ("123", "tt123", ""),
                )
                self.assertEqual(target.clean_title, "Film")
                self.assertEqual(
                    target.tmdb_metadata["localized"]["en-US"]["title"], "Curated film"
                )

    def test_changed_cleanup_can_attach_a_new_source_without_replacing_a_known_source(
        self,
    ):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                library.save_library_settings({"title_rules": []})
                source = self.import_rows(kind, [{"name": "Prefix Film (2020)"}]).get()
                target = getattr(source, f"{kind}_id")
                library.save_library_settings({"title_rules": ["Prefix "]})
                rows = self.import_rows(
                    kind, [{"name": "Prefix Film (2020)"}, {"name": "Film (2020)"}]
                )
                self.assertEqual({getattr(row, f"{kind}_id") for row in rows}, {target})
                self.assertEqual(fixture[0].objects.get(pk=target).clean_title, "Film")

    def test_cleanup_failure_aborts_instead_of_skipping_existing_sources(self):
        for kind in self.fixtures:
            with self.subTest(kind=kind):
                source = self.import_rows(kind, [{"name": "Film (2020)"}]).get()
                before = (source.pk, source.last_seen, getattr(source, f"{kind}_id"))
                with (
                    patch(
                        "apps.vod.tasks.import_title",
                        side_effect=ImportTitleError("invalid cleanup"),
                    ),
                    self.assertRaises(ImportTitleError),
                ):
                    self.import_rows(kind, [{"name": "Film (2020)"}])
                source.refresh_from_db()
                self.assertEqual(
                    (source.pk, source.last_seen, getattr(source, f"{kind}_id")), before
                )

    def test_current_cleanup_matches_existing_titles_from_another_provider(self):
        library.save_library_settings({"title_rules": ["Prefix "]})
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                target = fixture[0].objects.create(
                    name="Prefix Film (2020)", clean_title="Prefix Film", year=2020
                )
                source = self.import_rows(kind, [{"name": "Film (2020)"}]).get()
                self.assertEqual(getattr(source, f"{kind}_id"), target.pk)

    def test_year_parser_supports_early_films_and_a_rolling_future_limit(self):
        from apps.vod.tasks import extract_year_from_data

        future = timezone.now().year + 5
        self.assertEqual(extract_year_from_data({"year": 1895}), 1895)
        self.assertEqual(extract_year_from_data({"name": f"Film [{future}]"}), future)
        self.assertIsNone(extract_year_from_data({"year": future + 1}))

    def test_all_technical_filters_must_match_the_same_source(self):
        source = self.source(
            manual_metadata={
                "audio_languages": ["ger"],
                "resolution": "1080p",
                "video_features": ["hdr"],
            },
            container_extension="mkv",
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=source.movie,
            category=source.category,
            stream_id="20",
            manual_metadata={"audio_languages": ["eng"], "resolution": "2160p"},
        )
        for view in ("titles", "sources", "posters"):
            self.assertEqual(
                self.client.get(
                    self.endpoint(),
                    {"view": view, "audio_language": "ger", "resolution": "2160p"},
                ).json()["count"],
                0,
            )
            self.assertEqual(
                self.client.get(
                    self.endpoint(),
                    {
                        "view": view,
                        "audio_language": "de",
                        "resolution": "1080p",
                        "video_feature": "HDR",
                        "container_extension": "mkv",
                    },
                ).json()["count"],
                1,
            )

    def test_filter_precedence_and_explicit_empty_values_match_source_display(self):
        source = self.source(
            declared_metadata={"audio_languages": ["eng"]},
            observed_metadata={"audio_languages": ["ger"]},
            manual_metadata={"audio_languages": []},
        )
        self.assertEqual(
            self.client.get(self.endpoint(), {"audio_language": "ger"}).json()["count"],
            0,
        )
        source.manual_metadata = {}
        source.save()
        self.assertEqual(
            self.client.get(self.endpoint(), {"audio_language": "ger"}).json()["count"],
            1,
        )
        self.assertEqual(
            self.client.get(self.endpoint(), {"audio_language": "eng"}).json()["count"],
            0,
        )

    def test_options_are_scoped_and_do_not_fall_back_through_explicit_empty(self):
        self.source(
            manual_metadata={
                "audio_languages": ["ger"],
                "subtitle_languages": ["eng"],
                "resolution": "1080p",
                "video_features": ["hdr"],
            },
            container_extension="mkv",
        )
        response = self.client.get(
            self.endpoint("filter-options"),
            {"type": "movie", "account": self.account.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audio_languages"], ["ger"])
        self.assertEqual(response.json()["container_extensions"], ["mkv"])
        self.assertEqual(
            self.client.get(self.endpoint("filter-options"), {"type": "series"}).json()[
                "audio_languages"
            ],
            [],
        )

    def test_content_filters_use_canonical_metadata_and_library_added_date(self):
        source = self.source()
        Movie.objects.filter(pk=source.movie_id).update(
            genre="Drama",
            library_added_at=timezone.now() - timedelta(days=20),
            tmdb_metadata={
                "genres": [{"name": "Animation"}],
                "is_anime": True,
                "adult": False,
            },
        )
        for params, count in (
            ({"genre": "Animation", "anime_mode": "only"}, 1),
            ({"genre": "Drama"}, 0),
            ({"adult_mode": "exclude"}, 1),
            ({"added_after_days": 7}, 0),
            ({"metadata_status": "missing_id"}, 1),
        ):
            self.assertEqual(
                self.client.get(self.endpoint(), params).json()["count"], count
            )

    @patch("apps.vod.library.tmdb_client")
    def test_bulk_tmdb_assignment_is_rejected_before_fetching_or_changing_sources(
        self, client
    ):
        sources = [self.source(), self.source()]
        client.return_value.details.return_value = {
            "id": "123",
            "localized": {"en-US": {"title": "Film"}},
        }
        response = self.client.patch(
            self.endpoint("source-metadata"),
            {
                "items": [
                    {"content_type": "movie", "id": source.pk} for source in sources
                ],
                "tmdb_id": "123",
                "manual_metadata": {"audio_languages": ["ger"]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        client.assert_not_called()
        for source in sources:
            source.refresh_from_db()
            self.assertEqual(source.manual_metadata, {})
            self.assertEqual(source.tmdb_override_id, "")

    def test_mixed_content_and_invalid_filter_values_are_rejected(self):
        source = self.source()
        for data in (
            {"items": [{"content_type": "movie", "id": source.pk}]},
            {
                "items": [
                    {"content_type": "movie", "id": source.pk},
                    {"content_type": "series", "id": 1},
                ],
                "tmdb_id": "123",
            },
        ):
            self.assertEqual(
                self.client.patch(
                    self.endpoint("source-metadata"), data, format="json"
                ).status_code,
                400,
            )
        for params in (
            {"resolution": "wrong"},
            {"audio_language": "invalid"},
            {"added_after_days": 0},
        ):
            self.assertEqual(self.client.get(self.endpoint(), params).status_code, 400)

    def test_partial_provider_ids_cannot_coalesce_a_known_source_with_a_conflicting_title(
        self,
    ):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                canonical = fixture[0].objects.create(
                    name="Film", clean_title="Film", year=2020, tmdb_id="123"
                )
                provider_field = (
                    "stream_id" if kind == "movie" else "external_series_id"
                )
                original = fixture[1].objects.create(
                    m3u_account=self.account,
                    category=fixture[4],
                    **{kind: canonical, provider_field: "1"},
                )
                rows = list(
                    self.import_rows(
                        kind,
                        [
                            {"name": "Film (2020)", "imdb_id": "tt123"},
                            {"name": "Film (2020)", "tmdb_id": "999"},
                        ],
                    )
                )
                original.refresh_from_db()
                self.assertEqual(getattr(original, f"{kind}_id"), canonical.pk)
                self.assertNotEqual(getattr(rows[1], f"{kind}_id"), canonical.pk)

    def test_exclusion_filters_keep_sources_with_unknown_optional_metadata(self):
        self.source()
        for params in ({"anime_mode": "exclude"}, {"adult_mode": "exclude"}):
            self.assertEqual(
                self.client.get(self.endpoint(), params).json()["count"], 1
            )

    @patch("apps.vod.library.tmdb_client")
    def test_missing_bulk_source_is_rejected_before_contacting_tmdb(self, client):
        source = self.source()
        response = self.client.patch(
            self.endpoint("source-metadata"),
            {
                "items": [
                    {"content_type": "movie", "id": source.pk},
                    {"content_type": "movie", "id": 999999},
                ],
                "manual_metadata": {"audio_languages": ["ger"]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        client.assert_not_called()
        source.refresh_from_db()
        self.assertEqual(source.tmdb_override_id, "")

    @patch("apps.vod.library.tmdb_client")
    def test_single_assignment_rolls_back_if_a_move_fails(self, client):
        sources = [self.source(), self.source()]
        original = [(source.pk, source.movie_id) for source in sources]
        client.return_value.details.return_value = {
            "id": "123",
            "localized": {"en-US": {"title": "Film"}},
        }
        move = library.move_source_to_tmdb

        def checked_move(kind, pk, metadata):
            move(kind, pk, metadata)
            raise ValueError("Conflicting episode identities")

        with patch("apps.vod.library.move_source_to_tmdb", side_effect=checked_move):
            response = self.client.patch(
                self.endpoint("source-metadata"),
                {
                    "items": [{"content_type": "movie", "id": sources[0].pk}],
                    "tmdb_id": "123",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            list(M3UMovieRelation.objects.order_by("pk").values_list("pk", "movie_id")),
            original,
        )
        self.assertFalse(Movie.objects.filter(tmdb_id="123").exists())
