from django.test import TestCase
from django.utils import timezone
from unittest.mock import MagicMock

from apps.m3u.models import M3UAccount
from apps.vod.models import Movie, Series, M3UMovieRelation, M3USeriesRelation, VODCategory
from apps.vod.tasks import process_movie_batch, process_series_batch, _names_are_similar


def make_account(name="Test Account"):
    return M3UAccount.objects.create(
        name=name,
        account_type=M3UAccount.Types.XC,
        server_url="http://example.com",
        username="user",
        password="pass",
    )


def make_category(name="Action", provider_cat_id="1"):
    cat = VODCategory.objects.create(name=name)
    return provider_cat_id, cat


class NamesAreSimilarTests(TestCase):
    """Unit tests for the name-similarity guard helper."""

    def test_identical_names(self):
        self.assertTrue(_names_are_similar("Inception", "Inception"))

    def test_case_insensitive(self):
        self.assertTrue(_names_are_similar("inception", "INCEPTION"))

    def test_punctuation_differences(self):
        self.assertTrue(_names_are_similar("Spider-Man: No Way Home", "Spider Man No Way Home"))

    def test_year_suffix_ignored(self):
        self.assertTrue(_names_are_similar("The Batman", "The Batman (2022)"))

    def test_completely_different_names(self):
        self.assertFalse(_names_are_similar("Inception", "The Dark Knight"))

    def test_empty_names_return_true(self):
        # Cannot compare empty; give benefit of the doubt
        self.assertTrue(_names_are_similar("", "Inception"))
        self.assertTrue(_names_are_similar("Inception", ""))


class ProcessMovieBatchStableIDTests(TestCase):
    """
    Regression tests for issue #961: movie IDs must not change on M3U refresh.

    Root cause: when a movie has no TMDB/IMDB on first import (common with XC
    providers) the record is keyed by name+year.  On the next refresh, if the
    provider now returns a TMDB ID, the key becomes tmdb_<id> — no match is
    found, a duplicate Movie is created, and the relation is repointed to it,
    breaking STRM files and XC-compatible URLs that rely on the original ID.
    """

    def setUp(self):
        self.account = make_account()
        provider_cat_id, self.category = make_category()
        self.categories = {
            provider_cat_id: self.category,
            '__uncategorized__': VODCategory.objects.create(name='Uncategorized'),
        }
        self.category_relations = {}  # No disabled categories
        self.scan_time = timezone.now()

    def _batch(self, stream_id, name, tmdb_id=None, imdb_id=None, year=None):
        return [{
            'stream_id': stream_id,
            'name': name,
            'category_id': '1',
            'tmdb_id': tmdb_id or '0',
            'imdb_id': imdb_id or '',
            'year': year,
            'container_extension': 'mp4',
        }]

    def test_movie_id_stable_when_tmdb_appears_on_refresh(self):
        """Core regression: the same movie DB row is used after TMDB ID appears."""
        # First import: no TMDB ID
        process_movie_batch(
            self.account,
            self._batch('101', 'Inception', year=2010),
            self.categories,
            self.category_relations,
            scan_start_time=self.scan_time,
        )

        self.assertEqual(Movie.objects.count(), 1)
        original_movie_id = Movie.objects.first().pk
        original_relation_id = M3UMovieRelation.objects.first().pk

        # Second import: provider now supplies a TMDB ID
        process_movie_batch(
            self.account,
            self._batch('101', 'Inception', tmdb_id='27205', year=2010),
            self.categories,
            self.category_relations,
            scan_start_time=self.scan_time,
        )

        # Still exactly one movie; no duplicate created
        self.assertEqual(Movie.objects.count(), 1)

        movie = Movie.objects.first()
        self.assertEqual(movie.pk, original_movie_id, "Movie primary key must not change")
        self.assertEqual(movie.tmdb_id, '27205', "TMDB ID should be filled in")

        relation = M3UMovieRelation.objects.first()
        self.assertEqual(relation.pk, original_relation_id, "Relation primary key must not change")
        self.assertEqual(relation.movie_id, original_movie_id, "Relation must still point to original movie")

    def test_no_duplicate_movie_created_on_second_refresh(self):
        """Repeated refreshes with TMDB present must not accumulate duplicates."""
        process_movie_batch(
            self.account,
            self._batch('101', 'Inception', tmdb_id='27205', year=2010),
            self.categories,
            self.category_relations,
            scan_start_time=self.scan_time,
        )
        process_movie_batch(
            self.account,
            self._batch('101', 'Inception', tmdb_id='27205', year=2010),
            self.categories,
            self.category_relations,
            scan_start_time=self.scan_time,
        )

        self.assertEqual(Movie.objects.count(), 1)
        self.assertEqual(M3UMovieRelation.objects.count(), 1)

    def test_existing_tmdb_not_overwritten(self):
        """A TMDB ID already on the record must not be replaced by new provider data."""
        process_movie_batch(
            self.account,
            self._batch('101', 'Inception', tmdb_id='27205', year=2010),
            self.categories,
            self.category_relations,
        )
        # Provider sends a different (wrong) TMDB ID on next refresh
        process_movie_batch(
            self.account,
            self._batch('101', 'Inception', tmdb_id='99999', year=2010),
            self.categories,
            self.category_relations,
        )

        movie = Movie.objects.get(name='Inception')
        self.assertEqual(movie.tmdb_id, '27205', "Existing TMDB ID must not be overwritten")

    def test_recycled_stream_id_creates_new_movie(self):
        """When a provider reuses a stream_id for different content a new movie must be created."""
        process_movie_batch(
            self.account,
            self._batch('101', 'Inception', year=2010),
            self.categories,
            self.category_relations,
        )
        original_movie_id = Movie.objects.first().pk

        # Provider recycles stream 101 for a completely different title
        process_movie_batch(
            self.account,
            self._batch('101', 'The Dark Knight', year=2008),
            self.categories,
            self.category_relations,
        )

        self.assertEqual(Movie.objects.count(), 2, "A new movie record must be created for the recycled stream")
        new_movie = Movie.objects.exclude(pk=original_movie_id).first()
        self.assertEqual(new_movie.name, 'The Dark Knight')

        # Relation is updated to point to the new movie
        relation = M3UMovieRelation.objects.get(stream_id='101', m3u_account=self.account)
        self.assertEqual(relation.movie_id, new_movie.pk)

    def test_new_stream_creates_new_movie(self):
        """A stream_id that has never been seen before creates a new movie and relation."""
        process_movie_batch(
            self.account,
            self._batch('999', 'Brand New Film', year=2024),
            self.categories,
            self.category_relations,
        )

        self.assertEqual(Movie.objects.count(), 1)
        self.assertEqual(Movie.objects.first().name, 'Brand New Film')
        self.assertEqual(M3UMovieRelation.objects.count(), 1)


