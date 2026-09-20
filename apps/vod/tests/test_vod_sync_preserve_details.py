"""List sync keeps relation detail payloads and non-blank movie/series fields."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    M3UVODCategoryRelation,
    Series,
    VODCategory,
)
from apps.vod.tasks import (
    is_blank_vod_value,
    process_movie_batch,
    process_series_batch,
    refresh_movie_advanced_data,
    refresh_series_episodes,
    should_apply_provider_list_field,
)
from apps.vod.tmdb import DEFAULT_TITLE_YEAR_RULES
from core.models import CoreSettings


class VODListFieldHelperTests(SimpleTestCase):
    def test_is_blank_vod_value(self):
        self.assertTrue(is_blank_vod_value(None))
        self.assertTrue(is_blank_vod_value(""))
        self.assertTrue(is_blank_vod_value([]))
        self.assertTrue(is_blank_vod_value([None, ""]))
        self.assertFalse(is_blank_vod_value("plot"))
        self.assertFalse(is_blank_vod_value(0))
        self.assertFalse(is_blank_vod_value(["https://cdn.example.com/a.jpg"]))

    def test_should_apply_provider_list_field(self):
        self.assertFalse(should_apply_provider_list_field("kept plot", ""))
        self.assertFalse(should_apply_provider_list_field("kept plot", None))
        self.assertFalse(should_apply_provider_list_field("same", "same"))
        self.assertTrue(should_apply_provider_list_field("", "new plot"))
        self.assertTrue(should_apply_provider_list_field("old", "new"))
        self.assertTrue(should_apply_provider_list_field(None, "Comedy"))


class VODBatchSourceVariantTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Variant Provider",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )

    def _categories(self, category_type):
        first = VODCategory.objects.create(
            name=f"First {category_type}",
            category_type=category_type,
        )
        second = VODCategory.objects.create(
            name=f"Second {category_type}",
            category_type=category_type,
        )
        first_relation = M3UVODCategoryRelation.objects.create(
            category=first,
            m3u_account=self.account,
            enabled=True,
        )
        second_relation = M3UVODCategoryRelation.objects.create(
            category=second,
            m3u_account=self.account,
            enabled=True,
        )
        return (
            {"10": first, "20": second},
            {first.id: first_relation, second.id: second_relation},
        )

    def test_movie_batch_keeps_all_sources_for_same_tmdb_id(self):
        categories, relations = self._categories("movie")
        process_movie_batch(
            self.account,
            [
                {
                    "stream_id": 1001,
                    "name": "NF - Shared Movie",
                    "tmdb_id": "500",
                    "category_id": "10",
                },
                {
                    "stream_id": 1002,
                    "name": "DE - Shared Movie",
                    "tmdb_id": "500",
                    "category_id": "20",
                },
            ],
            categories,
            relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(Movie.objects.filter(tmdb_id="500").count(), 1)
        source_relations = M3UMovieRelation.objects.filter(
            m3u_account=self.account,
            movie__tmdb_id="500",
        ).order_by("stream_id")
        self.assertEqual(source_relations.count(), 2)
        self.assertEqual(
            [relation.category_id for relation in source_relations],
            [categories["10"].id, categories["20"].id],
        )
        self.assertEqual(
            [
                relation.custom_properties["basic_data"]["name"]
                for relation in source_relations
            ],
            ["NF - Shared Movie", "DE - Shared Movie"],
        )

    def test_movie_batch_preserves_manual_tmdb_source_assignment(self):
        categories, relations = self._categories("movie")
        row = {
            "stream_id": 1001,
            "name": "Wrong Provider Movie",
            "tmdb_id": "500",
            "category_id": "10",
        }
        process_movie_batch(
            self.account,
            [row],
            categories,
            relations,
            scan_start_time=timezone.now(),
        )
        relation = M3UMovieRelation.objects.get(stream_id="1001")
        target = Movie.objects.create(
            name="Correct TMDB Movie",
            display_name="Correct TMDB Movie",
            tmdb_id="76600",
            tmdb_match_id="76600",
            tmdb_status="matched",
        )
        relation.movie = target
        relation.tmdb_override_id = "76600"
        relation.save(update_fields=["movie", "tmdb_override_id"])

        process_movie_batch(
            self.account,
            [row],
            categories,
            relations,
            scan_start_time=timezone.now(),
        )

        relation.refresh_from_db()
        self.assertEqual(relation.movie_id, target.id)
        self.assertEqual(relation.tmdb_override_id, "76600")

    def test_series_batch_keeps_all_sources_for_same_tmdb_id(self):
        categories, relations = self._categories("series")
        process_series_batch(
            self.account,
            [
                {
                    "series_id": 2001,
                    "name": "NF - Shared Series",
                    "tmdb": "246",
                    "category_id": "10",
                },
                {
                    "series_id": 2002,
                    "name": "NICK - Shared Series",
                    "tmdb": "246",
                    "category_id": "20",
                },
            ],
            categories,
            relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(Series.objects.filter(tmdb_id="246").count(), 1)
        source_relations = M3USeriesRelation.objects.filter(
            m3u_account=self.account,
            series__tmdb_id="246",
        ).order_by("external_series_id")
        self.assertEqual(source_relations.count(), 2)
        self.assertEqual(
            [relation.category_id for relation in source_relations],
            [categories["10"].id, categories["20"].id],
        )
        self.assertEqual(
            [
                relation.custom_properties["basic_data"]["name"]
                for relation in source_relations
            ],
            ["NF - Shared Series", "NICK - Shared Series"],
        )

    def test_series_batch_preserves_manual_tmdb_source_assignment(self):
        categories, relations = self._categories("series")
        row = {
            "series_id": 2001,
            "name": "Wrong Provider Series",
            "tmdb": "246",
            "category_id": "10",
        }
        process_series_batch(
            self.account,
            [row],
            categories,
            relations,
            scan_start_time=timezone.now(),
        )
        relation = M3USeriesRelation.objects.get(external_series_id="2001")
        target = Series.objects.create(
            name="Correct TMDB Series",
            display_name="Correct TMDB Series",
            tmdb_id="1399",
            tmdb_match_id="1399",
            tmdb_status="matched",
        )
        relation.series = target
        relation.tmdb_override_id = "1399"
        relation.save(update_fields=["series", "tmdb_override_id"])

        process_series_batch(
            self.account,
            [row],
            categories,
            relations,
            scan_start_time=timezone.now(),
        )

        relation.refresh_from_db()
        self.assertEqual(relation.series_id, target.id)
        self.assertEqual(relation.tmdb_override_id, "1399")

    def test_movie_batch_skips_blank_provider_rows_without_losing_valid_rows(self):
        categories, relations = self._categories("movie")

        process_movie_batch(
            self.account,
            [
                {"stream_id": 3001, "name": None, "category_id": "10"},
                {"stream_id": None, "name": "Missing ID", "category_id": "10"},
                {"stream_id": 3002, "name": "  Valid Movie  ", "category_id": "20"},
            ],
            categories,
            relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(Movie.objects.count(), 1)
        self.assertEqual(Movie.objects.get().name, "Valid Movie")
        self.assertEqual(
            list(M3UMovieRelation.objects.values_list("stream_id", flat=True)),
            ["3002"],
        )

    def test_series_batch_skips_blank_provider_rows_without_losing_valid_rows(self):
        categories, relations = self._categories("series")

        process_series_batch(
            self.account,
            [
                {"series_id": 4001, "name": "   ", "category_id": "10"},
                {"series_id": "", "name": "Missing ID", "category_id": "10"},
                {"series_id": 4002, "name": "  Valid Series  ", "category_id": "20"},
            ],
            categories,
            relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(Series.objects.count(), 1)
        self.assertEqual(Series.objects.get().name, "Valid Series")
        self.assertEqual(
            list(
                M3USeriesRelation.objects.values_list(
                    "external_series_id", flat=True
                )
            ),
            ["4002"],
        )

    def test_movie_batch_database_failure_is_not_reported_as_success(self):
        categories, relations = self._categories("movie")

        with patch.object(
            Movie.objects,
            "bulk_create",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                process_movie_batch(
                    self.account,
                    [{"stream_id": 5001, "name": "Valid", "category_id": "10"}],
                    categories,
                    relations,
                    scan_start_time=timezone.now(),
                )


class VODSyncPreserveDetailsTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Test XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category = VODCategory.objects.create(
            name="Test Movies",
            category_type="movie",
        )
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category,
            m3u_account=self.account,
            enabled=True,
        )
        self.movie = Movie.objects.create(
            name="Dummy Test Film",
            year=2024,
            tmdb_id="900001",
            description="Dummy plot for advanced detail.",
        )
        self.relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            category=self.category,
            stream_id="1001",
            container_extension="mkv",
            last_advanced_refresh=timezone.now(),
            custom_properties={
                "basic_data": {"stream_id": 1001, "name": self.movie.name},
                "detailed_fetched": True,
                "detailed_info": {
                    "plot": self.movie.description,
                    "backdrop_path": ["https://cdn.example.com/backdrop.jpg"],
                },
            },
        )
        self.categories = {
            "10": self.category,
            "__uncategorized__": self.category,
        }
        self.relations = {self.category.id: self.cat_relation}

    def _list_row(self, **overrides):
        row = {
            "stream_id": 1001,
            "name": "Dummy Test Film",
            "category_id": "10",
            "tmdb_id": "900001",
            "container_extension": "mkv",
        }
        row.update(overrides)
        return row

    def _process_list_batch(self, **row_overrides):
        process_movie_batch(
            self.account,
            [self._list_row(**row_overrides)],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

    def test_list_sync_preserves_description_and_detailed_info(self):
        self._process_list_batch(stream_icon="http://example.com/poster.jpg")

        self.movie.refresh_from_db()
        self.relation.refresh_from_db()
        props = self.relation.custom_properties or {}

        self.assertEqual(self.movie.description, "Dummy plot for advanced detail.")
        self.assertTrue(props.get("detailed_fetched"))
        self.assertEqual(
            props.get("detailed_info", {}).get("plot"),
            "Dummy plot for advanced detail.",
        )
        self.assertIn("basic_data", props)
        self.assertEqual(props["basic_data"].get("stream_id"), 1001)

    def test_list_sync_still_applies_non_empty_field_updates(self):
        self._process_list_batch(genre="Action")

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.genre, "Action")
        self.assertEqual(self.movie.description, "Dummy plot for advanced detail.")

    @patch("core.xtream_codes.Client")
    def test_refresh_runs_when_detailed_fetched_false_despite_recent_timestamp(
        self, mock_client_cls
    ):
        self.relation.custom_properties = {
            "basic_data": {"stream_id": 1001},
            "detailed_fetched": False,
        }
        self.relation.last_advanced_refresh = timezone.now()
        self.relation.save(update_fields=["custom_properties", "last_advanced_refresh"])
        self.movie.description = ""
        self.movie.save(update_fields=["description"])

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            "info": {
                "plot": "Provider plot returns.",
                "rating": "7.5",
                "genre": "Action",
                "duration_secs": "5400",
                "releasedate": "2024-01-15",
                "tmdb_id": "900001",
                "backdrop_path": ["https://cdn.example.com/bd.jpg"],
            },
            "movie_data": {"stream_id": 1001, "name": self.movie.name},
        }

        result = refresh_movie_advanced_data(self.relation.id, force_refresh=False)

        self.assertEqual(result, "Advanced data refreshed.")
        mock_client.get_vod_info.assert_called_once_with("1001")
        self.movie.refresh_from_db()
        self.relation.refresh_from_db()
        self.assertEqual(self.movie.description, "Provider plot returns.")
        self.assertTrue((self.relation.custom_properties or {}).get("detailed_fetched"))

    @patch("core.xtream_codes.Client")
    def test_refresh_skips_when_details_were_already_fetched(self, mock_client_cls):
        result = refresh_movie_advanced_data(self.relation.id, force_refresh=False)

        self.assertEqual(result, "Advanced data already fetched, skipping.")
        mock_client_cls.assert_not_called()

    @patch("core.xtream_codes.Client")
    def test_old_details_refresh_only_when_forced(self, mock_client_cls):
        self.relation.last_advanced_refresh = timezone.now() - timedelta(hours=25)
        self.relation.save(update_fields=["last_advanced_refresh"])

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            "info": {"plot": "Refreshed after window."},
            "movie_data": {},
        }

        result = refresh_movie_advanced_data(self.relation.id, force_refresh=True)

        self.assertEqual(result, "Advanced data refreshed.")
        mock_client.get_vod_info.assert_called_once()

    @patch("core.xtream_codes.Client")
    def test_source_refresh_does_not_overwrite_manual_tmdb_target(
        self, mock_client_cls
    ):
        target = Movie.objects.create(
            name="TMDB title",
            display_name="TMDB title",
            description="TMDB plot",
            tmdb_id="76600",
            tmdb_match_id="76600",
            tmdb_status="matched",
        )
        self.relation.movie = target
        self.relation.tmdb_override_id = "76600"
        self.relation.custom_properties = {"detailed_fetched": False}
        self.relation.save(
            update_fields=["movie", "tmdb_override_id", "custom_properties"]
        )
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            "info": {
                "name": "Wrong provider title",
                "plot": "Wrong provider plot",
                "tmdb_id": "900001",
            },
            "movie_data": {"stream_id": 1001},
        }

        result = refresh_movie_advanced_data(
            self.relation.id, force_refresh=False
        )

        target.refresh_from_db()
        self.relation.refresh_from_db()
        self.assertEqual(
            result,
            "Advanced source data refreshed; canonical override preserved.",
        )
        self.assertEqual(target.name, "TMDB title")
        self.assertEqual(target.description, "TMDB plot")
        self.assertEqual(
            self.relation.custom_properties["detailed_info"]["name"],
            "Wrong provider title",
        )


class VODSeriesSyncPreserveDetailsTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Test XC Series",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category = VODCategory.objects.create(
            name="Test Series",
            category_type="series",
        )
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category,
            m3u_account=self.account,
            enabled=True,
        )
        self.series = Series.objects.create(
            name="Dummy Test Series",
            year=2023,
            tmdb_id="900002",
            description="Dummy series plot for advanced detail.",
        )
        self.relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            category=self.category,
            external_series_id="2002",
            last_episode_refresh=timezone.now(),
            custom_properties={
                "basic_data": {"series_id": 2002, "name": self.series.name},
                "detailed_fetched": True,
                "episodes_fetched": True,
                "detailed_info": {"plot": self.series.description},
            },
        )
        self.categories = {
            "20": self.category,
            "__uncategorized__": self.category,
        }
        self.relations = {self.category.id: self.cat_relation}

    def test_list_sync_preserves_description_and_fetch_flags(self):
        process_series_batch(
            self.account,
            [
                {
                    "series_id": 2002,
                    "name": "Dummy Test Series",
                    "category_id": "20",
                    "tmdb_id": "900002",
                    "cover": "http://example.com/series-cover.jpg",
                }
            ],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

        self.series.refresh_from_db()
        self.relation.refresh_from_db()
        props = self.relation.custom_properties or {}

        self.assertEqual(
            self.series.description,
            "Dummy series plot for advanced detail.",
        )
        self.assertTrue(props.get("detailed_fetched"))
        self.assertTrue(props.get("episodes_fetched"))
        self.assertEqual(
            props.get("detailed_info", {}).get("plot"),
            "Dummy series plot for advanced detail.",
        )

    @patch("apps.vod.tasks.XtreamCodesClient")
    def test_episode_refresh_stores_relation_specific_series_details(
        self, mock_client_cls
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_series_info.return_value = {
            "info": {
                "name": "Clean Provider Series Title",
                "plot": "Provider-specific plot",
                "backdrop_path": ["https://cdn.example.com/provider-series.jpg"],
            },
            "episodes": {},
        }

        refresh_series_episodes(
            self.account,
            self.series,
            self.relation.external_series_id,
        )

        self.relation.refresh_from_db()
        details = (self.relation.custom_properties or {}).get("detailed_info", {})
        self.assertEqual(details.get("name"), "Clean Provider Series Title")
        self.assertEqual(details.get("plot"), "Provider-specific plot")
        self.assertEqual(
            details.get("backdrop_path"),
            ["https://cdn.example.com/provider-series.jpg"],
        )


class VODMovieIsAdultSyncTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Adult XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category = VODCategory.objects.create(
            name="Movies",
            category_type="movie",
        )
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category,
            m3u_account=self.account,
            enabled=True,
        )
        self.categories = {
            "10": self.category,
            "__uncategorized__": self.category,
        }
        self.relations = {self.category.id: self.cat_relation}

    def _process(self, **row_overrides):
        row = {
            "stream_id": 2001,
            "name": "Provider Film",
            "category_id": "10",
            "container_extension": "mp4",
        }
        row.update(row_overrides)
        process_movie_batch(
            self.account,
            [row],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

    def test_creates_movie_is_adult_from_string_one(self):
        self._process(is_adult="1")
        movie = Movie.objects.get(name="Provider Film")
        self.assertTrue(movie.is_adult)

    def test_creates_movie_is_adult_from_integer_one(self):
        self._process(is_adult=1, stream_id=2002, name="Int Adult Film")
        movie = Movie.objects.get(name="Int Adult Film")
        self.assertTrue(movie.is_adult)

    def test_creates_movie_not_adult_from_zero(self):
        self._process(is_adult=0, stream_id=2003, name="Safe Film")
        movie = Movie.objects.get(name="Safe Film")
        self.assertFalse(movie.is_adult)

    def test_updates_existing_movie_is_adult(self):
        movie = Movie.objects.create(
            name="Provider Film",
            tmdb_id="900010",
            is_adult=False,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie,
            category=self.category,
            stream_id="2001",
            custom_properties={"basic_data": {"stream_id": 2001}},
        )
        self._process(is_adult="1", tmdb_id="900010")
        movie.refresh_from_db()
        self.assertTrue(movie.is_adult)

    def test_sparse_provider_row_without_is_adult_key_does_not_clear_flag(self):
        """A second provider matched to the same movie (TMDB/IMDB/name+year)
        that simply omits is_adult from its list row must not undo a flag
        another provider already set, matching how sparse description/genre/etc.
        rows are ignored elsewhere in this module.
        """
        movie = Movie.objects.create(
            name="Shared Adult Film",
            tmdb_id="900011",
            is_adult=True,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie,
            category=self.category,
            stream_id="2001",
            custom_properties={"basic_data": {"stream_id": 2001}},
        )
        # Provider row has no "is_adult" key at all (not 0, just absent).
        self._process(tmdb_id="900011")
        movie.refresh_from_db()
        self.assertTrue(movie.is_adult)

    def test_explicit_zero_from_second_provider_still_clears_flag(self):
        """Unlike an omitted key, an explicit 0 is real signal and should apply."""
        movie = Movie.objects.create(
            name="Reclassified Film",
            tmdb_id="900012",
            is_adult=True,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie,
            category=self.category,
            stream_id="2001",
            custom_properties={"basic_data": {"stream_id": 2001}},
        )
        self._process(is_adult=0, tmdb_id="900012")
        movie.refresh_from_db()
        self.assertFalse(movie.is_adult)


class VODBlankNameBatchTests(TestCase):
    """Blank provider names are skipped without discarding the rest of the batch."""

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Blank Name XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.movie_category = VODCategory.objects.create(
            name="Blank Movies", category_type="movie",
        )
        self.series_category = VODCategory.objects.create(
            name="Blank Series", category_type="series",
        )
        self.movie_relations = {
            self.movie_category.id: M3UVODCategoryRelation.objects.create(
                category=self.movie_category, m3u_account=self.account, enabled=True,
            )
        }
        self.series_relations = {
            self.series_category.id: M3UVODCategoryRelation.objects.create(
                category=self.series_category, m3u_account=self.account, enabled=True,
            )
        }
        self.movie_categories = {
            "10": self.movie_category, "__uncategorized__": self.movie_category,
        }
        self.series_categories = {
            "20": self.series_category, "__uncategorized__": self.series_category,
        }

    def test_blank_name_movie_is_skipped_without_discarding_the_batch(self):
        process_movie_batch(
            self.account,
            [
                {"stream_id": 3001, "name": None, "category_id": "10"},
                {"stream_id": 3002, "name": "   ", "category_id": "10"},
                {"stream_id": 3003, "category_id": "10"},
                {"stream_id": 3005, "name": 12345, "category_id": "10", "tmdb_id": "700999"},
                {"stream_id": 3004, "name": "Good Movie", "category_id": "10", "tmdb_id": "700123"},
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        self.assertTrue(
            Movie.objects.filter(tmdb_id="700123", name="Good Movie").exists()
        )
        self.assertTrue(
            Movie.objects.filter(tmdb_id="700999", name="12345").exists()
        )
        self.assertEqual(Movie.objects.count(), 2)
        self.assertFalse(
            M3UMovieRelation.objects.filter(
                m3u_account=self.account,
                stream_id__in=["3001", "3002", "3003"],
            ).exists()
        )
        self.assertTrue(
            M3UMovieRelation.objects.filter(
                m3u_account=self.account, stream_id="3004"
            ).exists()
        )

    def test_blank_name_series_is_skipped_without_discarding_the_batch(self):
        process_series_batch(
            self.account,
            [
                {"series_id": 4001, "name": None, "category_id": "20"},
                {"series_id": 4002, "name": "   ", "category_id": "20"},
                {"series_id": 4003, "category_id": "20"},
                {"series_id": 4004, "name": "Good Series", "category_id": "20", "tmdb_id": "700456"},
            ],
            self.series_categories,
            self.series_relations,
            scan_start_time=timezone.now(),
        )

        self.assertTrue(
            Series.objects.filter(tmdb_id="700456", name="Good Series").exists()
        )
        self.assertEqual(Series.objects.count(), 1)
        self.assertFalse(
            M3USeriesRelation.objects.filter(
                m3u_account=self.account,
                external_series_id__in=["4001", "4002", "4003"],
            ).exists()
        )
        self.assertTrue(
            M3USeriesRelation.objects.filter(
                m3u_account=self.account, external_series_id="4004"
            ).exists()
        )


class VODDuplicateAcrossCategoriesBatchTests(TestCase):
    """Same canonical movie/series under multiple stream/series IDs in one
    batch must get a relation per ID; identical IDs still coalesce to one.
    Blank Movie/Series fields are filled from later occurrences.
    """

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Multi-Category XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.movie_category_a = VODCategory.objects.create(
            name="Movies A", category_type="movie",
        )
        self.movie_category_b = VODCategory.objects.create(
            name="Movies B", category_type="movie",
        )
        self.series_category_a = VODCategory.objects.create(
            name="Series A", category_type="series",
        )
        self.series_category_b = VODCategory.objects.create(
            name="Series B", category_type="series",
        )
        self.movie_relations = {
            self.movie_category_a.id: M3UVODCategoryRelation.objects.create(
                category=self.movie_category_a, m3u_account=self.account, enabled=True,
            ),
            self.movie_category_b.id: M3UVODCategoryRelation.objects.create(
                category=self.movie_category_b, m3u_account=self.account, enabled=True,
            ),
        }
        self.series_relations = {
            self.series_category_a.id: M3UVODCategoryRelation.objects.create(
                category=self.series_category_a, m3u_account=self.account, enabled=True,
            ),
            self.series_category_b.id: M3UVODCategoryRelation.objects.create(
                category=self.series_category_b, m3u_account=self.account, enabled=True,
            ),
        }
        self.movie_categories = {
            "10": self.movie_category_a,
            "11": self.movie_category_b,
            "__uncategorized__": self.movie_category_a,
        }
        self.series_categories = {
            "20": self.series_category_a,
            "21": self.series_category_b,
            "__uncategorized__": self.series_category_a,
        }

    def test_movie_in_two_categories_creates_a_relation_for_each(self):
        process_movie_batch(
            self.account,
            [
                {"stream_id": 5001, "name": "Shared Movie", "category_id": "10", "tmdb_id": "800001"},
                {"stream_id": 5002, "name": "Shared Movie", "category_id": "11", "tmdb_id": "800001"},
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(Movie.objects.filter(tmdb_id="800001").count(), 1)
        movie = Movie.objects.get(tmdb_id="800001")

        relations = M3UMovieRelation.objects.filter(m3u_account=self.account, movie=movie)
        self.assertEqual(relations.count(), 2)
        by_stream_id = {rel.stream_id: rel for rel in relations}
        self.assertEqual(by_stream_id["5001"].category_id, self.movie_category_a.id)
        self.assertEqual(by_stream_id["5002"].category_id, self.movie_category_b.id)

    def test_clean_title_and_year_merge_id_and_no_id_rows_in_initial_batch(self):
        CoreSettings.set_vod_metadata_settings(
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
            title_rules=["DE -"],
        )

        process_movie_batch(
            self.account,
            [
                {
                    "stream_id": 5011,
                    "name": "DE - Shared Movie (2024)",
                    "category_id": "10",
                },
                {
                    "stream_id": 5012,
                    "name": "Shared Movie (2024)",
                    "category_id": "11",
                    "tmdb_id": "800011",
                },
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        movie = Movie.objects.get(tmdb_id="800011")
        self.assertEqual(movie.clean_title, "Shared Movie")
        self.assertEqual(movie.year, 2024)
        self.assertEqual(
            set(
                M3UMovieRelation.objects.filter(movie=movie).values_list(
                    "stream_id", flat=True
                )
            ),
            {"5011", "5012"},
        )
        self.assertEqual(Movie.objects.count(), 1)

    def test_movie_group_regex_can_remove_year_after_it_is_extracted(self):
        relation = self.movie_relations[self.movie_category_a.id]
        relation.custom_properties = {
            "title_cleanup": {
                "pattern": r"^-\d+-\s*",
            }
        }
        relation.save(update_fields=["custom_properties"])
        CoreSettings.set_vod_metadata_settings(
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
            year_rules=DEFAULT_TITLE_YEAR_RULES,
        )

        process_movie_batch(
            self.account,
            [
                {
                    "stream_id": 5015,
                    "name": "-1- Provider Movie - 2024",
                    "category_id": "10",
                }
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        movie = Movie.objects.get(
            m3u_relations__m3u_account=self.account,
            m3u_relations__stream_id="5015",
        )
        self.assertEqual(movie.clean_title, "Provider Movie")
        self.assertEqual(movie.year, 2024)

    def test_series_group_regex_can_remove_year_after_it_is_extracted(self):
        relation = self.series_relations[self.series_category_a.id]
        relation.custom_properties = {
            "title_cleanup": {
                "pattern": r"^-\d+-\s*",
            }
        }
        relation.save(update_fields=["custom_properties"])
        CoreSettings.set_vod_metadata_settings(
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
            year_rules=DEFAULT_TITLE_YEAR_RULES,
        )

        process_series_batch(
            self.account,
            [
                {
                    "series_id": 6015,
                    "name": "-1- Provider Series - 2024",
                    "category_id": "20",
                }
            ],
            self.series_categories,
            self.series_relations,
            scan_start_time=timezone.now(),
        )

        series = Series.objects.get(
            m3u_relations__m3u_account=self.account,
            m3u_relations__external_series_id="6015",
        )
        self.assertEqual(series.clean_title, "Provider Series")
        self.assertEqual(series.year, 2024)

    def test_conflicting_external_ids_do_not_merge_by_title_and_year(self):
        process_movie_batch(
            self.account,
            [
                {
                    "stream_id": 5013,
                    "name": "Collision (2024)",
                    "category_id": "10",
                    "tmdb_id": "800013",
                },
                {
                    "stream_id": 5014,
                    "name": "Collision (2024)",
                    "category_id": "11",
                    "tmdb_id": "800014",
                },
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(Movie.objects.filter(year=2024).count(), 2)

    def test_duplicate_stream_id_for_same_movie_does_not_create_two_relations(self):
        process_movie_batch(
            self.account,
            [
                {"stream_id": 5003, "name": "Repeated Movie", "category_id": "10", "tmdb_id": "800002"},
                {"stream_id": 5003, "name": "Repeated Movie", "category_id": "10", "tmdb_id": "800002"},
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(
            M3UMovieRelation.objects.filter(m3u_account=self.account, stream_id="5003").count(),
            1,
        )

    def test_provider_tmdb_id_reuses_locked_manually_matched_movie(self):
        target = Movie.objects.create(
            name="Canonical Movie",
            description="Curated movie description",
            tmdb_match_id="800010",
            tmdb_enrichment_signature="processed",
        )

        process_movie_batch(
            self.account,
            [
                {
                    "stream_id": 5010,
                    "name": "Provider Movie",
                    "category_id": "10",
                    "tmdb_id": "800010",
                    "plot": "Provider movie description",
                }
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        relation = M3UMovieRelation.objects.get(
            m3u_account=self.account,
            stream_id="5010",
        )
        target.refresh_from_db()
        self.assertEqual(relation.movie_id, target.id)
        self.assertEqual(Movie.objects.count(), 1)
        self.assertEqual(target.description, "Curated movie description")
        self.assertEqual(target.tmdb_enrichment_signature, "processed")

    def test_series_in_two_categories_creates_a_relation_for_each(self):
        process_series_batch(
            self.account,
            [
                {"series_id": 6001, "name": "Shared Series", "category_id": "20", "tmdb_id": "800101"},
                {"series_id": 6002, "name": "Shared Series", "category_id": "21", "tmdb_id": "800101"},
            ],
            self.series_categories,
            self.series_relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(Series.objects.filter(tmdb_id="800101").count(), 1)
        series = Series.objects.get(tmdb_id="800101")

        relations = M3USeriesRelation.objects.filter(m3u_account=self.account, series=series)
        self.assertEqual(relations.count(), 2)
        by_series_id = {rel.external_series_id: rel for rel in relations}
        self.assertEqual(by_series_id["6001"].category_id, self.series_category_a.id)
        self.assertEqual(by_series_id["6002"].category_id, self.series_category_b.id)

    def test_duplicate_series_id_for_same_series_does_not_create_two_relations(self):
        process_series_batch(
            self.account,
            [
                {"series_id": 6003, "name": "Repeated Series", "category_id": "20", "tmdb_id": "800102"},
                {"series_id": 6003, "name": "Repeated Series", "category_id": "20", "tmdb_id": "800102"},
            ],
            self.series_categories,
            self.series_relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(
            M3USeriesRelation.objects.filter(
                m3u_account=self.account, external_series_id="6003"
            ).count(),
            1,
        )

    def test_provider_tmdb_id_reuses_locked_manually_matched_series(self):
        target = Series.objects.create(
            name="Canonical Series",
            description="Curated series description",
            tmdb_match_id="800110",
            tmdb_enrichment_signature="processed",
        )

        process_series_batch(
            self.account,
            [
                {
                    "series_id": 6010,
                    "name": "Provider Series",
                    "category_id": "20",
                    "tmdb_id": "800110",
                    "plot": "Provider series description",
                }
            ],
            self.series_categories,
            self.series_relations,
            scan_start_time=timezone.now(),
        )

        relation = M3USeriesRelation.objects.get(
            m3u_account=self.account,
            external_series_id="6010",
        )
        target.refresh_from_db()
        self.assertEqual(relation.series_id, target.id)
        self.assertEqual(Series.objects.count(), 1)
        self.assertEqual(target.description, "Curated series description")
        self.assertEqual(target.tmdb_enrichment_signature, "processed")

    def test_later_movie_occurrence_fills_blank_description(self):
        process_movie_batch(
            self.account,
            [
                {"stream_id": 5004, "name": "Sparse First", "category_id": "10", "tmdb_id": "800003"},
                {
                    "stream_id": 5005,
                    "name": "Sparse First",
                    "category_id": "11",
                    "tmdb_id": "800003",
                    "description": "Full plot from second category",
                },
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        movie = Movie.objects.get(tmdb_id="800003")
        self.assertEqual(movie.description, "Full plot from second category")
        self.assertEqual(
            M3UMovieRelation.objects.filter(m3u_account=self.account, movie=movie).count(),
            2,
        )

    def test_later_movie_occurrence_does_not_overwrite_existing_description(self):
        process_movie_batch(
            self.account,
            [
                {
                    "stream_id": 5006,
                    "name": "Described First",
                    "category_id": "10",
                    "tmdb_id": "800004",
                    "description": "Keep this",
                },
                {
                    "stream_id": 5007,
                    "name": "Described First",
                    "category_id": "11",
                    "tmdb_id": "800004",
                    "description": "Ignore this",
                },
            ],
            self.movie_categories,
            self.movie_relations,
            scan_start_time=timezone.now(),
        )

        movie = Movie.objects.get(tmdb_id="800004")
        self.assertEqual(movie.description, "Keep this")

    def test_later_series_occurrence_fills_blank_description(self):
        process_series_batch(
            self.account,
            [
                {"series_id": 6004, "name": "Sparse Series", "category_id": "20", "tmdb_id": "800103"},
                {
                    "series_id": 6005,
                    "name": "Sparse Series",
                    "category_id": "21",
                    "tmdb_id": "800103",
                    "plot": "Series plot from second category",
                },
            ],
            self.series_categories,
            self.series_relations,
            scan_start_time=timezone.now(),
        )

        series = Series.objects.get(tmdb_id="800103")
        self.assertEqual(series.description, "Series plot from second category")
        self.assertEqual(
            M3USeriesRelation.objects.filter(m3u_account=self.account, series=series).count(),
            2,
        )
