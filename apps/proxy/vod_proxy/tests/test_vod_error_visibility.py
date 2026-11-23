from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from apps.proxy.vod_proxy.multi_worker_connection_manager import MultiWorkerVODConnectionManager
from apps.proxy.vod_proxy.views import head_vod, stream_vod
from apps.proxy.vod_proxy.utils import vod_error_response


SECRET_ERROR = 'provider http://example.test/movie/user/secret/123.mkv <script>bad</script>'


class VodErrorVisibilityTests(SimpleTestCase):
    def assert_safe_error(self, response, prefix):
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.content.decode().startswith(prefix + ': '))
        self.assertNotIn(b'example.test', response.content)
        self.assertNotIn(b'/user/secret/', response.content)
        self.assertEqual(response['Content-Type'], 'text/plain')

    @patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True)
    @patch('apps.proxy.vod_proxy.views.get_client_info', side_effect=RuntimeError(SECRET_ERROR))
    def test_anonymous_stream_and_head_hide_exception_details(self, _client_info, _network):
        factory = APIRequestFactory()
        for view, request, message in (
            (stream_vod, factory.get('/proxy/vod/movie/example'), 'Streaming error'),
            (head_vod, factory.head('/proxy/vod/movie/example'), 'HEAD error'),
        ):
            with self.subTest(message=message):
                response = view(request, content_type='movie', content_id='example')
                self.assert_safe_error(response, message)

    @patch('apps.proxy.vod_proxy.multi_worker_connection_manager.RedisBackedVODConnection',
           side_effect=RuntimeError(SECRET_ERROR))
    def test_connection_manager_hides_exception_details(self, _connection):
        manager = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        manager.worker_id = 'test'
        manager.redis_client = MagicMock()
        response = manager.stream_content_with_session(
            session_id='test', content_obj=MagicMock(uuid='test', name='test'),
            stream_url='http://example.test/movie/user/secret/123.mkv',
            m3u_profile=MagicMock(), client_ip='127.0.0.1',
            client_user_agent='test', request=APIRequestFactory().get('/'),
        )
        self.assert_safe_error(response, 'Streaming error')

    def test_preserves_diagnostic_text_as_plain_text(self):
        response = vod_error_response(RuntimeError(SECRET_ERROR))
        self.assert_safe_error(response, 'Streaming error')
        self.assertIn(b'<script>bad</script>', response.content)
