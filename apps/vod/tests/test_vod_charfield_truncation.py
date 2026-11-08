"""Oversized provider name/genre must not abort VOD list-sync batches."""

from django.test import TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
)
from apps.vod.tasks import process_movie_batch, process_series_batch


class MovieCharFieldTruncationTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='Long genre movie provider',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.category = VODCategory.objects.create(
            name='Long Genre Movies',
            category_type='movie',
        )
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category,
            m3u_account=self.account,
            enabled=True,
        )
        self.categories = {
            '10': self.category,
            '__uncategorized__': self.category,
        }
        self.relations = {self.category.id: self.cat_relation}
        self.genre_max = Movie._meta.get_field('genre').max_length
        self.name_max = Movie._meta.get_field('name').max_length

    def _row(self, stream_id, name, **overrides):
        row = {
            'stream_id': stream_id,
            'name': name,
            'category_id': '10',
            'container_extension': 'mp4',
        }
        row.update(overrides)
        return row

    def _process(self, rows):
        process_movie_batch(
            self.account,
            rows,
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

    def test_long_genre_does_not_abort_movie_batch(self):
        # One over-long genre used to raise DataError inside transaction.atomic
        # and roll back the entire 1,000-movie chunk.
        long_genre = 'G' * (self.genre_max + 100)
        self._process([
            self._row(2001, 'Long Genre Film', genre=long_genre, tmdb_id='92001'),
            self._row(2002, 'Short Genre Film', genre='Action', tmdb_id='92002'),
        ])

        long_movie = Movie.objects.get(tmdb_id='92001')
        short_movie = Movie.objects.get(tmdb_id='92002')
        self.assertEqual(len(long_movie.genre), self.genre_max)
        self.assertEqual(long_movie.genre, long_genre[:self.genre_max])
        self.assertEqual(short_movie.genre, 'Action')
        self.assertEqual(
            M3UMovieRelation.objects.filter(m3u_account=self.account).count(),
            2,
        )

    def test_long_category_name_fallback_genre_is_truncated(self):
        long_category = 'C' * (self.genre_max + 50)
        self._process([
            self._row(2003, 'Category Genre Film', category_name=long_category),
        ])
        movie = Movie.objects.get(name='Category Genre Film')
        self.assertEqual(movie.genre, long_category[:self.genre_max])

    def test_long_name_does_not_abort_movie_batch(self):
        long_name = 'N' * (self.name_max + 80)
        self._process([
            self._row(2004, long_name, tmdb_id='92004'),
            self._row(2005, 'Neighbor Film', tmdb_id='92005'),
        ])
        long_movie = Movie.objects.get(tmdb_id='92004')
        self.assertEqual(long_movie.name, long_name[:self.name_max])
        self.assertTrue(Movie.objects.filter(tmdb_id='92005').exists())
        self.assertEqual(
            M3UMovieRelation.objects.filter(m3u_account=self.account).count(),
            2,
        )

    def test_bulk_create_and_save_clamp_name_and_genre(self):
        long_name = 'M' * (self.name_max + 10)
        long_genre = 'X' * (self.genre_max + 10)
        Movie.objects.bulk_create([
            Movie(name=long_name, genre=long_genre, tmdb_id='93001'),
        ])
        movie = Movie.objects.get(tmdb_id='93001')
        self.assertEqual(movie.name, long_name[:self.name_max])
        self.assertEqual(movie.genre, long_genre[:self.genre_max])

        movie.genre = 'Y' * (self.genre_max + 20)
        movie.save()
        movie.refresh_from_db()
        self.assertEqual(len(movie.genre), self.genre_max)


class SeriesCharFieldTruncationTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='Long genre series provider',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.category = VODCategory.objects.create(
            name='Long Genre Series',
            category_type='series',
        )
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category,
            m3u_account=self.account,
            enabled=True,
        )
        self.categories = {
            '20': self.category,
            '__uncategorized__': self.category,
        }
        self.relations = {self.category.id: self.cat_relation}
        self.genre_max = Series._meta.get_field('genre').max_length
        self.name_max = Series._meta.get_field('name').max_length

    def _row(self, series_id, name, **overrides):
        row = {
            'series_id': series_id,
            'name': name,
            'category_id': '20',
        }
        row.update(overrides)
        return row

    def _process(self, rows):
        process_series_batch(
            self.account,
            rows,
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

    def test_long_genre_does_not_abort_series_batch(self):
        long_genre = 'S' * (self.genre_max + 100)
        self._process([
            self._row(3001, 'Long Genre Show', genre=long_genre, tmdb='83001'),
            self._row(3002, 'Short Genre Show', genre='Drama', tmdb='83002'),
        ])

        long_series = Series.objects.get(tmdb_id='83001')
        short_series = Series.objects.get(tmdb_id='83002')
        self.assertEqual(long_series.genre, long_genre[:self.genre_max])
        self.assertEqual(short_series.genre, 'Drama')
        self.assertEqual(
            M3USeriesRelation.objects.filter(m3u_account=self.account).count(),
            2,
        )

    def test_long_name_does_not_abort_series_batch(self):
        long_name = 'T' * (self.name_max + 80)
        self._process([
            self._row(3003, long_name, tmdb='83003'),
            self._row(3004, 'Neighbor Show', tmdb='83004'),
        ])
        long_series = Series.objects.get(tmdb_id='83003')
        self.assertEqual(long_series.name, long_name[:self.name_max])
        self.assertTrue(Series.objects.filter(tmdb_id='83004').exists())
