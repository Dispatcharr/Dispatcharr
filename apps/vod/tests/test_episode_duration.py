"""Bad provider durations must not discard an entire episode batch."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import Episode, M3UEpisodeRelation, M3USeriesRelation, Series
from apps.vod.provider_refresh import run_provider_refresh
from apps.vod.tasks import MAX_DURATION_SECS, batch_process_episodes


def episode_data(number, duration):
    return {
        'id': str(1000 + number),
        'title': f'Episode {number}',
        'episode_num': number,
        'container_extension': 'mp4',
        'info': {'duration_secs': duration},
    }


class EpisodeDurationTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='Duration test provider',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.series = Series.objects.create(name='Duration test series')
        self.relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id='1771',
        )

    def process(self, episodes):
        batch_process_episodes(
            self.account, self.series, {'1': episodes},
            series_relation=self.relation,
        )

    def durations(self):
        return list(self.series.episodes.order_by('episode_number').values_list(
            'duration_secs', flat=True,
        ))

    def test_invalid_durations_do_not_abort_bulk_create(self):
        durations = [
            2605442460, '2605442460', MAX_DURATION_SECS + 1, -(MAX_DURATION_SECS + 1),
            -1, 0, '0', '', 'unknown', '1.5', 1.5, None, True, [], {},
        ]
        self.process([
            episode_data(number, duration)
            for number, duration in enumerate(durations + [1800], start=1)
        ])

        self.assertEqual(self.durations(), [None] * len(durations) + [1800])
        self.assertEqual(
            M3UEpisodeRelation.objects.filter(series_relation=self.relation).count(),
            len(durations) + 1,
        )

    def test_invalid_duration_does_not_roll_back_updates_or_new_episodes(self):
        self.process([episode_data(1, 1800), episode_data(2, 2400)])
        original_ids = list(self.series.episodes.values_list('id', flat=True))

        self.process([
            episode_data(1, 2605442460),
            episode_data(2, '3600'),
            episode_data(3, 1200),
        ])

        # Invalid duration on episode 1 must not wipe the previous good value.
        self.assertEqual(self.durations(), [1800, 3600, 1200])
        self.assertEqual(Episode.objects.filter(id__in=original_ids).count(), 2)
        self.assertEqual(
            M3UEpisodeRelation.objects.filter(series_relation=self.relation).count(), 3,
        )

    def test_valid_integer_durations_and_max_boundary_are_preserved(self):
        durations = [1800, 1800.0, '3600', MAX_DURATION_SECS, str(MAX_DURATION_SECS)]
        self.process([
            episode_data(number, duration)
            for number, duration in enumerate(durations, start=1)
        ])

        self.assertEqual(self.durations(), [int(value) for value in durations])

    def test_provider_info_returns_episodes_and_does_not_retry_completed_refresh(self):
        user = get_user_model().objects.create_user(
            username='duration-admin', password='testpass', user_level=10,
        )
        client = APIClient()
        client.force_authenticate(user)
        url = f'/api/vod/series/{self.series.id}/provider-info/'

        with patch('apps.vod.tasks.XtreamCodesClient') as provider, patch('apps.vod.tasks.refresh_library_provider_details.delay') as publish:
            get_series_info = provider.return_value.__enter__.return_value.get_series_info
            get_series_info.return_value = {
                'info': {'plot': 'Duration test plot'},
                'episodes': {'1': [episode_data(1, 2605442460), episode_data(2, 1800)]},
            }
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['refresh_status'], 'pending')
            get_series_info.assert_not_called()
            run_provider_refresh('series', self.relation.pk, publish.call_args.args[2])
            response = client.get(url)
            self.assertTrue(response.data['episodes_fetched'])
            self.assertEqual(
                [episode['duration_secs'] for episode in response.data['episodes']['1']],
                [None, 1800],
            )
            self.relation.refresh_from_db()
            self.assertIsNotNone(self.relation.last_episode_refresh)

            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['episodes']['1']), 2)
            get_series_info.assert_called_once_with('1771')
