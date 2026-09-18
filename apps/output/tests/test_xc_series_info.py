"""XC get_series_info preserves Season 0 and avoids episode-relation N+1."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_series_info
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3USeriesRelation,
    Series,
)

User = get_user_model()


class XCGetSeriesInfoTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='xcuser', password='testpass123')
        self.user.user_level = 10
        self.user.save()

        self.account = M3UAccount.objects.create(
            name='Provider A',
            server_url='http://a.example.com',
            username='a',
            password='a',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=1,
            custom_properties={'enable_vod': True},
        )
        self.other_account = M3UAccount.objects.create(
            name='Provider B',
            server_url='http://b.example.com',
            username='b',
            password='b',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=10,
            custom_properties={'enable_vod': True},
        )
        self.series = Series.objects.create(name='Shared Show', year=1989)

        self.relation_a = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id='100',
            last_episode_refresh=timezone.now(),
            custom_properties={'episodes_fetched': True, 'detailed_fetched': True},
        )
        self.relation_b = M3USeriesRelation.objects.create(
            m3u_account=self.other_account,
            series=self.series,
            external_series_id='200',
            last_episode_refresh=timezone.now(),
            custom_properties={'episodes_fetched': True, 'detailed_fetched': True},
        )

        self.s1e1 = Episode.objects.create(
            series=self.series, name='S1E1', season_number=1, episode_number=1
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=self.s1e1,
            series_relation=self.relation_a,
            stream_id='a-1',
            container_extension='mkv',
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.other_account,
            episode=self.s1e1,
            series_relation=self.relation_b,
            stream_id='b-1',
            container_extension='mp4',
        )

        self.special = Episode.objects.create(
            series=self.series, name='Special', season_number=0, episode_number=1
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.other_account,
            episode=self.special,
            series_relation=self.relation_b,
            stream_id='b-special',
            container_extension='mp4',
        )

    def _info(self, relation_id):
        request = self.factory.get('/player_api.php')
        return xc_get_series_info(request, self.user, str(relation_id))

    def test_returns_only_selected_relation_episodes(self):
        info = self._info(self.relation_a.id)
        self.assertNotIn(0, info['episodes'])
        self.assertIn(1, info['episodes'])
        self.assertEqual(info['episodes'][1][0]['title'], 'S1E1')

    def test_uses_selected_relation_stream_metadata(self):
        info = self._info(self.relation_a.id)
        self.assertEqual(info['episodes'][1][0]['container_extension'], 'mkv')

    def test_tmdb_id_uses_the_selected_provider_source_override(self):
        self.series.tmdb_id = '100'
        self.series.tmdb_match_id = '100'
        self.series.save(update_fields=['tmdb_id', 'tmdb_match_id'])
        self.relation_a.tmdb_override_id = '200'
        self.relation_a.save(update_fields=['tmdb_override_id'])

        info = self._info(self.relation_a.id)

        self.assertEqual(info['info']['tmdb'], '200')

    def test_uses_selected_relation_episode_metadata(self):
        relation = M3UEpisodeRelation.objects.get(
            series_relation=self.relation_a,
            episode=self.s1e1,
        )
        relation.custom_properties = {
            'info': {
                'title': 'Provider A Episode',
                'episode_num': 1,
                'info': {
                    'plot': 'Provider A plot',
                    'duration_secs': '1500',
                    'rating': '8.4',
                    'air_date': '1989-02-03',
                    'tmdb_id': 'a-tmdb',
                    'imdb_id': 'a-imdb',
                    'director': 'Provider A Director',
                },
            }
        }
        relation.save(update_fields=['custom_properties'])

        info = self._info(self.relation_a.id)
        episode = info['episodes'][1][0]

        self.assertEqual(episode['id'], relation.id)
        self.assertEqual(episode['title'], 'Provider A Episode')
        self.assertEqual(episode['info']['overview'], 'Provider A plot')
        self.assertEqual(episode['info']['duration_secs'], 1500)
        self.assertEqual(episode['info']['duration'], '00:25:00')
        self.assertEqual(episode['info']['rating'], 8.4)
        self.assertEqual(episode['info']['air_date'], '1989-02-03')
        self.assertEqual(episode['info']['tmdb_id'], 'a-tmdb')
        self.assertEqual(episode['info']['imdb_id'], 'a-imdb')
        self.assertEqual(
            episode['info']['directed_by'],
            'Provider A Director',
        )

    def test_episode_artwork_prefers_higher_priority_relation(self):
        self.s1e1.custom_properties = {
            'movie_image': 'https://cdn.example.com/stale.jpg',
        }
        self.s1e1.save(update_fields=['custom_properties'])
        M3UEpisodeRelation.objects.filter(
            episode=self.s1e1, m3u_account=self.account
        ).update(
            custom_properties={
                'info': {'info': {'movie_image': 'https://cdn.example.com/low.jpg'}}
            }
        )
        M3UEpisodeRelation.objects.filter(
            episode=self.s1e1, m3u_account=self.other_account
        ).update(
            custom_properties={
                'info': {'info': {'movie_image': 'https://cdn.example.com/high.jpg'}}
            }
        )

        info = self._info(self.relation_a.id)
        movie_image = info['episodes'][1][0]['info']['movie_image']
        self.assertIn('/api/vod/episodes/', movie_image)
        self.assertIn('kind=movie_image', movie_image)
        # Proxied URL embeds a hash of the selected relation's source URL.
        from hashlib import md5
        expected_v = md5(b'https://cdn.example.com/low.jpg').hexdigest()[:8]
        self.assertIn(f'v={expected_v}', movie_image)

    def test_does_not_n_plus_one_episode_relations(self):
        for i in range(2, 12):
            ep = Episode.objects.create(
                series=self.series,
                name=f'S1E{i}',
                season_number=1,
                episode_number=i,
            )
            M3UEpisodeRelation.objects.create(
                m3u_account=self.account,
                episode=ep,
                series_relation=self.relation_a,
                stream_id=f'a-{i}',
                container_extension='mkv',
            )

        self._info(self.relation_a.id)  # warm

        with CaptureQueriesContext(connection) as ctx:
            info = self._info(self.relation_a.id)

        self.assertEqual(len(info['episodes'][1]), 11)
        relation_queries = [
            q for q in ctx.captured_queries
            if 'from "vod_m3uepisoderelation"' in q['sql'].lower()
            or "from vod_m3uepisoderelation" in q['sql'].lower()
        ]
        # At most one bulk fetch. A warm XC catalog cache legitimately needs no
        # relation query at all.
        self.assertLessEqual(len(relation_queries), 1)
