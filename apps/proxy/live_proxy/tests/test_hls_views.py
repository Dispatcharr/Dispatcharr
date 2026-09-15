"""HLS playlist/segment HTTP session edge cases (410 paths)."""

import json
import time
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.proxy.live_proxy.output.hls import views as hls_views
from apps.proxy.live_proxy.redis_keys import RedisKeys


CHANNEL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLIENT_ID = "client-1"


class PlaylistStaleHelperTests(SimpleTestCase):
    def test_missing_timestamp_is_not_stale(self):
        self.assertFalse(hls_views._playlist_is_stale({"window": [], "adv_target": 8}))

    def test_recent_timestamp_is_not_stale(self):
        state = {"ts": time.time() - 5, "adv_target": 8}
        self.assertFalse(hls_views._playlist_is_stale(state))

    def test_old_timestamp_is_stale(self):
        state = {"ts": time.time() - 120, "adv_target": 8}
        self.assertTrue(hls_views._playlist_is_stale(state))

    def test_stale_limit_scales_with_adv_target(self):
        # 3 * adv_target can exceed the 45s floor.
        state = {"ts": time.time() - 50, "adv_target": 30}  # limit = 90
        self.assertFalse(hls_views._playlist_is_stale(state))
        state["ts"] = time.time() - 100
        self.assertTrue(hls_views._playlist_is_stale(state))


class HLSPlaylistViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self):
        return self.factory.get(
            f"/proxy/hls/{CHANNEL_ID}/{CLIENT_ID}/index.m3u8"
        )

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_session_gone_returns_410(self, mock_proxy_cls, _network, _close):
        redis = MagicMock()
        redis.exists.return_value = True  # channel_stopping or client_stop
        proxy = MagicMock()
        proxy.redis_client = redis
        mock_proxy_cls.get_instance.return_value = proxy

        response = hls_views.hls_playlist(self._request(), CHANNEL_ID, CLIENT_ID)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Stream stopped", response.content)

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_lapsed_client_returns_410_without_reregister(
        self, mock_proxy_cls, _network, _close
    ):
        redis = MagicMock()
        redis.exists.return_value = False
        redis.hgetall.return_value = {}  # metadata gone
        proxy = MagicMock()
        proxy.redis_client = redis
        mock_proxy_cls.get_instance.return_value = proxy

        response = hls_views.hls_playlist(self._request(), CHANNEL_ID, CLIENT_ID)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Session expired", response.content)
        redis.srem.assert_called_once_with(
            RedisKeys.clients(CHANNEL_ID), CLIENT_ID
        )
        # Must not recreate the client hash from nothing.
        pipe = redis.pipeline.return_value
        self.assertFalse(pipe.hset.called)

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_stale_playlist_descriptor_returns_410(
        self, mock_proxy_cls, _network, _close
    ):
        redis = MagicMock()
        redis.exists.return_value = False
        redis.hgetall.return_value = {"output_format": "hls"}
        stale = json.dumps({
            "window": [{"seq": 1, "dur": 4.0, "disc": False}],
            "target": 4,
            "adv_target": 8,
            "disc_seq": 0,
            "ts": time.time() - 120,
        })
        redis.get.return_value = stale
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        proxy = MagicMock()
        proxy.redis_client = redis
        mock_proxy_cls.get_instance.return_value = proxy

        response = hls_views.hls_playlist(self._request(), CHANNEL_ID, CLIENT_ID)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Stream stopped", response.content)

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_fresh_playlist_returns_m3u8(self, mock_proxy_cls, _network, _close):
        redis = MagicMock()
        redis.exists.return_value = False
        redis.hgetall.return_value = {"output_format": "hls"}
        body = json.dumps({
            "window": [{"seq": 7, "dur": 4.0, "disc": False}],
            "target": 4,
            "adv_target": 8,
            "disc_seq": 0,
            "ts": time.time(),
        })
        redis.get.return_value = body
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        proxy = MagicMock()
        proxy.redis_client = redis
        mock_proxy_cls.get_instance.return_value = proxy

        response = hls_views.hls_playlist(self._request(), CHANNEL_ID, CLIENT_ID)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.apple.mpegurl")
        self.assertIn(b"#EXTM3U", response.content)
        self.assertIn(b"#EXT-X-MEDIA-SEQUENCE:7", response.content)


class HLSSegmentViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self):
        return self.factory.get(
            f"/proxy/hls/{CHANNEL_ID}/{CLIENT_ID}/3.ts"
        )

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_lapsed_client_returns_410(self, mock_proxy_cls, _network, _close):
        redis = MagicMock()
        redis.exists.return_value = False
        redis.hgetall.return_value = {}
        proxy = MagicMock()
        proxy.redis_client = redis
        mock_proxy_cls.get_instance.return_value = proxy

        response = hls_views.hls_segment(self._request(), CHANNEL_ID, CLIENT_ID, 3)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Session expired", response.content)
