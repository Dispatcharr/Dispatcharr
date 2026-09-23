from datetime import timedelta
from unittest.mock import ANY, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import Episode, M3UEpisodeRelation, M3USeriesRelation, Series
from apps.vod.tasks import (
    refresh_series_episodes,
    refresh_series_provider_info_in_background,
    series_provider_refresh_keys,
)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class SeriesProviderInfoAsyncTests(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_user(username='series-admin', password='testpass')
        user.user_level = 10
        user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.account = M3UAccount.objects.create(
            name='Provider', server_url='http://example.com', username='user',
            password='pass', account_type=M3UAccount.Types.XC, is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.series = Series.objects.create(name='Cached Series', year=2024)
        self.relation = M3USeriesRelation.objects.create(
            series=self.series, m3u_account=self.account,
            external_series_id='1234', custom_properties={},
        )
        self.url = f'/api/vod/series/{self.series.id}/provider-info/?relation_id={self.relation.id}'

    @patch('apps.vod.api_views.refresh_series_provider_info_in_background.delay')
    def test_missing_episodes_return_immediately_and_queue_only_once(self, delay):
        first = self.client.get(self.url)
        second = self.client.get(self.url)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['episodes'], {})
        self.assertFalse(first.data['episodes_fetched'])
        self.assertEqual(first.data['detail_refresh_status'], 'pending')
        self.assertEqual(second.data['detail_refresh_status'], 'pending')
        delay.assert_called_once_with(self.relation.id)

    @patch('apps.vod.api_views.refresh_series_provider_info_in_background.delay')
    def test_stored_episode_relations_are_visible_even_before_fetch_flag(self, delay):
        episode = Episode.objects.create(
            series=self.series, name='Stored Episode', season_number=1, episode_number=2,
        )
        M3UEpisodeRelation.objects.create(
            episode=episode, series_relation=self.relation,
            m3u_account=self.account, stream_id='5678', container_extension='mkv',
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['episodes_fetched'])
        self.assertEqual(response.data['episodes']['1'][0]['name'], 'Stored Episode')
        self.assertEqual(response.data['detail_refresh_status'], 'pending')
        delay.assert_called_once_with(self.relation.id)

    @patch('apps.vod.api_views.refresh_series_provider_info_in_background.delay')
    def test_stale_provider_keeps_cached_episodes_visible_while_refreshing(self, delay):
        self.relation.custom_properties = {'episodes_fetched': True, 'detailed_fetched': True}
        self.relation.last_episode_refresh = timezone.now() - timedelta(days=2)
        self.relation.save(update_fields=['custom_properties', 'last_episode_refresh'])
        episode = Episode.objects.create(
            series=self.series, name='First Episode', season_number=1, episode_number=1,
        )
        M3UEpisodeRelation.objects.create(
            episode=episode, series_relation=self.relation,
            m3u_account=self.account, stream_id='5678', container_extension='mkv',
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['detail_refresh_status'], 'pending')
        self.assertEqual(response.data['episodes']['1'][0]['name'], 'First Episode')
        delay.assert_called_once_with(self.relation.id)

    @patch('apps.vod.api_views.refresh_series_provider_info_in_background.delay')
    def test_fresh_provider_does_not_queue_refresh(self, delay):
        self.relation.custom_properties = {'episodes_fetched': True, 'detailed_fetched': True}
        self.relation.last_episode_refresh = timezone.now()
        self.relation.save(update_fields=['custom_properties', 'last_episode_refresh'])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['detail_refresh_status'], 'completed')
        delay.assert_not_called()

    @patch('apps.vod.api_views.refresh_series_provider_info_in_background.delay')
    def test_failed_refresh_waits_for_explicit_retry(self, delay):
        _, status_key = series_provider_refresh_keys(self.relation.id)
        cache.set(status_key, 'failed')
        self.assertEqual(self.client.get(self.url).data['detail_refresh_status'], 'failed')
        delay.assert_not_called()

        retry = self.client.post(self.url)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.data['detail_refresh_status'], 'pending')
        delay.assert_called_once_with(self.relation.id)

    @patch('apps.vod.tasks.refresh_series_episodes')
    def test_background_failure_releases_lock_and_reports_failure(self, refresh):
        lock_key, status_key = series_provider_refresh_keys(self.relation.id)
        cache.set(lock_key, True)

        refresh_series_provider_info_in_background.run(self.relation.id)

        refresh.assert_called_once_with(
            self.account, self.series, '1234', bounded=True, series_relation=ANY
        )
        self.assertEqual(cache.get(status_key), 'failed')
        self.assertIsNone(cache.get(lock_key))

    @patch('apps.vod.tasks.XtreamCodesClient')
    def test_background_lookup_uses_bounded_provider_timeout(self, client_class):
        client_class.return_value.__enter__.return_value.get_series_info.return_value = {
            'info': {}, 'episodes': {},
        }

        refresh_series_episodes(
            self.account, self.series, '1234', bounded=True,
            series_relation=self.relation,
        )

        client_class.assert_called_once_with(
            self.account.server_url,
            self.account.username,
            self.account.password,
            self.account.get_user_agent_string(),
            request_timeout=(10, 30),
            max_retries=0,
        )

    @patch('apps.vod.tasks.XtreamCodesClient')
    def test_empty_provider_reply_is_not_cached_as_success(self, client_class):
        client_class.return_value.__enter__.return_value.get_series_info.return_value = None
        _, status_key = series_provider_refresh_keys(self.relation.id)

        refresh_series_provider_info_in_background.run(self.relation.id)

        self.relation.refresh_from_db()
        self.assertEqual(cache.get(status_key), 'failed')
        self.assertIsNone(self.relation.last_episode_refresh)
        self.assertFalse(self.relation.custom_properties.get('episodes_fetched', False))
