"""stream_xc_movie's stream_id resolution under the VOD category-language
feature: relation-id-first once any category has a language assigned, with
a Movie.id fallback for stale clients, and the legacy movie_id lookup when
the feature is off.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.views import _LANGUAGE_UNSET, stream_xc_movie
from apps.vod.language import invalidate_category_metadata_cache
from apps.vod.models import M3UMovieRelation, M3UVODCategoryRelation, Movie, VODCategory

User = get_user_model()


class StreamXcMovieLanguageTests(TestCase):
    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)

        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='xcmovieuser', password='testpass123')
        self.user.custom_properties = {'xc_password': 'streampass'}
        self.user.save()

        self.account = M3UAccount.objects.create(
            name='StreamProvider',
            server_url='http://example.com',
            username='u',
            password='p',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.movie = Movie.objects.create(name='Stream Movie', year=2020)

    def _call(self, stream_id):
        request = self.factory.get(f'/movie/xcmovieuser/streampass/{stream_id}.mp4')
        with patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True), \
             patch('apps.proxy.vod_proxy.views.stream_vod', return_value=HttpResponse('OK')) as stream_vod_mock:
            response = stream_xc_movie(request, 'xcmovieuser', 'streampass', str(stream_id), 'mp4')
        return response, stream_vod_mock

    def test_feature_off_resolves_as_movie_id_legacy(self):
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, stream_id='p-1',
            container_extension='mp4',
        )
        response, stream_vod_mock = self._call(self.movie.id)

        stream_vod_mock.assert_called_once()
        self.assertEqual(stream_vod_mock.call_args[0][2], self.movie.uuid)
        self.assertEqual(stream_vod_mock.call_args.kwargs.get('content_language'), _LANGUAGE_UNSET)

    def test_feature_on_resolves_via_relation_id(self):
        category, props = VODCategory.objects.create(
            name='Spanish', category_type='movie'
        ), {'language': 'es'}
        M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=True, custom_properties=props,
        )
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, category=category,
            stream_id='p-2', container_extension='mp4',
        )

        response, stream_vod_mock = self._call(relation.id)

        stream_vod_mock.assert_called_once()
        self.assertEqual(stream_vod_mock.call_args[0][2], self.movie.uuid)
        self.assertEqual(stream_vod_mock.call_args.kwargs.get('content_language'), 'es')

    def test_feature_on_still_resolves_a_stale_movie_id(self):
        """A pre-feature client's cached Movie.id must still resolve to the
        right movie once the feature is on, whether that's because the id
        happens to also be a live relation pk (harmless: same movie either
        way) or because it misses as a relation id and falls through to the
        legacy Movie.id lookup."""
        category, props = VODCategory.objects.create(
            name='French', category_type='movie'
        ), {'language': 'fr'}
        M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=True, custom_properties=props,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, category=category,
            stream_id='p-3', container_extension='mp4',
        )

        response, stream_vod_mock = self._call(self.movie.id)

        stream_vod_mock.assert_called_once()
        self.assertEqual(stream_vod_mock.call_args[0][2], self.movie.uuid)

    def test_feature_on_unresolvable_id_is_404(self):
        category, props = VODCategory.objects.create(
            name='German', category_type='movie'
        ), {'language': 'de'}
        M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=True, custom_properties=props,
        )

        response, stream_vod_mock = self._call(999999)

        self.assertEqual(response.status_code, 404)
        stream_vod_mock.assert_not_called()
