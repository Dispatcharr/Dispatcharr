"""Series provider-info scopes episodes to the selected provider account."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3USeriesRelation,
    Series,
)

User = get_user_model()


class SeriesProviderInfoQueryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='vodadmin', password='testpass123')
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.account = M3UAccount.objects.create(
            name='XC Provider',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.other_account = M3UAccount.objects.create(
            name='Other Provider',
            server_url='http://other.example.com',
            username='user2',
            password='pass2',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.series = Series.objects.create(name='Big Series', year=1989)
        self.series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id='8701',
            last_episode_refresh=timezone.now(),
            custom_properties={
                'episodes_fetched': True,
                'detailed_fetched': True,
            },
        )
        self.other_relation = M3USeriesRelation.objects.create(
            m3u_account=self.other_account,
            series=self.series,
            external_series_id='9999',
            last_episode_refresh=timezone.now(),
            custom_properties={
                'episodes_fetched': True,
                'detailed_fetched': True,
            },
        )

        self.episode_count = 20
        for i in range(self.episode_count):
            episode = Episode.objects.create(
                series=self.series,
                name=f'Episode {i + 1}',
                season_number=1,
                episode_number=i + 1,
                custom_properties={'movie_image': ''},
            )
            M3UEpisodeRelation.objects.create(
                m3u_account=self.account,
                episode=episode,
                series_relation=self.series_relation,
                stream_id=str(1000 + i),
                container_extension='mkv',
            )

        # Specials exist on the shared Series but only on the other provider.
        self.special = Episode.objects.create(
            series=self.series,
            name='Special',
            season_number=0,
            episode_number=1,
            custom_properties={'movie_image': ''},
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.other_account,
            episode=self.special,
            series_relation=self.other_relation,
            stream_id='special-1',
            container_extension='mp4',
        )

    def test_provider_info_does_not_n_plus_one_episode_relations(self):
        url = (
            f'/api/vod/series/{self.series.id}/provider-info/'
            f'?include_episodes=true&relation_id={self.series_relation.id}'
        )

        warm = self.client.get(url)
        self.assertEqual(warm.status_code, 200)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        seasons = response.data.get('episodes') or {}
        episodes = seasons.get('1') or []
        self.assertEqual(len(episodes), self.episode_count)
        self.assertEqual(episodes[0]['container_extension'], 'mkv')

        relation_queries = [
            q for q in ctx.captured_queries
            if 'vod_m3uepisoderelation' in q['sql'].lower()
        ]
        self.assertEqual(len(relation_queries), 1)
        self.assertLessEqual(len(ctx.captured_queries), 12)

    def test_provider_info_backdrop_prefers_selected_relation_basic_data(self):
        """Shared Series.custom_properties can be stale; the selected account's
        own list-sync backdrop should be preferred when it has one."""
        self.series.custom_properties = {
            'backdrop_path': ['https://cdn.example.com/stale.jpg'],
        }
        self.series.save(update_fields=['custom_properties'])
        self.other_relation.custom_properties = {
            'episodes_fetched': True,
            'detailed_fetched': True,
            'basic_data': {'backdrop_path': 'https://cdn.example.com/fresh.jpg'},
        }
        self.other_relation.save(update_fields=['custom_properties'])

        url = (
            f'/api/vod/series/{self.series.id}/provider-info/'
            f'?include_episodes=false&relation_id={self.other_relation.id}'
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        backdrops = response.data.get('backdrop_path') or []
        self.assertEqual(len(backdrops), 1)
        from hashlib import md5
        expected_v = md5(b'https://cdn.example.com/fresh.jpg').hexdigest()[:8]
        self.assertIn(f'v={expected_v}', backdrops[0])

    def test_provider_info_omits_episodes_only_on_other_accounts(self):
        url = (
            f'/api/vod/series/{self.series.id}/provider-info/'
            f'?include_episodes=true&relation_id={self.series_relation.id}'
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        seasons = response.data.get('episodes') or {}
        self.assertNotIn('0', seasons)
        self.assertEqual(len(seasons.get('1') or []), self.episode_count)

        other_url = (
            f'/api/vod/series/{self.series.id}/provider-info/'
            f'?include_episodes=true&relation_id={self.other_relation.id}'
        )
        other_response = self.client.get(other_url)
        self.assertEqual(other_response.status_code, 200)
        other_seasons = other_response.data.get('episodes') or {}
        self.assertEqual(len(other_seasons.get('0') or []), 1)
        self.assertEqual(other_seasons['0'][0]['name'], 'Special')
