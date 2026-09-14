"""stream_xc_episode's stream_id resolution under the VOD category-language
feature, mirroring stream_xc_movie: relation-id-first once any category has
a language assigned, with an Episode.id fallback for stale clients, and the
legacy episode_id lookup when the feature is off.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.views import _LANGUAGE_UNSET, stream_xc_episode
from apps.vod.language import invalidate_category_metadata_cache
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Series,
    VODCategory,
)

User = get_user_model()


class StreamXcEpisodeLanguageTests(TestCase):
    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)

        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='xcepisodeuser', password='testpass123')
        self.user.custom_properties = {'xc_password': 'streampass'}
        self.user.save()

        self.account = M3UAccount.objects.create(
            name='EpisodeProvider',
            server_url='http://example.com',
            username='u',
            password='p',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.series = Series.objects.create(name='Stream Series', year=2020)
        self.episode = Episode.objects.create(series=self.series, name='Ep 1')

    def _call(self, stream_id):
        request = self.factory.get(f'/series/xcepisodeuser/streampass/{stream_id}.mp4')
        with patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True), \
             patch('apps.proxy.vod_proxy.views.stream_vod', return_value=HttpResponse('OK')) as stream_vod_mock:
            response = stream_xc_episode(request, 'xcepisodeuser', 'streampass', str(stream_id), 'mp4')
        return response, stream_vod_mock

    def test_feature_off_resolves_as_episode_id_legacy(self):
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=self.episode, stream_id='p-1',
        )
        response, stream_vod_mock = self._call(self.episode.id)

        stream_vod_mock.assert_called_once()
        self.assertEqual(stream_vod_mock.call_args[0][2], self.episode.uuid)
        self.assertEqual(stream_vod_mock.call_args.kwargs.get('content_language'), _LANGUAGE_UNSET)

    def test_feature_on_resolves_via_relation_id(self):
        category = VODCategory.objects.create(name='Spanish', category_type='series')
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=self.series, category=category,
            external_series_id='ext-1',
        )
        M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=True,
            custom_properties={'language': 'es'},
        )
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=self.episode, series_relation=series_relation,
            stream_id='p-2',
        )

        response, stream_vod_mock = self._call(relation.id)

        stream_vod_mock.assert_called_once()
        self.assertEqual(stream_vod_mock.call_args[0][2], self.episode.uuid)
        self.assertEqual(stream_vod_mock.call_args.kwargs.get('content_language'), 'es')

    def test_feature_on_still_resolves_a_stale_episode_id(self):
        category = VODCategory.objects.create(name='French', category_type='series')
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=self.series, category=category,
            external_series_id='ext-2',
        )
        M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=True,
            custom_properties={'language': 'fr'},
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=self.episode, series_relation=series_relation,
            stream_id='p-3',
        )

        response, stream_vod_mock = self._call(self.episode.id)

        stream_vod_mock.assert_called_once()
        self.assertEqual(stream_vod_mock.call_args[0][2], self.episode.uuid)

    def test_feature_on_unresolvable_id_is_404(self):
        category = VODCategory.objects.create(name='German', category_type='series')
        M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=True,
            custom_properties={'language': 'de'},
        )

        response, stream_vod_mock = self._call(999999)

        self.assertEqual(response.status_code, 404)
        stream_vod_mock.assert_not_called()
