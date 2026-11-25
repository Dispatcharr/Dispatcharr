"""Bad provider movie durations must not abort list sync or wipe good values."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    M3UMovieRelation,
    Movie,
    M3UVODCategoryRelation,
    VODCategory,
)
from apps.vod.tasks import (
    MAX_DURATION_SECS,
    extract_duration_from_data,
    process_movie_batch,
    refresh_movie_advanced_data,
)


class ExtractDurationFromDataTests(SimpleTestCase):
    def test_duration_secs_and_parsed_duration_are_normalized(self):
        self.assertEqual(extract_duration_from_data({'duration_secs': 5400}), 5400)
        self.assertEqual(extract_duration_from_data({'duration_secs': '5400'}), 5400)
        self.assertEqual(extract_duration_from_data({'duration': '90'}), 5400)
        self.assertEqual(extract_duration_from_data({'duration': '01:30:00'}), 5400)
        self.assertEqual(extract_duration_from_data({'duration': '90:00'}), 5400)
        self.assertEqual(
            extract_duration_from_data({'duration_secs': MAX_DURATION_SECS}),
            MAX_DURATION_SECS,
        )

    def test_invalid_duration_secs_falls_back_to_duration(self):
        self.assertEqual(
            extract_duration_from_data({'duration_secs': 'unknown', 'duration': '01:30:00'}),
            5400,
        )
        self.assertEqual(
            extract_duration_from_data({'duration_secs': 2605442460, 'duration': '90'}),
            5400,
        )
        self.assertEqual(
            extract_duration_from_data({'duration_secs': 0, 'duration': '90'}),
            5400,
        )

    def test_invalid_durations_become_none(self):
        for value in (
            2605442460,
            '2605442460',
            MAX_DURATION_SECS + 1,
            -1,
            0,
            '0',
            'unknown',
            1.5,
            True,
            '',
            None,
        ):
            self.assertIsNone(extract_duration_from_data({'duration_secs': value}))

        # A bare duration is minutes, so one minute past the cap is rejected.
        over_cap_minutes = (MAX_DURATION_SECS // 60) + 1
        self.assertIsNone(extract_duration_from_data({'duration': str(over_cap_minutes)}))
        self.assertIsNone(extract_duration_from_data({}))
        # isdigit() accepts characters and lengths that int() rejects.
        self.assertIsNone(extract_duration_from_data({'duration': '²'}))
        self.assertIsNone(extract_duration_from_data({'duration': '9' * 5000}))


class MovieDurationSyncTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='Duration movie provider',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.category = VODCategory.objects.create(
            name='Duration Movies',
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

    def _row(self, stream_id, name, duration_secs=None, **overrides):
        row = {
            'stream_id': stream_id,
            'name': name,
            'category_id': '10',
            'container_extension': 'mp4',
        }
        if duration_secs is not None:
            row['duration_secs'] = duration_secs
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

    def test_invalid_durations_do_not_abort_bulk_create(self):
        self._process([
            self._row(1001, 'Junk Duration Film', 2605442460),
            self._row(1002, 'Good Duration Film', 5400),
            self._row(1003, 'Over Cap Film', MAX_DURATION_SECS + 1),
        ])

        movies = {
            movie.name: movie.duration_secs
            for movie in Movie.objects.filter(
                name__in=['Junk Duration Film', 'Good Duration Film', 'Over Cap Film']
            )
        }
        self.assertEqual(movies['Junk Duration Film'], None)
        self.assertEqual(movies['Good Duration Film'], 5400)
        self.assertEqual(movies['Over Cap Film'], None)
        self.assertEqual(
            M3UMovieRelation.objects.filter(m3u_account=self.account).count(),
            3,
        )

    def test_invalid_duration_does_not_wipe_existing_value_on_list_sync(self):
        self._process([self._row(1001, 'Keep Duration Film', 5400, tmdb_id='900101')])
        movie = Movie.objects.get(tmdb_id='900101')
        self.assertEqual(movie.duration_secs, 5400)

        self._process([
            self._row(1001, 'Keep Duration Film', 2605442460, tmdb_id='900101'),
        ])

        movie.refresh_from_db()
        self.assertEqual(movie.duration_secs, 5400)

    def test_list_sync_still_applies_valid_duration_updates(self):
        self._process([self._row(1001, 'Update Duration Film', 5400, tmdb_id='900102')])
        self._process([self._row(1001, 'Update Duration Film', 7200, tmdb_id='900102')])

        movie = Movie.objects.get(tmdb_id='900102')
        self.assertEqual(movie.duration_secs, 7200)


class MovieAdvancedDurationRefreshTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='Duration advanced provider',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.category = VODCategory.objects.create(
            name='Advanced Duration Movies',
            category_type='movie',
        )
        M3UVODCategoryRelation.objects.create(
            category=self.category,
            m3u_account=self.account,
            enabled=True,
        )
        self.movie = Movie.objects.create(
            name='Advanced Duration Film',
            year=2024,
            tmdb_id='900201',
            duration_secs=5400,
        )
        self.relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            category=self.category,
            stream_id='2001',
            container_extension='mkv',
            custom_properties={
                'basic_data': {'stream_id': 2001, 'name': self.movie.name},
                'detailed_fetched': False,
            },
        )

    @patch('core.xtream_codes.Client')
    def test_invalid_advanced_duration_keeps_existing_value(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            'info': {
                'plot': 'Provider plot.',
                'duration_secs': '2605442460',
            },
            'movie_data': {'stream_id': 2001, 'name': self.movie.name},
        }

        result = refresh_movie_advanced_data(self.relation.id, force_refresh=True)

        self.assertEqual(result, 'Advanced data refreshed.')
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.duration_secs, 5400)
        self.assertEqual(self.movie.description, 'Provider plot.')

    @patch('core.xtream_codes.Client')
    def test_valid_advanced_duration_is_applied(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            'info': {'duration_secs': '7200'},
            'movie_data': {},
        }

        result = refresh_movie_advanced_data(self.relation.id, force_refresh=True)

        self.assertEqual(result, 'Advanced data refreshed.')
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.duration_secs, 7200)

    @patch('core.xtream_codes.Client')
    def test_zero_advanced_duration_keeps_existing_value(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            'info': {'duration_secs': 0},
            'movie_data': {},
        }

        result = refresh_movie_advanced_data(self.relation.id, force_refresh=True)

        self.assertEqual(result, 'Advanced data refreshed.')
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.duration_secs, 5400)

    @patch('core.xtream_codes.Client')
    def test_invalid_advanced_duration_secs_uses_duration_field(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            'info': {'duration_secs': '2605442460', 'duration': '90'},
            'movie_data': {},
        }

        result = refresh_movie_advanced_data(self.relation.id, force_refresh=True)

        self.assertEqual(result, 'Advanced data refreshed.')
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.duration_secs, 5400)

    @patch('core.xtream_codes.Client')
    def test_unparseable_duration_does_not_abort_refresh(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            'info': {'plot': 'Still saved.', 'duration': '²'},
            'movie_data': {},
        }

        result = refresh_movie_advanced_data(self.relation.id, force_refresh=True)

        self.assertEqual(result, 'Advanced data refreshed.')
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.description, 'Still saved.')
        self.assertEqual(self.movie.duration_secs, 5400)
