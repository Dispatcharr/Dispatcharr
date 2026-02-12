from django.test import TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Movie, Series, VODCategory, M3UMovieRelation, M3USeriesRelation,
)
from apps.vod.tasks import process_movie_batch, process_series_batch


class ProcessMovieBatchStableIDTests(TestCase):
    """
    Tests for issue #961: VOD movie IDs must remain stable across M3U refreshes.

    When process_movie_batch runs on a refresh, it must NOT create duplicate
    movies and repoint existing relations — this breaks STRM files and
    XC-compat URLs that reference the original movie ID.
    """

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Test XC Account",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type="XC",
        )
        self.category = VODCategory.objects.create(
            name="Action", category_type="movie"
        )
        # categories dict keyed by provider category ID (string)
        self.categories = {"1": self.category}
        # relations dict (category_id -> M3UVODCategoryRelation) — empty = all enabled
        self.relations = {}

    def _make_movie_data(self, stream_id, name, year=2024, tmdb=None, imdb=None):
        """Helper to build a movie_data dict as the XC provider would return."""
        data = {
            "stream_id": stream_id,
            "name": name,
            "category_id": "1",
            "container_extension": "mkv",
        }
        if tmdb is not None:
            data["tmdb"] = tmdb
        if imdb is not None:
            data["imdb"] = imdb
        return data

    # ------------------------------------------------------------------
    # Core regression test for #961
    # ------------------------------------------------------------------
    def test_existing_relation_preserves_movie_id_when_tmdb_appears(self):
        """
        Scenario from #961:
        1. Initial import: movie created WITHOUT tmdb_id, relation points to it.
        2. Refresh: provider now includes tmdb ID for the same stream_id.
        3. Expected: relation still points to the SAME movie (ID unchanged),
           and the movie's tmdb_id is filled in.
        """
        # --- Step 1: Initial import (no TMDB ID) ---
        batch_initial = [self._make_movie_data("100", "Cool Movie", tmdb=None)]
        process_movie_batch(
            self.account, batch_initial, self.categories, self.relations
        )

        self.assertEqual(Movie.objects.count(), 1)
        self.assertEqual(M3UMovieRelation.objects.count(), 1)

        original_movie = Movie.objects.first()
        original_movie_id = original_movie.id
        self.assertIsNone(original_movie.tmdb_id)

        relation = M3UMovieRelation.objects.first()
        self.assertEqual(relation.movie_id, original_movie_id)

        # --- Step 2: Refresh — same stream_id, now with TMDB ID ---
        batch_refresh = [self._make_movie_data("100", "Cool Movie", tmdb="625568")]
        process_movie_batch(
            self.account, batch_refresh, self.categories, self.relations
        )

        # --- Assertions ---
        # No duplicate movie should be created
        self.assertEqual(Movie.objects.count(), 1,
                         "Refresh must NOT create a duplicate movie")

        # Relation must still point to the original movie
        relation.refresh_from_db()
        self.assertEqual(relation.movie_id, original_movie_id,
                         "Relation must NOT be repointed to a different movie")

        # TMDB ID should now be filled in on the original movie
        original_movie.refresh_from_db()
        self.assertEqual(original_movie.tmdb_id, "625568",
                         "TMDB ID should be filled in on existing movie")

    def test_existing_relation_preserves_movie_id_when_imdb_appears(self):
        """Same as above but for IMDB IDs."""
        batch_initial = [self._make_movie_data("200", "Another Movie")]
        process_movie_batch(
            self.account, batch_initial, self.categories, self.relations
        )

        original_movie_id = Movie.objects.first().id

        batch_refresh = [self._make_movie_data("200", "Another Movie", imdb="tt1234567")]
        process_movie_batch(
            self.account, batch_refresh, self.categories, self.relations
        )

        self.assertEqual(Movie.objects.count(), 1)
        relation = M3UMovieRelation.objects.first()
        self.assertEqual(relation.movie_id, original_movie_id)

        movie = Movie.objects.first()
        self.assertEqual(movie.imdb_id, "tt1234567")

    def test_existing_tmdb_id_not_overwritten(self):
        """
        If a movie already has a tmdb_id and the provider sends a different
        value on refresh, the existing tmdb_id must NOT be overwritten.
        """
        batch_initial = [self._make_movie_data("300", "Third Movie", tmdb="111")]
        process_movie_batch(
            self.account, batch_initial, self.categories, self.relations
        )

        movie = Movie.objects.first()
        self.assertEqual(movie.tmdb_id, "111")

        # Refresh with a different TMDB ID (shouldn't overwrite)
        batch_refresh = [self._make_movie_data("300", "Third Movie", tmdb="222")]
        process_movie_batch(
            self.account, batch_refresh, self.categories, self.relations
        )

        movie.refresh_from_db()
        self.assertEqual(movie.tmdb_id, "111",
                         "Existing TMDB ID must not be overwritten on refresh")

    def test_genuinely_new_stream_creates_new_movie(self):
        """A stream_id not seen before should still create a new movie."""
        batch1 = [self._make_movie_data("400", "Existing Movie")]
        process_movie_batch(
            self.account, batch1, self.categories, self.relations
        )
        self.assertEqual(Movie.objects.count(), 1)

        batch2 = [self._make_movie_data("401", "Brand New Movie", tmdb="999")]
        process_movie_batch(
            self.account, batch2, self.categories, self.relations
        )
        self.assertEqual(Movie.objects.count(), 2,
                         "A genuinely new stream should create a new movie")
        self.assertEqual(M3UMovieRelation.objects.count(), 2)

    def test_metadata_updated_on_refresh(self):
        """Non-ID metadata (description, genre, etc.) should still be updated."""
        batch_initial = [self._make_movie_data("500", "Meta Movie")]
        batch_initial[0]["description"] = "Old description"
        batch_initial[0]["genre"] = "Action"
        process_movie_batch(
            self.account, batch_initial, self.categories, self.relations
        )

        batch_refresh = [self._make_movie_data("500", "Meta Movie")]
        batch_refresh[0]["description"] = "New description"
        batch_refresh[0]["genre"] = "Comedy"
        process_movie_batch(
            self.account, batch_refresh, self.categories, self.relations
        )

        movie = Movie.objects.first()
        self.assertEqual(movie.description, "New description")
        self.assertEqual(movie.genre, "Comedy")

    def test_multiple_movies_stable_across_refresh(self):
        """Multiple movies with different stream_ids all remain stable."""
        batch_initial = [
            self._make_movie_data("600", "Movie A"),
            self._make_movie_data("601", "Movie B"),
            self._make_movie_data("602", "Movie C"),
        ]
        process_movie_batch(
            self.account, batch_initial, self.categories, self.relations
        )

        original_ids = {
            rel.stream_id: rel.movie_id
            for rel in M3UMovieRelation.objects.all()
        }
        self.assertEqual(len(original_ids), 3)

        # Refresh — now all have TMDB IDs
        batch_refresh = [
            self._make_movie_data("600", "Movie A", tmdb="10"),
            self._make_movie_data("601", "Movie B", tmdb="20"),
            self._make_movie_data("602", "Movie C", tmdb="30"),
        ]
        process_movie_batch(
            self.account, batch_refresh, self.categories, self.relations
        )

        self.assertEqual(Movie.objects.count(), 3,
                         "No duplicate movies should be created")

        for rel in M3UMovieRelation.objects.all():
            self.assertEqual(rel.movie_id, original_ids[rel.stream_id],
                             f"stream_id={rel.stream_id} must keep its original movie_id")


