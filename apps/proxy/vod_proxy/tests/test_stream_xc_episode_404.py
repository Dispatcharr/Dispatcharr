"""stream_xc_episode returns 404 when no M3U episode relation exists."""

from unittest.mock import MagicMock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase


class TestStreamXcEpisodeMissingRelation(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, stream_id='missing-id'):
        from apps.proxy.vod_proxy.views import stream_xc_episode

        request = self.factory.get(f'/series/testuser/testpass/{stream_id}.mp4')
        return stream_xc_episode(request, 'testuser', 'testpass', stream_id, 'mp4')

    def _mock_user(self):
        user = MagicMock()
        user.custom_properties = {'xc_password': 'testpass'}
        return user

    def test_missing_relation_returns_clean_404_not_500(self):
        with patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True), \
             patch('apps.proxy.vod_proxy.views.get_object_or_404', return_value=self._mock_user()), \
             patch('apps.vod.models.M3UEpisodeRelation') as RelMock:
            RelMock.objects.select_related.return_value.filter.return_value \
                .order_by.return_value.first.return_value = None

            response = self._call(stream_id='stale-id')

            self.assertEqual(response.status_code, 404)

    def test_valid_relation_still_streams(self):
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
