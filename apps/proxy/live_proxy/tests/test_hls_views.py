"""HLS playlist/segment HTTP session edge cases (410/404 paths)."""

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.http import JsonResponse
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


class WaitForPlaylistTests(SimpleTestCase):
    """_wait_for_playlist driven by a fake clock (sleep advances time)."""

    BODY = '{"window": []}'

    def setUp(self):
        self.clock = [0.0]
        self.sleeps = []

        def fake_sleep(seconds):
            self.sleeps.append(seconds)
            self.clock[0] += seconds

        fake_time = SimpleNamespace(time=time.time, monotonic=lambda: self.clock[0])
        base = "apps.proxy.live_proxy.output.hls.views"
        patches = [
            patch(f"{base}.time", fake_time),
            patch(f"{base}.gevent.sleep", side_effect=fake_sleep),
            patch(f"{base}.ConfigHelper.channel_init_grace_period", return_value=60),
            patch(
                f"{base}.ConfigHelper.get",
                side_effect=lambda key, default=None: default,
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _redis(self, poll):
        """poll(now) -> (playlist, output_state, channel_state, stopping, client_stop)."""
        redis = MagicMock()
        redis.get.return_value = None
        pipe = redis.pipeline.return_value
        pipe.execute.side_effect = lambda: poll(self.clock[0])
        return redis

    def _wait(self, redis):
        return hls_views._wait_for_playlist(
            redis, TOKEN, CHANNEL_ID, CLIENT_ID, "hls"
        )

    def test_published_playlist_returns_without_polling_pipeline(self):
        redis = MagicMock()
        redis.get.return_value = self.BODY
        self.assertEqual(self._wait(redis), (self.BODY, None))
        redis.pipeline.assert_not_called()

    def test_starting_channel_waits_for_init_grace_then_gives_up(self):
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        with patch.object(hls_views, "touch_hls_session", return_value=(None, None)):
            self.assertEqual(self._wait(redis), (None, None))
        self.assertGreaterEqual(self.clock[0], 60)
        self.assertLess(self.clock[0], 61)

    def test_missing_channel_metadata_is_treated_as_starting(self):
        redis = self._redis(lambda now: (None, None, None, 0, 0))
        with patch.object(hls_views, "touch_hls_session", return_value=(None, None)):
            self.assertEqual(self._wait(redis), (None, None))
        self.assertGreaterEqual(self.clock[0], 60)

    def test_ready_channel_gives_up_after_short_wait(self):
        redis = self._redis(lambda now: (None, None, "active", 0, 0))
        with patch.object(hls_views, "touch_hls_session", return_value=(None, None)):
            self.assertEqual(self._wait(redis), (None, None))
        self.assertGreaterEqual(self.clock[0], hls_views.HLS_READY_PLAYLIST_WAIT_SECONDS)
        self.assertLess(self.clock[0], hls_views.HLS_READY_PLAYLIST_WAIT_SECONDS + 1)

    def test_time_spent_starting_does_not_use_up_the_ready_wait(self):
        """A channel that connects after 30s must still get the ready wait."""

        def poll(now):
            state = "connecting" if now < 30 else "active"
            playlist = self.BODY if now >= 34 else None
            return (playlist, None, state, 0, 0)

        redis = self._redis(poll)
        with patch.object(hls_views, "touch_hls_session", return_value=(None, None)):
            self.assertEqual(self._wait(redis), (self.BODY, None))
        self.assertGreaterEqual(self.clock[0], 34)

    def test_dead_channel_state_returns_410_and_drops_session(self):
        for state in ("error", "stopping", "stopped"):
            redis = self._redis(lambda now, s=state: (None, None, s, 0, 0))
            playlist, response = self._wait(redis)
            self.assertIsNone(playlist, msg=state)
            self.assertEqual(response.status_code, 410, msg=state)
            redis.delete.assert_called_with(RedisKeys.hls_session(TOKEN))

    def test_stopping_or_client_stop_flags_return_410(self):
        for flags in ((1, 0), (0, 1)):
            redis = self._redis(
                lambda now, f=flags: (None, None, "connecting", f[0], f[1])
            )
            playlist, response = self._wait(redis)
            self.assertIsNone(playlist, msg=flags)
            self.assertEqual(response.status_code, 410, msg=flags)

    def test_output_state_stopped_returns_410(self):
        redis = self._redis(lambda now: (None, "stopped", "active", 0, 0))
        _, response = self._wait(redis)
        self.assertEqual(response.status_code, 410)

    def test_wait_keeps_client_alive_well_inside_ghost_timeout(self):
        """last_active only advances on touch; ghost timeout is 12s by default."""
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        touch_times = []

        def fake_touch(_redis, _token):
            touch_times.append(self.clock[0])
            return (None, None)

        with patch.object(hls_views, "touch_hls_session", side_effect=fake_touch):
            self._wait(redis)

        gaps = [b - a for a, b in zip([0.0] + touch_times, touch_times)]
        self.assertGreater(len(touch_times), 10)
        self.assertLess(max(gaps), 12)

    def test_touch_reporting_lapsed_client_ends_wait_with_410(self):
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        with patch.object(hls_views, "touch_hls_session", return_value=(None, "lapsed")):
            playlist, response = self._wait(redis)
        self.assertIsNone(playlist)
        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Session expired", response.content)

    def test_touch_interval_scales_with_ghost_timeout(self):
        base = "apps.proxy.live_proxy.output.hls.views.ConfigHelper.get"
        with patch(base, side_effect=lambda key, default=None: default):
            self.assertEqual(hls_views._touch_interval_seconds(), 3.0)
        values = {"HLS_SEGMENT_DURATION": 1, "HLS_CLIENT_GHOST_SEGMENTS": 3}
        with patch(base, side_effect=lambda key, default=None: values.get(key, default)):
            self.assertEqual(hls_views._touch_interval_seconds(), 0.75)


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

    @patch("apps.proxy.live_proxy.output.hls.views._wait_for_playlist")
    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_exhausted_wait_returns_503_with_retry_after(
        self, mock_proxy_cls, _network, _close, mock_wait
    ):
        redis = MagicMock()
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls"]
        )
        mock_wait.return_value = (None, None)

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "2")

    @patch("apps.proxy.live_proxy.output.hls.views._wait_for_playlist")
    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_wait_error_response_is_returned_as_is(
        self, mock_proxy_cls, _network, _close, mock_wait
    ):
        redis = MagicMock()
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls"]
        )
        mock_wait.return_value = (
            None,
            JsonResponse({"error": "Stream stopped"}, status=410),
        )

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Stream stopped", response.content)

    @patch("apps.proxy.live_proxy.output.hls.views._wait_for_playlist")
    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_playlist_published_during_wait_is_rendered(
        self, mock_proxy_cls, _network, _close, mock_wait
    ):
        redis = MagicMock()
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls"]
        )
        mock_wait.return_value = (
            json.dumps({
                "window": [{"seq": 1, "dur": 4.0, "disc": False}],
                "target": 4,
                "adv_target": 6,
                "disc_seq": 0,
                "ts": time.time(),
            }),
            None,
        )

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"#EXT-X-MEDIA-SEQUENCE:1", response.content)


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
