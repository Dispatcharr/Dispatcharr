"""VOD proxy must release geventpool checkouts after ORM on stream and stats paths."""

from unittest.mock import MagicMock, patch

from django.http import StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase


class StreamVodDbCleanupTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager")
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=False,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_stream_vod_closes_db_before_streaming_response(
        self,
        _network_ok,
        _is_redirect,
        mock_select,
        mock_manager_cls,
        mock_close,
    ):
        movie = MagicMock()
        movie.name = "Test Movie"
        profile = MagicMock()
        profile.id = 1
        profile.max_streams = 5
        mock_select.return_value = {
            "content_obj": movie,
            "m3u_account": MagicMock(name="Provider"),
            "m3u_profile": profile,
            "current_connections": 0,
            "final_stream_url": "http://example.com/movie.mp4",
        }

        mock_manager = MagicMock()
        mock_manager.stream_content_with_session.return_value = StreamingHttpResponse(
            streaming_content=iter([b"data"]),
            content_type="video/mp4",
        )
        mock_manager_cls.get_instance.return_value = mock_manager

        request = self.factory.get(
            "/proxy/vod/movie/uuid/session123/",
            HTTP_USER_AGENT="test-agent",
        )
        request.user = MagicMock(is_authenticated=False)

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            request,
            content_type="movie",
            content_id="uuid",
            session_id="session123",
        )

        self.assertIsInstance(response, StreamingHttpResponse)
        mock_close.assert_called_once()
        mock_manager.stream_content_with_session.assert_called_once()


class BuildVodStatsDbCleanupTests(SimpleTestCase):
    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views.Movie")
    def test_build_vod_stats_data_closes_db(self, mock_movie, mock_close):
        redis_client = MagicMock()
        redis_client.scan.side_effect = [
            (0, ["vod_persistent_connection:s1"]),
        ]
        redis_client.hgetall.return_value = {
            "content_obj_type": "movie",
            "content_uuid": "movie-uuid",
            "content_name": "Test Movie",
            "m3u_profile_id": "1",
            "client_ip": "127.0.0.1",
            "client_user_agent": "agent",
            "connected_at": "1000.0",
            "last_activity": "1001.0",
            "active_streams": "1",
        }

        movie_obj = MagicMock(
            name="Test Movie",
            logo=None,
            year=2020,
            rating=7.5,
            genre="Action",
            description="Desc",
            tmdb_id="1",
            imdb_id="tt1",
        )
        mock_movie.objects.select_related.return_value.get.return_value = movie_obj

        with patch("apps.m3u.models.M3UAccountProfile") as mock_profile_model:
            mock_profile_model.objects.select_related.return_value.get.return_value = MagicMock(
                name="Profile 1",
                m3u_account=MagicMock(name="Account", id=1),
            )

            from apps.proxy.vod_proxy.views import build_vod_stats_data

            stats = build_vod_stats_data(redis_client)

        self.assertEqual(stats["total_connections"], 1)
        mock_close.assert_called_once()

    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    def test_build_vod_stats_data_closes_db_on_error(self, mock_close):
        redis_client = MagicMock()
        redis_client.scan.side_effect = RuntimeError("redis down")

        from apps.proxy.vod_proxy.views import build_vod_stats_data

        stats = build_vod_stats_data(redis_client)

        self.assertEqual(stats["total_connections"], 0)
        mock_close.assert_called_once()


class VodStatsUpdateDbCleanupTests(SimpleTestCase):
    @patch("core.utils.send_websocket_update")
    @patch("apps.proxy.vod_proxy.views.build_vod_stats_data")
    def test_do_vod_stats_update_uses_build_vod_stats_data(self, mock_build, mock_ws):
        mock_build.return_value = {
            "vod_connections": [],
            "total_connections": 0,
            "timestamp": 0,
        }

        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        manager = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        manager.redis_client = MagicMock()

        manager._do_vod_stats_update()

        mock_build.assert_called_once_with(manager.redis_client)
        mock_ws.assert_called_once()