class ProcessSeriesBatchStableIDTests(TestCase):
    """Parallel stability guarantees for TV series."""

    def setUp(self):
        self.account = make_account("Series Account")
        provider_cat_id, self.category = make_category("Drama", "2")
        self.categories = {
            provider_cat_id: self.category,
            '__uncategorized__': VODCategory.objects.create(name='Uncategorized'),
        }
        self.category_relations = {}
        self.scan_time = timezone.now()

    def _batch(self, series_id, name, tmdb_id=None, imdb_id=None, year=None):
        return [{
            'series_id': series_id,
            'name': name,
            'category_id': '2',
            'tmdb': tmdb_id or '0',
            'imdb': imdb_id or '',
            'releaseDate': f'{year}-01-01' if year else '',
        }]

    def test_series_id_stable_when_tmdb_appears_on_refresh(self):
        """Core regression: series DB row is preserved after TMDB ID appears."""
        process_series_batch(
            self.account,
            self._batch('201', 'Breaking Bad', year=2008),
            self.categories,
            self.category_relations,
            scan_start_time=self.scan_time,
        )

        self.assertEqual(Series.objects.count(), 1)
        original_series_id = Series.objects.first().pk

        process_series_batch(
            self.account,
            self._batch('201', 'Breaking Bad', tmdb_id='1396', year=2008),
            self.categories,
            self.category_relations,
            scan_start_time=self.scan_time,
        )

        self.assertEqual(Series.objects.count(), 1)
        series = Series.objects.first()
        self.assertEqual(series.pk, original_series_id, "Series primary key must not change")
        self.assertEqual(series.tmdb_id, '1396', "TMDB ID should be filled in")

        relation = M3USeriesRelation.objects.first()
        self.assertEqual(relation.series_id, original_series_id, "Relation must still point to original series")

    def test_recycled_series_id_creates_new_series(self):
        """When a provider reuses a series_id for different content a new series must be created."""
        process_series_batch(
            self.account,
            self._batch('201', 'Breaking Bad', year=2008),
            self.categories,
            self.category_relations,
        )
        original_series_pk = Series.objects.first().pk

        process_series_batch(
            self.account,
            self._batch('201', 'Better Call Saul', year=2015),
            self.categories,
            self.category_relations,
        )

        self.assertEqual(Series.objects.count(), 2)
        new_series = Series.objects.exclude(pk=original_series_pk).first()
        self.assertEqual(new_series.name, 'Better Call Saul')

        relation = M3USeriesRelation.objects.get(external_series_id='201', m3u_account=self.account)
        self.assertEqual(relation.series_id, new_series.pk)

    def test_no_duplicate_series_on_repeated_refresh(self):
        """Repeated refreshes with the same data must not accumulate duplicates."""
        for _ in range(3):
            process_series_batch(
                self.account,
                self._batch('201', 'Breaking Bad', tmdb_id='1396', year=2008),
                self.categories,
                self.category_relations,
                scan_start_time=self.scan_time,
            )

        self.assertEqual(Series.objects.count(), 1)
        self.assertEqual(M3USeriesRelation.objects.count(), 1)
