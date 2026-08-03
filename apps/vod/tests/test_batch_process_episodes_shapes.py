"""batch_process_episodes accepts dict and list-shaped XC episode payloads."""

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod.models import Episode, M3UEpisodeRelation, M3USeriesRelation, Series
from apps.vod.tasks import batch_process_episodes


def _episode(stream_id, title, episode_num, season=None):
    data = {
        'id': str(stream_id),
        'title': title,
        'episode_num': episode_num,
        'container_extension': 'mp4',
        'info': {},
    }
    if season is not None:
        data['season'] = season
    return data


class BatchProcessEpisodesShapesTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='XC Episodes Shape',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.series = Series.objects.create(name='Example Series', year=2000)
        self.series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id='8701',
        )

    def test_dict_shaped_episodes_use_season_keys(self):
        episodes_data = {
            '1': [_episode(101, 'S1E1', 1, season=1)],
            '2': [_episode(201, 'S2E1', 1, season=2)],
        }

        batch_process_episodes(
            self.account,
            self.series,
            episodes_data,
            series_relation=self.series_relation,
        )

        seasons = set(
            Episode.objects.filter(series=self.series).values_list(
                'season_number', flat=True
            )
        )
        self.assertEqual(seasons, {1, 2})
        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 2)

    def test_list_shaped_episodes_use_index_as_season(self):
        # Contiguous 0-based season keys become a JSON array from PHP panels.
        episodes_data = [
            [_episode(1, 'Special', 1, season=0)],
            [_episode(11, 'S1E1', 1, season=1)],
            [_episode(21, 'S2E1', 1, season=2)],
        ]

        batch_process_episodes(
            self.account,
            self.series,
            episodes_data,
            series_relation=self.series_relation,
        )

        by_season = {
            ep.season_number: ep.name
            for ep in Episode.objects.filter(series=self.series)
        }
        self.assertEqual(
            by_season,
            {0: 'Special', 1: 'S1E1', 2: 'S2E1'},
        )
        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 3)

    def test_list_shaped_skips_non_list_season_slots(self):
        episodes_data = [
            None,
            [_episode(11, 'S1E1', 1, season=1)],
        ]

        batch_process_episodes(
            self.account,
            self.series,
            episodes_data,
            series_relation=self.series_relation,
        )

        episodes = list(Episode.objects.filter(series=self.series))
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].season_number, 1)
        self.assertEqual(episodes[0].name, 'S1E1')
