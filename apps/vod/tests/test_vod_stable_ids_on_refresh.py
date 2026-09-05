"""Regression tests for issue #961: VOD movie/series IDs must stay stable
across M3U refreshes.

Root cause reproduced: when a provider does NOT supply a stable TMDB/IMDB id
in its list payload, process_movie_batch / process_series_batch used to
re-point an existing M3UMovieRelation to a freshly built Movie object on every
refresh, creating duplicate Movie rows (new auto-increment IDs) and breaking
any consumer keyed on Movie.id (STRM URLs, tmdb group keys, etc).

These tests assert the stable behaviour: an existing relation keeps its linked
movie/series across refreshes, no duplicate rows are created, and -- when the
provider finally supplies an external id -- it is back-filled onto the stable
record rather than forcing a new one.
"""

from django.test import TestCase
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
from apps.vod.tasks import process_movie_batch, process_series_batch


class VODStableIdsOnRefreshTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Dirty XC",
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

    def _movie_row(self, **overrides):
        row = {
            "stream_id": 5001,
            "name": "No ID Film",
            "category_id": "10",
            "container_extension": "mp4",
        }
        row.update(overrides)
        return row

    def test_refresh_without_tmdb_does_not_create_duplicate_movie(self):
        """A provider that never sends tmdb_id must not spawn new Movie rows
        on every refresh -- the relation stays linked to the original movie."""
        # Initial import (no tmdb_id).
        process_movie_batch(
            self.account,
            [self._movie_row()],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )
        movie = Movie.objects.get(name="No ID Film")
        relation = M3UMovieRelation.objects.get(
            m3u_account=self.account, stream_id="5001"
        )
        original_movie_id = movie.id
        self.assertEqual(relation.movie_id, original_movie_id)

        # Refresh with the SAME stream_id but still no tmdb_id.
        process_movie_batch(
            self.account,
            [self._movie_row()],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

        # Exactly one Movie row, same id, same relation link.
        self.assertEqual(Movie.objects.filter(name="No ID Film").count(), 1)
        relation.refresh_from_db()
        self.assertEqual(relation.movie_id, original_movie_id)

    def test_refresh_backfills_tmdb_onto_stable_movie(self):
        """When the provider later supplies a tmdb_id, back-fill it onto the
        existing (stable) movie instead of creating a new row."""
        process_movie_batch(
            self.account,
            [self._movie_row()],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )
        original_movie_id = Movie.objects.get(name="No ID Film").id

        # Refresh now carrying a tmdb_id.
        process_movie_batch(
            self.account,
            [self._movie_row(tmdb_id="123456")],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

        # Still a single movie, same id, tmdb_id populated, relation stable.
        self.assertEqual(Movie.objects.filter(name="No ID Film").count(), 1)
        movie = Movie.objects.get(name="No ID Film")
        self.assertEqual(movie.id, original_movie_id)
        self.assertEqual(movie.tmdb_id, "123456")
        relation = M3UMovieRelation.objects.get(
            m3u_account=self.account, stream_id="5001"
        )
        self.assertEqual(relation.movie_id, original_movie_id)


class VODStableSeriesIdsOnRefreshTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Dirty XC Series",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category = VODCategory.objects.create(
            name="Series",
            category_type="series",
        )
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category,
            m3u_account=self.account,
            enabled=True,
        )
        self.categories = {
            "20": self.category,
            "__uncategorized__": self.category,
        }
        self.relations = {self.category.id: self.cat_relation}

    def test_refresh_without_tmdb_does_not_create_duplicate_series(self):
        process_series_batch(
            self.account,
            [{
                "series_id": 6001,
                "name": "No ID Show",
                "category_id": "20",
                "cover": "http://example.com/cover.jpg",
            }],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )
        series = Series.objects.get(name="No ID Show")
        relation = M3USeriesRelation.objects.get(
            m3u_account=self.account, external_series_id="6001"
        )
        original_id = series.id
        self.assertEqual(relation.series_id, original_id)

        # Refresh, same series_id, still no tmdb.
        process_series_batch(
            self.account,
            [{
                "series_id": 6001,
                "name": "No ID Show",
                "category_id": "20",
                "cover": "http://example.com/cover.jpg",
            }],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

        self.assertEqual(Series.objects.filter(name="No ID Show").count(), 1)
        relation.refresh_from_db()
        self.assertEqual(relation.series_id, original_id)