class ProcessSeriesBatchStableIDTests(TestCase):
    """Same tests as above but for series, since the fix applies to both."""

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Test XC Account Series",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type="XC",
        )
        self.category = VODCategory.objects.create(
            name="Drama", category_type="series"
        )
        self.categories = {"1": self.category}
        self.relations = {}

    def _make_series_data(self, series_id, name, year=2024, tmdb=None, imdb=None):
        data = {
            "series_id": series_id,
            "name": name,
            "category_id": "1",
        }
        if tmdb is not None:
            data["tmdb"] = tmdb
        if imdb is not None:
            data["imdb"] = imdb
        return data

    def test_existing_relation_preserves_series_id_when_tmdb_appears(self):
        """Series version of the core #961 regression test."""
        batch_initial = [self._make_series_data("S100", "Cool Series")]
        process_series_batch(
            self.account, batch_initial, self.categories, self.relations
        )

        self.assertEqual(Series.objects.count(), 1)
        original_series_id = Series.objects.first().id
        relation = M3USeriesRelation.objects.first()
        self.assertEqual(relation.series_id, original_series_id)

        batch_refresh = [self._make_series_data("S100", "Cool Series", tmdb="99999")]
        process_series_batch(
            self.account, batch_refresh, self.categories, self.relations
        )

        self.assertEqual(Series.objects.count(), 1,
                         "Refresh must NOT create a duplicate series")
        relation.refresh_from_db()
        self.assertEqual(relation.series_id, original_series_id,
                         "Relation must NOT be repointed to a different series")

        series = Series.objects.first()
        self.assertEqual(series.tmdb_id, "99999")

    def test_genuinely_new_series_creates_new_record(self):
        batch1 = [self._make_series_data("S200", "Existing Show")]
        process_series_batch(
            self.account, batch1, self.categories, self.relations
        )

        batch2 = [self._make_series_data("S201", "New Show", tmdb="888")]
        process_series_batch(
            self.account, batch2, self.categories, self.relations
        )

        self.assertEqual(Series.objects.count(), 2)
        self.assertEqual(M3USeriesRelation.objects.count(), 2)
