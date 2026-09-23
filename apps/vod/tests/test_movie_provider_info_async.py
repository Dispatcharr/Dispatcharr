from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import M3UMovieRelation, Movie
from apps.vod.tasks import (
    movie_provider_refresh_keys,
    refresh_movie_provider_info_in_background,
)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class MovieProviderInfoAsyncTests(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_user(username='movie-admin', password='testpass')
        user.user_level = 10
        user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        account = M3UAccount.objects.create(
            name='Provider', server_url='http://example.com', username='user',
            password='pass', account_type=M3UAccount.Types.XC, is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.movie = Movie.objects.create(name='Cached Movie', year=2024)
        self.relation = M3UMovieRelation.objects.create(
            movie=self.movie, m3u_account=account, stream_id='1234',
            container_extension='mkv', custom_properties={'detailed_fetched': False},
        )
        self.url = f'/api/vod/movies/{self.movie.id}/provider-info/?relation_id={self.relation.id}'

    @patch('apps.vod.api_views.refresh_movie_provider_info_in_background.delay')
    def test_get_returns_cached_data_and_queues_only_one_background_lookup(self, delay):
        first = self.client.get(self.url)
        second = self.client.get(self.url)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['name'], 'Cached Movie')
        self.assertFalse(first.data['detail_fetched'])
        self.assertEqual(first.data['detail_refresh_status'], 'pending')
        self.assertEqual(second.data['detail_refresh_status'], 'pending')
        delay.assert_called_once_with(self.relation.id, force_refresh=False)

    @patch('apps.vod.api_views.refresh_movie_provider_info_in_background.delay')
    def test_failed_lookup_waits_for_explicit_retry(self, delay):
        _, status_key = movie_provider_refresh_keys(self.relation.id)
        cache.set(status_key, 'failed')
        self.assertEqual(self.client.get(self.url).data['detail_refresh_status'], 'failed')
        delay.assert_not_called()

        retry = self.client.post(self.url)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.data['detail_refresh_status'], 'pending')
        delay.assert_called_once_with(self.relation.id, force_refresh=True)

    @patch('apps.vod.api_views.refresh_movie_provider_info_in_background.delay')
    def test_fetched_details_do_not_start_a_new_lookup(self, delay):
        self.relation.custom_properties = {'detailed_fetched': True, 'detailed_info': {'name': 'Provider Movie'}}
        self.relation.save(update_fields=['custom_properties'])

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Provider Movie')
        self.assertTrue(response.data['detail_fetched'])
        self.assertEqual(response.data['detail_refresh_status'], 'completed')
        delay.assert_not_called()

    @patch('apps.vod.tasks.refresh_movie_advanced_data', return_value='Error: timed out')
    def test_background_failure_releases_lock_and_reports_failure(self, refresh):
        lock_key, status_key = movie_provider_refresh_keys(self.relation.id)
        cache.set(lock_key, True)

        refresh_movie_provider_info_in_background.run(self.relation.id)

        refresh.assert_called_once_with(self.relation.id, force_refresh=False, bounded=True)
        self.assertEqual(cache.get(status_key), 'failed')
        self.assertIsNone(cache.get(lock_key))
