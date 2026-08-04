"""stream_xc_movie / stream_xc_episode: lookup by the stable relation PK.

Context: xc_get_vod_streams / xc_get_vod_info / xc_get_series_info hand XC
clients (TiviMate etc.) an episode/movie "id" that clients cache and later
request playback with. That id used to be the underlying Movie/Episode row's
own PK, which is not stable -- a catalog refresh can delete and recreate the
row, orphaning every cached id. The M3UMovieRelation/M3UEpisodeRelation rows
themselves are stable (upserted in place, keyed by (m3u_account, stream_id)
from the provider), so the client-facing id is now the relation's own PK
instead, matching the id already emitted by the read endpoints.

These tests cover the two live playback endpoints directly:

  * valid relation id -> resolves and streams (stream_vod called with the
    correct content uuid)
  * a value that used to be a valid Movie/Episode PK but is NOT a relation id
    -> clean 404, not a crash (this is the exact bug that was crashing in
    production: AttributeError: 'NoneType' object has no attribute 'episode')
  * relation id present but its m3u_account is inactive -> clean 404
  * garbage id -> clean 404
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.views import stream_xc_episode, stream_xc_movie
from apps.vod.models import Episode, M3UEpisodeRelation, M3UMovieRelation, Movie, Series

User = get_user_model()


class XcStreamIdBaseTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='xcstreamuser', password='testpass123')
        self.user.custom_properties = {'xc_password': 'xcpass'}
        self.user.save(update_fields=['custom_properties'])

        self.account = M3UAccount.objects.create(
            name='Provider A',
            server_url='http://a.example.com',
            username='a',
            password='a',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=1,
        )

    def _request(self):
        return self.factory.get('/series/xcstreamuser/xcpass/1.mp4')


class StreamXcMovieTests(XcStreamIdBaseTestCase):
    def setUp(self):
        super().setUp()
        self.movie = Movie.objects.create(name='Some Movie')
        self.relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, stream_id='provider-movie-1',
        )

    @patch('apps.proxy.vod_proxy.views.stream_vod')
    def test_valid_relation_id_streams(self, mock_stream_vod):
        mock_stream_vod.return_value = HttpResponse('STREAMED')
        result = stream_xc_movie(self._request(), 'xcstreamuser', 'xcpass', str(self.relation.id), 'mp4')

        self.assertIs(result, mock_stream_vod.return_value)
        mock_stream_vod.assert_called_once()
        args = mock_stream_vod.call_args[0]
        self.assertEqual(args[1], 'movie')
        self.assertEqual(args[2], self.movie.uuid)

    def test_stale_movie_pk_is_clean_404_not_crash(self):
        """The id that USED to work pre-fix (the Movie's own PK) must now 404
        cleanly rather than crash -- this is the exact regression."""
        response = stream_xc_movie(self._request(), 'xcstreamuser', 'xcpass', str(self.movie.id), 'mp4')
        self.assertEqual(response.status_code, 404)

    def test_inactive_account_is_404(self):
        self.account.is_active = False
        self.account.save(update_fields=['is_active'])
        response = stream_xc_movie(self._request(), 'xcstreamuser', 'xcpass', str(self.relation.id), 'mp4')
        self.assertEqual(response.status_code, 404)

    def test_garbage_id_is_404(self):
        response = stream_xc_movie(self._request(), 'xcstreamuser', 'xcpass', '999999', 'mp4')
        self.assertEqual(response.status_code, 404)


class StreamXcEpisodeTests(XcStreamIdBaseTestCase):
    def setUp(self):
        super().setUp()
        self.series = Series.objects.create(name='Some Series')
        self.episode = Episode.objects.create(series=self.series, name='S1E1', season_number=1, episode_number=1)
        self.relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=self.episode, stream_id='provider-episode-1',
        )

    @patch('apps.proxy.vod_proxy.views.stream_vod')
    def test_valid_relation_id_streams(self, mock_stream_vod):
        mock_stream_vod.return_value = HttpResponse('STREAMED')
        result = stream_xc_episode(self._request(), 'xcstreamuser', 'xcpass', str(self.relation.id), 'mp4')

        self.assertIs(result, mock_stream_vod.return_value)
        mock_stream_vod.assert_called_once()
        args = mock_stream_vod.call_args[0]
        self.assertEqual(args[1], 'episode')
        self.assertEqual(args[2], self.episode.uuid)

    def test_stale_episode_pk_is_clean_404_not_crash(self):
        """The id that USED to work pre-fix (the Episode's own PK) must now
        404 cleanly rather than crash with AttributeError -- this is the exact
        bug reproduced live against a disposable Dispatcharr container before
        this fix, and reported upstream."""
        response = stream_xc_episode(self._request(), 'xcstreamuser', 'xcpass', str(self.episode.id), 'mp4')
        self.assertEqual(response.status_code, 404)

    def test_inactive_account_is_404(self):
        self.account.is_active = False
        self.account.save(update_fields=['is_active'])
        response = stream_xc_episode(self._request(), 'xcstreamuser', 'xcpass', str(self.relation.id), 'mp4')
        self.assertEqual(response.status_code, 404)

    def test_garbage_id_is_404(self):
        response = stream_xc_episode(self._request(), 'xcstreamuser', 'xcpass', '999999', 'mp4')
        self.assertEqual(response.status_code, 404)
