"""
Regression test for stream_xc_episode's stale/missing episode_id crash.

`.filter(...).first()` returns None on no match -- it never raises
M3UEpisodeRelation.DoesNotExist, so the try/except that used to wrap this
lookup was dead code. A stale/missing stream_id (e.g. a client's cached
episode list from before a VOD catalog refresh reassigned internal ids)
fell through to `episode_relation.episode.uuid` on None and crashed with
an unhandled `AttributeError: 'NoneType' object has no attribute
'episode'` instead of returning a clean 404. This is easy to hit in
practice whenever a client (e.g. TiviMate) has cached an episode list and
the backing account's VOD catalog is later refreshed.

The fix replaces the dead try/except with a direct `if not
episode_relation` check -- the same pattern stream_xc_movie (immediately
above this function in views.py) already uses.
"""

from unittest.mock import MagicMock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase


class TestStreamXcEpisodeMissingRelation(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, stream_id='missing-id'):
        # @api_view wraps this in DRF's dispatch, which asserts the request
        # is a real HttpRequest (a bare MagicMock fails that isinstance
        # check) -- same RequestFactory pattern test_vod_db_cleanup.py
        # already uses for other views in this module.
        from apps.proxy.vod_proxy.views import stream_xc_episode

        request = self.factory.get(f'/series/testuser/testpass/{stream_id}.mp4')
        return stream_xc_episode(request, 'testuser', 'testpass', stream_id, 'mp4')

    def _mock_user(self):
        user = MagicMock()
        user.custom_properties = {'xc_password': 'testpass'}
        return user

    def test_missing_relation_returns_clean_404_not_500(self):
        """Pre-fix, this raised AttributeError instead of returning a
        JsonResponse -- Django would surface that as an unhandled 500."""
        with patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True), \
             patch('apps.proxy.vod_proxy.views.get_object_or_404', return_value=self._mock_user()), \
             patch('apps.vod.models.M3UEpisodeRelation') as RelMock:
            RelMock.objects.select_related.return_value.filter.return_value \
                .order_by.return_value.first.return_value = None

            response = self._call(stream_id='stale-id')

            self.assertEqual(response.status_code, 404)

    def test_valid_relation_still_streams(self):
        """Happy path unchanged: a real relation still resolves and is
        handed off to stream_vod with the episode's uuid."""
        episode = MagicMock(uuid='real-uuid')
        relation = MagicMock(episode=episode)

        with patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True), \
             patch('apps.proxy.vod_proxy.views.get_object_or_404', return_value=self._mock_user()), \
             patch('apps.vod.models.M3UEpisodeRelation') as RelMock, \
             patch('apps.proxy.vod_proxy.views.stream_vod', return_value=HttpResponse('STREAMED')) as stream_vod_mock:
            RelMock.objects.select_related.return_value.filter.return_value \
                .order_by.return_value.first.return_value = relation

            result = self._call(stream_id='real-id')

            stream_vod_mock.assert_called_once()
            self.assertEqual(stream_vod_mock.call_args[0][2], 'real-uuid')
            self.assertEqual(result.content, b'STREAMED')
