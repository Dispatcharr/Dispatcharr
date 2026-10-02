"""HLS playlist/segment HTTP session edge cases (410/404 paths)."""

import json
import time
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.proxy.live_proxy.output.hls import session as hls_session
from apps.proxy.live_proxy.output.hls import views as hls_views
from apps.proxy.live_proxy.redis_keys import RedisKeys


CHANNEL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLIENT_ID = "client-1"
TOKEN = "opaque-hls-token"


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


class MintHlsSessionTests(SimpleTestCase):
    def setUp(self):
        hls_session._script_cache.clear()

    def test_mint_stores_channel_client_and_token_on_client_hash(self):
        redis = MagicMock()
        script = MagicMock(return_value=1)
        redis.register_script.return_value = script

        with patch(
            "apps.proxy.live_proxy.output.hls.session.ConfigHelper.get",
            return_value=60,
        ), patch(
            "apps.proxy.live_proxy.output.hls.session.secrets.token_urlsafe",
            return_value=TOKEN,
        ):
            token = hls_session.mint_hls_session(redis, CHANNEL_ID, CLIENT_ID)

        self.assertEqual(token, TOKEN)
        redis.register_script.assert_called_once()
        script.assert_called_once_with(
            keys=[
                RedisKeys.client_metadata(CHANNEL_ID, CLIENT_ID),
                RedisKeys.hls_session(TOKEN),
            ],
            args=[CHANNEL_ID, CLIENT_ID, TOKEN, 60, "0"],
        )

    def test_mint_stores_user_id_when_provided(self):
        redis = MagicMock()
        script = MagicMock(return_value=1)
        redis.register_script.return_value = script

        with patch(
            "apps.proxy.live_proxy.output.hls.session.ConfigHelper.get",
            return_value=60,
        ), patch(
            "apps.proxy.live_proxy.output.hls.session.secrets.token_urlsafe",
            return_value=TOKEN,
        ):
            token = hls_session.mint_hls_session(
                redis, CHANNEL_ID, CLIENT_ID, user_id=42
            )

        self.assertEqual(token, TOKEN)
        script.assert_called_once_with(
            keys=[
                RedisKeys.client_metadata(CHANNEL_ID, CLIENT_ID),
                RedisKeys.hls_session(TOKEN),
            ],
            args=[CHANNEL_ID, CLIENT_ID, TOKEN, 60, "42"],
        )

    def test_mint_returns_none_without_redis(self):
        self.assertIsNone(hls_session.mint_hls_session(None, CHANNEL_ID, CLIENT_ID))

    def test_mint_returns_none_when_client_record_missing(self):
        redis = MagicMock()
        script = MagicMock(return_value=0)
        redis.register_script.return_value = script

        with patch(
            "apps.proxy.live_proxy.output.hls.session.secrets.token_urlsafe",
            return_value=TOKEN,
        ):
            token = hls_session.mint_hls_session(redis, CHANNEL_ID, CLIENT_ID)

        self.assertIsNone(token)
        script.assert_called_once()
        redis.pipeline.assert_not_called()
        redis.hset.assert_not_called()


