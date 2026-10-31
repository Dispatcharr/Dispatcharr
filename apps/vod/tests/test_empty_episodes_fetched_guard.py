"""
Regression: empty get_series_info episode payloads must not mark episodes complete.

refresh_series_episodes used to set episodes_fetched whenever the provider call
completed without raising, including when episodes was empty. A real series_info
object still completes detailed_fetched (even with a blank info key). Only a
missing or non-object body leaves detailed_fetched unset for retry. Empty episode
lists leave episodes_fetched unset unless this relation already has stored rows.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import Episode, M3UEpisodeRelation, M3USeriesRelation, Series
from apps.vod.provider_refresh import run_provider_refresh
from apps.vod.tasks import (
    batch_process_episodes,
    batch_refresh_series_episodes,
    refresh_series_episodes,
)


def _episode(stream_id, title, episode_num):
    return {
        'id': str(stream_id),
        'title': title,
        'episode_num': episode_num,
        'container_extension': 'mp4',
        'info': {},
    }


USER_AGENT_PATCH = patch(
    'apps.m3u.models.M3UAccount.get_user_agent_string',
    return_value='Test/1.0',
)


class EmptyEpisodesFetchedGuardTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='Empty episodes guard',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.series = Series.objects.create(name='Incomplete catalog series')
        self.relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id='1740',
        )

    def _refresh_with_series_info(self, series_info):
        with patch('apps.vod.tasks.XtreamCodesClient') as client_cls:
            get_series_info = client_cls.return_value.__enter__.return_value.get_series_info
            get_series_info.return_value = series_info
            with USER_AGENT_PATCH:
                refresh_series_episodes(
                    self.account, self.series, self.relation.external_series_id,
                )
            return get_series_info

    def test_list_shaped_info_is_applied(self):
        self._refresh_with_series_info({
            'info': [{'plot': 'From a list'}],
            'episodes': {'1': [_episode(101, 'S1E1', 1)]},
        })

        self.relation.refresh_from_db()
        self.series.refresh_from_db()
        props = self.relation.custom_properties or {}
        self.assertEqual(self.series.description, 'From a list')
        self.assertTrue(props.get('detailed_fetched'))
        self.assertTrue(props.get('episodes_fetched'))

    def test_batch_process_count_matches_episode_dicts(self):
        self.assertEqual(
            batch_process_episodes(
                self.account, self.series, {}, series_relation=self.relation,
            ),
            0,
        )
        self.assertEqual(
            batch_process_episodes(
                self.account,
                self.series,
                {'1': [_episode(1, 'E1', 1)], '2': []},
                series_relation=self.relation,
            ),
            1,
        )

    def test_empty_episodes_does_not_set_episodes_fetched(self):
        self._refresh_with_series_info({
            'info': {'plot': 'A show'},
            'episodes': {},
        })

        self.relation.refresh_from_db()
        self.series.refresh_from_db()
        props = self.relation.custom_properties or {}

        self.assertFalse(props.get('episodes_fetched', False))
        self.assertTrue(props.get('detailed_fetched'))
        self.assertIsNotNone(self.relation.last_episode_refresh)
        self.assertEqual(self.series.description, 'A show')
        self.assertEqual(Episode.objects.filter(series=self.series).count(), 0)

    def test_blank_info_object_still_completes_detail_fetch(self):
        self._refresh_with_series_info({'info': {}})

        self.relation.refresh_from_db()
        props = self.relation.custom_properties or {}

        self.assertFalse(props.get('episodes_fetched', False))
        self.assertTrue(props.get('detailed_fetched'))
        self.assertIsNotNone(self.relation.last_episode_refresh)

    def test_blank_info_with_episodes_does_not_keep_refreshing_details(self):
        self._refresh_with_series_info({
            'info': {'plot': '   ', 'backdrop_path': []},
            'episodes': {'1': [_episode(101, 'S1E1', 1)]},
        })

        self.relation.refresh_from_db()
        props = self.relation.custom_properties or {}
        self.assertTrue(props.get('episodes_fetched'))
        self.assertTrue(props.get('detailed_fetched'))
        self.assertIsNotNone(self.relation.last_episode_refresh)

    def test_empty_response_clears_stale_fetched_flags(self):
        refreshed_at = timezone.now() - timedelta(hours=1)
        self.relation.custom_properties = {
            'episodes_fetched': True,
            'detailed_fetched': True,
            'basic_data': {'name': 'keep me'},
        }
        self.relation.last_episode_refresh = refreshed_at
        self.relation.save()

        self._refresh_with_series_info(None)

        self.relation.refresh_from_db()
        props = self.relation.custom_properties or {}
        self.assertFalse(props.get('episodes_fetched', False))
        self.assertFalse(props.get('detailed_fetched', False))
        self.assertEqual(props.get('basic_data'), {'name': 'keep me'})
        self.assertGreater(self.relation.last_episode_refresh, refreshed_at)

    def test_empty_response_allows_retry_that_succeeds(self):
        with patch('apps.vod.tasks.XtreamCodesClient') as client_cls:
            get_series_info = client_cls.return_value.__enter__.return_value.get_series_info
            get_series_info.return_value = {'info': {}, 'episodes': {}}
            with USER_AGENT_PATCH:
                refresh_series_episodes(
                    self.account, self.series, self.relation.external_series_id,
                )

            self.relation.refresh_from_db()
            props = self.relation.custom_properties or {}
            self.assertFalse(props.get('episodes_fetched', False))
            self.assertTrue(props.get('detailed_fetched'))
            self.assertIsNotNone(self.relation.last_episode_refresh)

            get_series_info.return_value = {
                'info': {'plot': 'Now complete'},
                'episodes': {'1': [_episode(101, 'S1E1', 1)]},
            }
            with USER_AGENT_PATCH:
                refresh_series_episodes(
                    self.account, self.series, self.relation.external_series_id,
                )

        self.relation.refresh_from_db()
        self.series.refresh_from_db()
        props = self.relation.custom_properties or {}
        self.assertTrue(props.get('episodes_fetched'))
        self.assertTrue(props.get('detailed_fetched'))
        self.assertIsNotNone(self.relation.last_episode_refresh)
        self.assertEqual(self.series.description, 'Now complete')
        self.assertEqual(Episode.objects.filter(series=self.series).count(), 1)
        self.assertEqual(
            M3UEpisodeRelation.objects.filter(series_relation=self.relation).count(),
            1,
        )
        self.assertEqual(get_series_info.call_count, 2)

    def test_non_empty_episodes_and_details_set_both_flags(self):
        self._refresh_with_series_info({
            'info': {'plot': 'A show'},
            'episodes': {'1': [_episode(101, 'S1E1', 1), _episode(102, 'S1E2', 2)]},
        })

        self.relation.refresh_from_db()
        props = self.relation.custom_properties or {}
        self.assertTrue(props.get('episodes_fetched'))
        self.assertTrue(props.get('detailed_fetched'))
        self.assertIsNotNone(self.relation.last_episode_refresh)
        self.assertEqual(Episode.objects.filter(series=self.series).count(), 2)

    def test_provider_info_retries_empty_fetch_and_stops_after_success(self):
        user = get_user_model().objects.create_user(
            username='empty-fetch-admin', password='testpass', user_level=10,
        )
        client = APIClient()
        client.force_authenticate(user)
        url = f'/api/vod/series/{self.series.id}/provider-info/'

        with patch('apps.vod.tasks.XtreamCodesClient') as provider, USER_AGENT_PATCH, patch('apps.vod.tasks.refresh_library_provider_details.delay') as publish:
            get_series_info = provider.return_value.__enter__.return_value.get_series_info
            get_series_info.return_value = {'info': {}, 'episodes': {}}

            first = client.get(url)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.data['refresh_status'], 'pending')
            get_series_info.assert_not_called()
            run_provider_refresh('series', self.relation.pk, publish.call_args.args[2])
            first = client.get(url)
            self.assertFalse(first.data['episodes_fetched'])
            self.assertTrue(first.data['detailed_fetched'])
            self.assertEqual(first.data['episodes'], {})

            second = client.get(url, {'force_refresh': 'true'})
            self.assertEqual(second.status_code, 200)
            run_provider_refresh('series', self.relation.pk, publish.call_args.args[2])
            self.assertEqual(get_series_info.call_count, 2)

            get_series_info.return_value = {
                'info': {'plot': 'A show'},
                'episodes': {'1': [_episode(101, 'S1E1', 1)]},
            }
            third = client.get(url, {'force_refresh': 'true'})
            self.assertEqual(third.status_code, 200)
            run_provider_refresh('series', self.relation.pk, publish.call_args.args[2])
            third = client.get(url)
            self.assertTrue(third.data['episodes_fetched'])
            self.assertTrue(third.data['detailed_fetched'])
            self.assertEqual(len(third.data['episodes']['1']), 1)

            fourth = client.get(url)
            self.assertEqual(fourth.status_code, 200)
            self.assertEqual(len(fourth.data['episodes']['1']), 1)
            self.assertEqual(get_series_info.call_count, 3)

    def test_provider_info_keeps_stored_episodes_when_provider_returns_empty(self):
        user = get_user_model().objects.create_user(
            username='stored-episodes-admin', password='testpass', user_level=10,
        )
        client = APIClient()
        client.force_authenticate(user)
        url = f'/api/vod/series/{self.series.id}/provider-info/'

        with patch('apps.vod.tasks.XtreamCodesClient') as provider, USER_AGENT_PATCH, patch('apps.vod.tasks.refresh_library_provider_details.delay') as publish:
            get_series_info = provider.return_value.__enter__.return_value.get_series_info
            get_series_info.return_value = {
                'info': {'plot': 'A show'},
                'episodes': {'1': [_episode(101, 'S1E1', 1)]},
            }
            first = client.get(url)
            self.assertEqual(first.data['refresh_status'], 'pending')
            run_provider_refresh('series', self.relation.pk, publish.call_args.args[2])
            first = client.get(url)
            self.assertEqual(len(first.data['episodes']['1']), 1)

            self.relation.refresh_from_db()
            self.relation.last_episode_refresh = timezone.now() - timedelta(hours=25)
            self.relation.save(update_fields=['last_episode_refresh'])
            get_series_info.return_value = {'info': {}, 'episodes': {}}

            second = client.get(url)
            self.assertEqual(second.data['refresh_status'], 'pending')
            # Stored episodes remain visible while a background refresh runs.
            self.assertEqual(len(second.data['episodes']['1']), 1)
            run_provider_refresh('series', self.relation.pk, publish.call_args.args[2])
            second = client.get(url)
            self.assertEqual(second.status_code, 200)
            self.assertTrue(second.data['episodes_fetched'])
            self.assertTrue(second.data['detailed_fetched'])
            self.assertEqual(len(second.data['episodes']['1']), 1)

            third = client.get(url)
            self.assertEqual(len(third.data['episodes']['1']), 1)
            self.assertEqual(get_series_info.call_count, 2)

    def test_empty_payload_ignores_episodes_from_other_series_relation(self):
        other_series = Series.objects.create(name='Other series')
        other_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=other_series,
            external_series_id='other',
        )
        episode = Episode.objects.create(
            series=other_series,
            name='Other E1',
            season_number=1,
            episode_number=1,
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=episode,
            series_relation=other_relation,
            stream_id='999',
            container_extension='mp4',
        )

        self._refresh_with_series_info({
            'info': {'plot': 'A show'},
            'episodes': {},
        })

        self.relation.refresh_from_db()
        props = self.relation.custom_properties or {}
        self.assertFalse(props.get('episodes_fetched', False))
        self.assertTrue(props.get('detailed_fetched'))

    def test_batch_refresh_skips_never_opened_series(self):
        recent_series = Series.objects.create(name='Recently fetched')
        M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=recent_series,
            external_series_id='recent',
            last_episode_refresh=timezone.now(),
            custom_properties={'episodes_fetched': True, 'detailed_fetched': True},
        )
        stale_series = Series.objects.create(name='Stale fetched')
        M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=stale_series,
            external_series_id='stale',
            last_episode_refresh=timezone.now() - timedelta(hours=25),
            custom_properties={'episodes_fetched': True, 'detailed_fetched': True},
        )

        with patch('apps.vod.tasks.refresh_series_episodes') as refresh:
            batch_refresh_series_episodes(self.account.id)

        refreshed = {call.args[2] for call in refresh.call_args_list}
        self.assertNotIn('1740', refreshed)
        self.assertIn('stale', refreshed)
        self.assertNotIn('recent', refreshed)
