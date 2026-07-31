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
    should_apply_provider_list_field,
)


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
    def test_refresh_skips_when_detailed_fetched_and_recent(self, mock_client_cls):
        result = refresh_movie_advanced_data(self.relation.id, force_refresh=False)

        self.assertEqual(result, "Advanced data recently fetched, skipping.")
        mock_client_cls.assert_not_called()

    @patch("core.xtream_codes.Client")
    def test_refresh_runs_after_age_window(self, mock_client_cls):
        self.relation.last_advanced_refresh = timezone.now() - timedelta(hours=25)
        self.relation.save(update_fields=["last_advanced_refresh"])

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            "info": {"plot": "Refreshed after window."},
            "movie_data": {},
        }

        result = refresh_movie_advanced_data(self.relation.id, force_refresh=False)

        self.assertEqual(result, "Advanced data refreshed.")
        mock_client.get_vod_info.assert_called_once()


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
