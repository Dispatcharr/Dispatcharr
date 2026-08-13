"""XC episode discovery and episode payload processing regression tests."""

from datetime import timedelta
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.vod.models import Episode, M3UEpisodeRelation, M3USeriesRelation, Series
from apps.vod.tasks import batch_process_episodes, refresh_due_series_episodes


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

    def test_due_refresh_includes_never_fetched_and_stale_series(self):
        stale_series = Series.objects.create(name='Stale Series', year=2001)
        stale_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=stale_series,
            external_series_id='8702',
            last_episode_refresh=timezone.now() - timedelta(hours=25),
        )
        recent_series = Series.objects.create(name='Recent Series', year=2002)
        M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=recent_series,
            external_series_id='8703',
            last_episode_refresh=timezone.now(),
        )
        client = MagicMock()
        client.get_series_info.side_effect = lambda series_id: {
            'info': {},
            'episodes': {
                '1': [_episode(f'{series_id}01', f'{series_id} episode', 1)],
            },
        }

        result = refresh_due_series_episodes(self.account, client=client)

        self.assertEqual(
            result,
            {
                'total': 2,
                'refreshed': 2,
                'failed': 0,
                'failed_series': [],
            },
        )
        self.assertEqual(
            {call.args[0] for call in client.get_series_info.call_args_list},
            {'8701', '8702'},
        )
        self.series_relation.refresh_from_db()
        stale_relation.refresh_from_db()
        self.assertIsNotNone(self.series_relation.last_episode_refresh)
        self.assertIsNotNone(stale_relation.last_episode_refresh)
        self.assertEqual(
            M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(),
            2,
        )

    def test_full_scan_refresh_only_hydrates_relations_seen_in_that_scan(self):
        scan_start = timezone.now()
        self.series_relation.last_seen = scan_start - timedelta(seconds=1)
        self.series_relation.save(update_fields=['last_seen'])
        current_series = Series.objects.create(name='Current Series', year=2003)
        M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=current_series,
            external_series_id='8704',
            last_seen=scan_start,
        )
        client = MagicMock()
        client.get_series_info.return_value = {'info': {}, 'episodes': {}}

        result = refresh_due_series_episodes(
            self.account,
            client=client,
            scan_start_time=scan_start,
        )

        self.assertEqual(
            result,
            {
                'total': 1,
                'refreshed': 0,
                'failed': 1,
                'failed_series': [
                    {
                        'id': current_series.id,
                        'name': current_series.name,
                        'external_series_id': '8704',
                    }
                ],
            },
        )
        client.get_series_info.assert_called_once_with('8704')
