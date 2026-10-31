"""Account-priority projection and the canonical metadata lock."""

from unittest.mock import patch

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod import library
from apps.vod.models import (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
)
from apps.vod.provider_metadata import PROVENANCE_KEY, reconcile_provider_metadata
from apps.vod.tasks import (
    process_movie_batch,
    process_series_batch,
    refresh_movie_advanced_data,
    refresh_series_episodes,
)


class ProviderMetadataTests(TestCase):
    def setUp(self):
        self.high = M3UAccount.objects.create(
            name="Higher priority", account_type="XC", priority=20, is_active=True
        )
        self.low = M3UAccount.objects.create(
            name="Lower priority", account_type="XC", priority=10, is_active=True
        )
        self.kinds = {
            "movie": (Movie, M3UMovieRelation, process_movie_batch, "stream_id"),
            "series": (Series, M3USeriesRelation, process_series_batch, "series_id"),
        }
        self.categories = {}
        for kind in self.kinds:
            category = VODCategory.objects.create(
                name=f"Synthetic {kind}", category_type=kind
            )
            self.categories[kind] = category
            for account in (self.high, self.low):
                M3UVODCategoryRelation.objects.create(
                    m3u_account=account, category=category, enabled=True
                )

    def import_row(self, kind, account, **values):
        _model, source_model, importer, provider_id = self.kinds[kind]
        category = self.categories[kind]
        relation = M3UVODCategoryRelation.objects.get(
            m3u_account=account, category=category
        )
        result = importer(
            account,
            [
                {
                    provider_id: "1",
                    "name": "Film (2020)",
                    "tmdb_id": "123",
                    "year": 2020,
                    "category_id": "1",
                    **values,
                }
            ],
            {"1": category},
            {category.pk: relation},
        )
        self.assertNotIn("failed", str(result).lower())
        return source_model.objects.get(m3u_account=account)

    def test_both_import_orders_use_account_priority_not_last_refresh(self):
        for kind, (model, _, _, _) in self.kinds.items():
            for order in ((self.high, self.low), (self.low, self.high)):
                with self.subTest(kind=kind, first=order[0].priority):
                    model.objects.all().delete()
                    for account in order:
                        self.import_row(
                            kind,
                            account,
                            plot=account.name,
                            genre=account.name,
                            rating="8.0" if account == self.high else "3.0",
                        )
                    item = model.objects.get()
                    self.assertEqual(item.description, self.high.name)
                    self.assertEqual(item.genre, self.high.name)
                    self.assertEqual(item.rating, "8.0")
                    self.assertEqual(
                        item.custom_properties[PROVENANCE_KEY]["description"][
                            "account_id"
                        ],
                        self.high.pk,
                    )
                    self.import_row(kind, self.low, plot="New low value")
                    item.refresh_from_db()
                    self.assertEqual(item.description, self.high.name)

    def test_lower_priority_only_fills_missing_fields(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                self.import_row(kind, self.high, plot="", genre="Priority genre")
                source = self.import_row(
                    kind, self.low, plot="Fallback description", genre="Other genre"
                )
                item = getattr(source, kind)
                self.assertEqual(item.description, "Fallback description")
                self.assertEqual(item.genre, "Priority genre")

    def test_locked_canonical_survives_refresh_while_source_payload_changes(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                self.import_row(
                    kind,
                    self.high,
                    plot="Stable",
                    genre="Stable",
                    rating="8",
                    stream_icon="https://example.com/a.jpg",
                    cover="https://example.com/a.jpg",
                )
                source = self.import_row(kind, self.low, plot="Other")
                item = getattr(source, kind)
                item.tmdb_lookup_excluded = True
                item.save(update_fields=["tmdb_lookup_excluded"])
                before = {
                    field: getattr(item, field)
                    for field in (
                        "description",
                        "genre",
                        "rating",
                        "year",
                        "clean_title",
                        "logo_id",
                        "custom_properties",
                    )
                }
                source = self.import_row(
                    kind,
                    self.high,
                    name="Changed title (2021)",
                    year=2021,
                    plot="Changed",
                    genre="Changed",
                    rating="2",
                    stream_icon="https://example.com/b.jpg",
                    cover="https://example.com/b.jpg",
                )
                item.refresh_from_db()
                self.assertEqual(
                    {field: getattr(item, field) for field in before}, before
                )
                self.assertEqual(
                    source.custom_properties["basic_data"]["plot"], "Changed"
                )
                self.assertEqual(reconcile_provider_metadata(kind, [item.pk]), 0)
                item.tmdb_lookup_excluded = False
                item.save(update_fields=["tmdb_lookup_excluded"])
                reconcile_provider_metadata(kind, [item.pk])
                item.refresh_from_db()
                self.assertEqual(item.description, "Changed")

    def test_language_selection_does_not_change_provider_priority(self):
        self.import_row("movie", self.high, plot="Higher")
        source = self.import_row("movie", self.low, plot="Lower")
        library.save_library_settings({"languages": ["es-ES", "de-DE"]})
        reconcile_provider_metadata("movie", [source.movie_id])
        source.movie.refresh_from_db()
        self.assertEqual(source.movie.description, "Higher")

    def test_formatted_source_year_repairs_unlocked_stale_year_and_survives_sparse_sources(
        self,
    ):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                source = self.import_row(kind, self.high, name="2012 - 2009", year=None)
                self.import_row(kind, self.low, name="2012", year=None)
                item = getattr(source, kind)
                item.year = 2012
                item.save(update_fields=["year"])
                reconcile_provider_metadata(kind, [item.pk])
                item.refresh_from_db()
                self.assertEqual((item.clean_title, item.year), ("2012", 2009))
                self.import_row(kind, self.low, name="2012", year=None)
                item.refresh_from_db()
                self.assertEqual((item.clean_title, item.year), ("2012", 2009))

    def test_unmarked_numbers_do_not_create_a_year_during_movie_or_series_import(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                source = self.import_row(
                    kind, self.high, name="Class of 1984", year=None
                )
                item = getattr(source, kind)
                self.assertEqual(item.clean_title, "Class of 1984")
                self.assertIsNone(item.year)

    def test_equal_priority_has_a_stable_account_tiebreak_and_inactive_sources_are_skipped(
        self,
    ):
        self.low.priority = self.high.priority
        self.low.save(update_fields=["priority"])
        self.import_row("movie", self.low, plot="Later account")
        source = self.import_row("movie", self.high, plot="Earlier account")
        self.assertEqual(source.movie.description, "Earlier account")
        self.high.is_active = False
        self.high.save(update_fields=["is_active"])
        reconcile_provider_metadata("movie", [source.movie_id])
        source.movie.refresh_from_db()
        self.assertEqual(source.movie.description, "Later account")

    def test_import_keeps_titles_open_and_retries_a_changed_lookup_title(self):
        source = self.import_row("movie", self.high, plot="First")
        reconcile_provider_metadata("movie", [source.movie_id])
        movie = Movie.objects.get(pk=source.movie_id)
        self.assertFalse(movie.tmdb_lookup_excluded)
        Movie.objects.filter(pk=movie.pk).update(
            tmdb_status="not_found",
            tmdb_metadata={"_lookup_key": [movie.clean_title, movie.year]},
        )
        self.import_row("movie", self.high, plot="Updated")
        movie.refresh_from_db()
        self.assertEqual(movie.description, "Updated")
        self.assertEqual(movie.tmdb_status, "not_found")
        library.save_library_settings({"title_rules": ["Film"]})
        self.import_row("movie", self.high, name="Film Night (2020)")
        movie.refresh_from_db()
        self.assertEqual(movie.clean_title, "Night")
        self.assertEqual(movie.tmdb_status, "")
        self.assertFalse(movie.tmdb_lookup_excluded)

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_cleanup_finalizes_and_locks_provider_only_metadata(self, _publish):
        source = self.import_row("movie", self.high, plot="Stable")
        state = library.queue_library_job("cleanup", [("movie", source.movie_id)])
        library.run_library_job(state["task_id"])
        source.movie.refresh_from_db()
        self.assertTrue(source.movie.tmdb_lookup_excluded)
        self.import_row("movie", self.high, plot="Changed")
        source.movie.refresh_from_db()
        self.assertEqual(source.movie.description, "Stable")

    @patch("core.xtream_codes.Client")
    def test_movie_detail_refresh_updates_raw_source_but_not_locked_canonical(
        self, factory
    ):
        source = self.import_row("movie", self.high, plot="Stable")
        Movie.objects.filter(pk=source.movie_id).update(tmdb_lookup_excluded=True)
        factory.return_value.__enter__.return_value.get_vod_info.return_value = {
            "info": {"plot": "New details", "genre": "New genre", "rating": "2"},
            "movie_data": {"name": "Changed"},
        }
        refresh_movie_advanced_data(source.pk, force_refresh=True)
        source.refresh_from_db()
        self.assertEqual(source.movie.description, "Stable")
        self.assertEqual(
            source.custom_properties["detailed_info"]["plot"], "New details"
        )

    @patch("apps.vod.tasks.XtreamCodesClient")
    def test_series_details_update_raw_source_but_not_locked_canonical(self, factory):
        source = self.import_row("series", self.high, plot="Stable")
        Series.objects.filter(pk=source.series_id).update(tmdb_lookup_excluded=True)
        factory.return_value.__enter__.return_value.get_series_info.return_value = {
            "info": {"plot": "New details"},
            "episodes": {},
        }
        refresh_series_episodes(self.high, source.series, "1")
        source.refresh_from_db()
        self.assertEqual(source.series.description, "Stable")
        self.assertEqual(
            source.custom_properties["detailed_info"]["plot"], "New details"
        )