class TouchHlsSessionTests(SimpleTestCase):
    def setUp(self):
        hls_session._script_cache.clear()

    def _redis_with_touch(self, result):
        redis = MagicMock()
        script = MagicMock(return_value=result)
        redis.register_script.return_value = script
        return redis, script

    def test_touch_returns_channel_client_and_hash_when_live(self):
        redis, script = self._redis_with_touch(
            [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls", "output_profile_id", ""]
        )

        with patch(
            "apps.proxy.live_proxy.output.hls.session.ConfigHelper.get",
            return_value=60,
        ):
            loaded, reason = hls_session.touch_hls_session(redis, TOKEN)

        self.assertIsNone(reason)
        channel_id, client_id, client_hash = loaded
        self.assertEqual(channel_id, CHANNEL_ID)
        self.assertEqual(client_id, CLIENT_ID)
        self.assertEqual(client_hash["output_format"], "hls")
        script.assert_called_once_with(
            keys=[RedisKeys.hls_session(TOKEN)],
            args=[script.call_args.kwargs["args"][0], 60, TOKEN],
        )
        redis.hgetall.assert_not_called()
        redis.hset.assert_not_called()
        redis.pipeline.assert_not_called()

    def test_touch_expired_does_not_recreate_client(self):
        redis, _script = self._redis_with_touch([0])
        loaded, reason = hls_session.touch_hls_session(redis, TOKEN)
        self.assertIsNone(loaded)
        self.assertEqual(reason, "expired")
        redis.hset.assert_not_called()
        redis.sadd.assert_not_called()

    def test_touch_stopped_does_not_recreate_client(self):
        redis, _script = self._redis_with_touch([1])
        loaded, reason = hls_session.touch_hls_session(redis, TOKEN)
        self.assertIsNone(loaded)
        self.assertEqual(reason, "stopped")
        redis.hset.assert_not_called()
        redis.sadd.assert_not_called()

    def test_touch_lapsed_does_not_recreate_client(self):
        redis, _script = self._redis_with_touch([2])
        loaded, reason = hls_session.touch_hls_session(redis, TOKEN)
        self.assertIsNone(loaded)
        self.assertEqual(reason, "lapsed")
        redis.hset.assert_not_called()
        redis.sadd.assert_not_called()


class HLSPlaylistViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        hls_session._script_cache.clear()

    def _request(self):
        return self.factory.get(f"/proxy/hls/{TOKEN}/index.m3u8")

    def _proxy_with_touch(self, redis, touch_result):
        redis.register_script.return_value = MagicMock(return_value=touch_result)
        proxy = MagicMock()
        proxy.redis_client = redis
        return proxy

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_unknown_token_returns_410(self, mock_proxy_cls, _network, _close):
        redis = MagicMock()
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [0]
        )

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Session expired", response.content)
        redis.hset.assert_not_called()
        redis.sadd.assert_not_called()

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_session_gone_returns_410(self, mock_proxy_cls, _network, _close):
        redis = MagicMock()
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [1]
        )

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Stream stopped", response.content)
        redis.hset.assert_not_called()
        redis.sadd.assert_not_called()

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_lapsed_client_returns_410_without_reregister(
        self, mock_proxy_cls, _network, _close
    ):
        redis = MagicMock()
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [2]
        )

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Session expired", response.content)
        redis.hset.assert_not_called()
        redis.sadd.assert_not_called()
        redis.expire.assert_not_called()

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_stale_playlist_descriptor_returns_404(
        self, mock_proxy_cls, _network, _close
    ):
        redis = MagicMock()
        stale = json.dumps({
            "window": [{"seq": 1, "dur": 4.0, "disc": False}],
            "target": 4,
            "adv_target": 8,
            "disc_seq": 0,
            "ts": time.time() - 120,
        })
        redis.get.return_value = stale
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls"]
        )

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Playlist stale", response.content)

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_fresh_playlist_returns_m3u8(self, mock_proxy_cls, _network, _close):
        redis = MagicMock()
        body = json.dumps({
            "window": [{"seq": 7, "dur": 4.0, "disc": False}],
            "target": 4,
            "adv_target": 8,
            "disc_seq": 0,
            "ts": time.time(),
        })
        redis.get.return_value = body
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls"]
        )

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.apple.mpegurl")
        self.assertIn(b"#EXTM3U", response.content)
        self.assertIn(b"#EXT-X-MEDIA-SEQUENCE:7", response.content)
        redis.delete.assert_not_called()
        redis.register_script.return_value.assert_called_once()


class HLSSegmentViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        hls_session._script_cache.clear()

    def _request(self):
        return self.factory.get(f"/proxy/hls/{TOKEN}/3.ts")

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_lapsed_client_returns_410(self, mock_proxy_cls, _network, _close):
        redis = MagicMock()
        redis.register_script.return_value = MagicMock(return_value=[2])
        proxy = MagicMock()
        proxy.redis_client = redis
        mock_proxy_cls.get_instance.return_value = proxy

        response = hls_views.hls_segment(self._request(), TOKEN, 3)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Session expired", response.content)
        redis.hset.assert_not_called()
        redis.sadd.assert_not_called()
