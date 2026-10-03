"""HLS playlist/segment HTTP session edge cases (410/404 paths)."""

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.http import JsonResponse, StreamingHttpResponse
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


def _playlist_json(seq=1, ts=None):
    return json.dumps({
        "window": [{"seq": seq, "dur": 4.0, "disc": False}],
        "target": 4,
        "adv_target": 6,
        "disc_seq": 0,
        "ts": time.time() if ts is None else ts,
    })


class ColdStartPlaylistStreamTests(SimpleTestCase):
    """_cold_start_playlist_chunks driven by a fake clock (sleep advances time)."""

    INIT_GRACE = 60.0

    def setUp(self):
        self.clock = [0.0]

        def fake_sleep(seconds):
            self.clock[0] += seconds

        fake_time = SimpleNamespace(time=time.time, monotonic=lambda: self.clock[0])
        base = "apps.proxy.live_proxy.output.hls.views"
        self.waiter = MagicMock()
        self.waiter.wait.side_effect = lambda timeout=None: fake_sleep(timeout or 0)
        patches = {
            "time": patch(f"{base}.time", fake_time),
            "config": patch(
                f"{base}.ConfigHelper.get",
                side_effect=lambda key, default=None: default,
            ),
            "enter": patch(f"{base}.enter_cold_start", return_value=1),
            "exit": patch(f"{base}.exit_cold_start", return_value=0),
            "spawn_later": patch(f"{base}.gevent.spawn_later"),
            "register": patch(
                f"{base}.register_playlist_waiter", return_value=self.waiter
            ),
            "unregister": patch(f"{base}.unregister_playlist_waiter"),
        }
        for name, p in patches.items():
            setattr(self, f"{name}_mock", p.start())
            self.addCleanup(p.stop)

    def _redis(self, poll):
        """poll(now) -> (playlist, output_state, channel_state, stopping, client_stop)."""
        redis = MagicMock()
        pipe = redis.pipeline.return_value
        pipe.execute.side_effect = lambda: poll(self.clock[0])
        return redis

    def _chunks(self, redis):
        return hls_views._cold_start_playlist_chunks(
            redis, TOKEN, CHANNEL_ID, CLIENT_ID, "hls", self.INIT_GRACE
        )

    def _consume(self, redis, touch_return=(None, None)):
        with patch.object(hls_views, "touch_hls_session", return_value=touch_return):
            return list(self._chunks(redis))

    def test_starts_with_extm3u_then_comments_then_finishes_without_duplicate_header(self):
        playlist = _playlist_json()

        def poll(now):
            return (playlist if now >= 2.5 else None, None, "connecting", 0, 0)

        chunks = self._consume(self._redis(poll))
        self.assertEqual(chunks[0], "#EXTM3U\n")
        self.assertTrue(
            all(c.startswith("# dispatcharr: waiting") for c in chunks[1:-1])
        )
        self.assertGreaterEqual(len(chunks), 4)
        self.assertNotIn("#EXTM3U", chunks[-1])
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:1", chunks[-1])
        self.assertIn("#EXTINF:4.000", chunks[-1])
        # Concatenated, the document is a valid playlist with one header.
        self.assertEqual("".join(chunks).count("#EXTM3U"), 1)

    def test_comments_are_dripped_about_once_per_poll(self):
        redis = self._redis(lambda now: (None, None, "active", 0, 0))
        chunks = self._consume(redis)
        comments = [c for c in chunks if c.startswith("# dispatcharr: waiting")]
        waited = hls_views.HLS_READY_PLAYLIST_WAIT_SECONDS
        expected = waited / hls_views._PLAYLIST_WAIT_POLL_SECONDS
        self.assertGreaterEqual(len(comments), expected - 2)
        self.assertLessEqual(len(comments), expected + 1)

    def test_every_poll_tick_after_the_header_writes_one_comment(self):
        def poll(now):
            return (_playlist_json() if now >= 1.0 else None, None, "connecting", 0, 0)

        chunks = self._consume(self._redis(poll))
        poll_seconds = hls_views._PLAYLIST_WAIT_POLL_SECONDS
        self.assertEqual(chunks[0], "#EXTM3U\n")
        self.assertEqual(
            chunks[1:-1],
            [f"# dispatcharr: waiting {n}\n" for n in range(1, int(1.0 / poll_seconds))],
        )

    def test_starting_channel_times_out_after_init_grace_without_header_only_body(self):
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        chunks = self._consume(redis)
        self.assertEqual(chunks[0], "#EXTM3U\n")
        self.assertTrue(any(c.startswith("# dispatcharr: waiting") for c in chunks))
        # Giving up just ends the response. It must not append a header-only
        # Media Playlist (RFC 8216 section 2: a Media Playlist has segments).
        self.assertNotIn("#EXT-X-TARGETDURATION", "".join(chunks))
        self.assertGreaterEqual(self.clock[0], self.INIT_GRACE)
        self.assertLess(self.clock[0], self.INIT_GRACE + 1)

    def test_missing_channel_metadata_is_treated_as_starting(self):
        redis = self._redis(lambda now: (None, None, None, 0, 0))
        self._consume(redis)
        self.assertGreaterEqual(self.clock[0], self.INIT_GRACE)

    def test_ready_channel_times_out_after_short_wait(self):
        redis = self._redis(lambda now: (None, None, "active", 0, 0))
        chunks = self._consume(redis)
        self.assertGreaterEqual(self.clock[0], hls_views.HLS_READY_PLAYLIST_WAIT_SECONDS)
        self.assertLess(self.clock[0], hls_views.HLS_READY_PLAYLIST_WAIT_SECONDS + 1)
        self.assertNotIn("#EXT-X-TARGETDURATION", "".join(chunks))

    def test_time_spent_starting_does_not_use_up_the_ready_wait(self):
        playlist = _playlist_json()

        def poll(now):
            state = "connecting" if now < 30 else "active"
            return (playlist if now >= 34 else None, None, state, 0, 0)

        chunks = self._consume(self._redis(poll))
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:1", "".join(chunks))
        self.assertGreaterEqual(self.clock[0], 34)

    def test_dead_channel_yields_nothing_and_drops_session(self):
        cases = [
            (None, "error", 0, 0),
            (None, "stopping", 0, 0),
            (None, "stopped", 0, 0),
            (None, "connecting", 1, 0),
            (None, "connecting", 0, 1),
            ("stopped", "active", 0, 0),
        ]
        for output_state, channel_state, stopping, client_stop in cases:
            self.clock[0] = 0.0
            redis = self._redis(
                lambda now, c=(output_state, channel_state, stopping, client_stop): (
                    None, c[0], c[1], c[2], c[3]
                )
            )
            chunks = self._consume(redis)
            self.assertEqual(chunks, [], msg=str((output_state, channel_state, stopping, client_stop)))
            redis.delete.assert_called_with(RedisKeys.hls_session(TOKEN))

    def test_playlist_ready_on_first_poll_sends_full_body_without_comments(self):
        redis = self._redis(lambda now: (_playlist_json(), None, "active", 0, 0))
        chunks = self._consume(redis)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("#EXTM3U\n"))
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:1", chunks[0])
        self.assertNotIn("dispatcharr: waiting", chunks[0])

    def test_unusable_descriptor_ends_stream_without_a_body(self):
        stale = _playlist_json(ts=time.time() - 3600)
        for descriptor in (stale, "{not json", json.dumps({"window": "bad"})):
            self.clock[0] = 0.0
            redis = self._redis(lambda now, d=descriptor: (d, None, "active", 0, 0))
            chunks = self._consume(redis)
            self.assertNotIn("#EXT-X-TARGETDURATION", "".join(chunks), msg=descriptor)
            self.assertLessEqual(len(chunks), 1, msg=descriptor)

    def _disconnect_after_first_chunk(self, redis):
        with patch.object(hls_views, "touch_hls_session", return_value=(None, None)):
            gen = self._chunks(redis)
            self.assertEqual(next(gen), "#EXTM3U\n")
            gen.close()

    def test_stream_is_counted_on_start_and_released_on_finish(self):
        redis = self._redis(lambda now: (_playlist_json(), None, "active", 0, 0))
        self.enter_mock.assert_not_called()
        self._consume(redis)
        self.enter_mock.assert_called_once_with(redis, TOKEN)
        self.exit_mock.assert_called_once_with(redis, TOKEN)
        self.register_mock.assert_called_once_with(CHANNEL_ID, "hls")
        self.unregister_mock.assert_called_once_with(CHANNEL_ID, "hls", self.waiter)
        self.spawn_later_mock.assert_not_called()

    def test_stream_closed_before_it_starts_is_never_counted(self):
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        self._chunks(redis).close()
        self.enter_mock.assert_not_called()
        self.exit_mock.assert_not_called()
        self.register_mock.assert_not_called()
        self.unregister_mock.assert_not_called()
        self.spawn_later_mock.assert_not_called()

    def test_playlist_ready_signal_wakes_the_wait_before_the_poll_timeout(self):
        """A notify mid-wait must not burn the rest of the 250ms tick."""
        wake_at = [None]

        def wait(timeout=None):
            # First wait: return early as if the segmenter signalled.
            # Later waits (should not happen once playlist is seen): full tick.
            if wake_at[0] is None:
                wake_at[0] = self.clock[0]
                self.clock[0] += 0.01
                return
            self.clock[0] += timeout or 0

        self.waiter.wait.side_effect = wait

        def poll(now):
            # Playlist appears right after the early wake.
            ready = wake_at[0] is not None and now >= wake_at[0]
            return (_playlist_json() if ready else None, None, "connecting", 0, 0)

        chunks = self._consume(self._redis(poll))
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:1", "".join(chunks))
        self.assertLess(self.clock[0], 0.25)
        self.assertGreaterEqual(self.clock[0], 0.01)

    def test_last_disconnect_schedules_stop_after_the_reconnect_grace(self):
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        before = time.time()
        self._disconnect_after_first_chunk(redis)
        after = time.time()

        self.exit_mock.assert_called_once_with(redis, TOKEN)
        self.spawn_later_mock.assert_called_once()
        args = self.spawn_later_mock.call_args.args
        self.assertEqual(args[0], 0.5)
        self.assertEqual(args[0], hls_views.HLS_COLD_START_RECONNECT_GRACE_SECONDS)
        self.assertIs(args[1], hls_views._stop_abandoned_cold_start)
        self.assertEqual(args[2:7], (redis, TOKEN, CHANNEL_ID, CLIENT_ID, "hls"))
        self.assertTrue(before <= args[7] <= after)
        # Nothing is torn down synchronously: the session stays usable for a
        # player that reconnects inside the grace.
        redis.delete.assert_not_called()

    def test_disconnect_with_another_request_still_held_does_not_schedule_stop(self):
        self.exit_mock.return_value = 1
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        self._disconnect_after_first_chunk(redis)
        self.exit_mock.assert_called_once_with(redis, TOKEN)
        self.spawn_later_mock.assert_not_called()

    def test_disconnect_after_session_is_gone_does_not_schedule_stop(self):
        self.exit_mock.return_value = None
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        self._disconnect_after_first_chunk(redis)
        self.spawn_later_mock.assert_not_called()

    def test_endings_that_are_not_a_disconnect_never_schedule_stop(self):
        timed_out = self._redis(lambda now: (None, None, "connecting", 0, 0))
        dead = self._redis(lambda now: (None, None, "error", 0, 0))
        for redis in (timed_out, dead):
            self.clock[0] = 0.0
            self._consume(redis)
            self.exit_mock.assert_called_with(redis, TOKEN)
        lapsed = self._redis(lambda now: (None, None, "connecting", 0, 0))
        self.clock[0] = 0.0
        self._consume(lapsed, touch_return=(None, "lapsed"))
        self.assertEqual(self.exit_mock.call_count, 3)
        self.spawn_later_mock.assert_not_called()

    def test_uncounted_stream_does_not_release_or_schedule(self):
        for entered in (None, RuntimeError("redis down")):
            self.enter_mock.reset_mock(return_value=True, side_effect=True)
            self.exit_mock.reset_mock()
            if isinstance(entered, Exception):
                self.enter_mock.side_effect = entered
            else:
                self.enter_mock.return_value = entered
            redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
            self._disconnect_after_first_chunk(redis)
            self.exit_mock.assert_not_called()
            self.spawn_later_mock.assert_not_called()

    def test_failing_release_does_not_break_the_close(self):
        self.exit_mock.side_effect = RuntimeError("redis down")
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        self._disconnect_after_first_chunk(redis)
        self.spawn_later_mock.assert_not_called()

    def test_wait_keeps_client_alive_well_inside_ghost_timeout(self):
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        touch_times = []

        def fake_touch(_redis, _token):
            touch_times.append(self.clock[0])
            return (None, None)

        with patch.object(hls_views, "touch_hls_session", side_effect=fake_touch):
            list(self._chunks(redis))

        gaps = [b - a for a, b in zip([0.0] + touch_times, touch_times)]
        self.assertGreater(len(touch_times), 10)
        self.assertLess(max(gaps), 12)

    def test_touch_reporting_lapsed_ends_stream_without_extra_delete(self):
        redis = self._redis(lambda now: (None, None, "connecting", 0, 0))
        chunks = self._consume(redis, touch_return=(None, "lapsed"))
        self.assertEqual(chunks[0], "#EXTM3U\n")
        self.assertNotIn("#EXT-X-TARGETDURATION", "".join(chunks))
        # The touch script already forgot the session; no second delete.
        redis.delete.assert_not_called()
        self.assertLess(self.clock[0], self.INIT_GRACE)

    def test_touch_interval_scales_with_ghost_timeout(self):
        base = "apps.proxy.live_proxy.output.hls.views.ConfigHelper.get"
        with patch(base, side_effect=lambda key, default=None: default):
            self.assertEqual(hls_views._touch_interval_seconds(), 3.0)
        values = {"HLS_SEGMENT_DURATION": 1, "HLS_CLIENT_GHOST_SEGMENTS": 3}
        with patch(base, side_effect=lambda key, default=None: values.get(key, default)):
            self.assertEqual(hls_views._touch_interval_seconds(), 0.75)


class StopAbandonedColdStartTests(SimpleTestCase):
    """The delayed stop that runs once the reconnect grace has passed."""

    def _run(self, claim_result=None, claim_error=None, stop_error=None):
        redis = MagicMock()
        base = "apps.proxy.live_proxy.output.hls.views"
        with patch(
            f"{base}.claim_abandoned_session",
            return_value=claim_result,
            side_effect=claim_error,
        ) as claim, patch(
            f"{base}.ChannelService.stop_client", side_effect=stop_error
        ) as stop_client:
            hls_views._stop_abandoned_cold_start(
                redis, TOKEN, CHANNEL_ID, CLIENT_ID, "hls", 123.5
            )
        return redis, claim, stop_client

    def test_claimed_session_stops_the_client(self):
        redis, claim, stop_client = self._run(claim_result=(CHANNEL_ID, CLIENT_ID))
        claim.assert_called_once_with(
            redis, TOKEN, RedisKeys.output_playlist(CHANNEL_ID, "hls"), 123.5
        )
        stop_client.assert_called_once_with(CHANNEL_ID, CLIENT_ID)

    def test_player_that_came_back_is_left_alone(self):
        _redis, _claim, stop_client = self._run(claim_result=None)
        stop_client.assert_not_called()

    def test_playlist_key_follows_the_clients_output_format(self):
        redis = MagicMock()
        base = "apps.proxy.live_proxy.output.hls.views"
        with patch(f"{base}.claim_abandoned_session", return_value=None) as claim:
            hls_views._stop_abandoned_cold_start(
                redis, TOKEN, CHANNEL_ID, CLIENT_ID, "hls:p7", 1.0
            )
        self.assertEqual(
            claim.call_args.args[2], RedisKeys.output_playlist(CHANNEL_ID, "hls:p7")
        )

    def test_redis_failure_is_contained(self):
        _redis, _claim, stop_client = self._run(claim_error=RuntimeError("down"))
        stop_client.assert_not_called()

    def test_stop_failure_is_contained(self):
        self._run(
            claim_result=(CHANNEL_ID, CLIENT_ID), stop_error=RuntimeError("boom")
        )


class ColdStartCountHelperTests(SimpleTestCase):
    """Python wrappers around the cold-start count / claim scripts."""

    def setUp(self):
        hls_session._script_cache.clear()

    def _redis(self, result):
        redis = MagicMock()
        script = MagicMock(return_value=result)
        redis.register_script.return_value = script
        return redis, script

    def test_enter_returns_the_new_count(self):
        redis, script = self._redis(2)
        self.assertEqual(hls_session.enter_cold_start(redis, TOKEN), 2)
        script.assert_called_once_with(keys=[RedisKeys.hls_session(TOKEN)])

    def test_enter_and_exit_report_a_missing_session_as_none(self):
        redis, _script = self._redis(-1)
        self.assertIsNone(hls_session.enter_cold_start(redis, TOKEN))
        self.assertIsNone(hls_session.exit_cold_start(redis, TOKEN))

    def test_exit_returns_what_is_still_held(self):
        redis, script = self._redis(0)
        self.assertEqual(hls_session.exit_cold_start(redis, TOKEN), 0)
        script.assert_called_once_with(keys=[RedisKeys.hls_session(TOKEN)])

    def test_claim_returns_channel_and_client_when_taken(self):
        redis, script = self._redis([1, CHANNEL_ID, CLIENT_ID])
        playlist_key = RedisKeys.output_playlist(CHANNEL_ID, "hls")
        claimed = hls_session.claim_abandoned_session(
            redis, TOKEN, playlist_key, 1700000000.25
        )
        self.assertEqual(claimed, (CHANNEL_ID, CLIENT_ID))
        script.assert_called_once_with(
            keys=[RedisKeys.hls_session(TOKEN), playlist_key],
            args=["1700000000.25"],
        )

    def test_claim_returns_none_when_not_taken(self):
        for result in ([0], [], None):
            redis, _script = self._redis(result)
            self.assertIsNone(
                hls_session.claim_abandoned_session(redis, TOKEN, "playlist", 1.0),
                msg=str(result),
            )


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
    def test_malformed_playlist_descriptor_returns_500_not_stale(
        self, mock_proxy_cls, _network, _close
    ):
        """Bad JSON is a ValueError too; it must not be reported as stale."""
        for descriptor in ("{not json", json.dumps({"window": "bad"})):
            redis = MagicMock()
            redis.get.return_value = descriptor
            mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
                redis, [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls"]
            )

            response = hls_views.hls_playlist(self._request(), TOKEN)

            self.assertEqual(response.status_code, 500, msg=descriptor)
            self.assertIn(b"Playlist unavailable", response.content)

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
        redis.pipeline.assert_not_called()

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_missing_playlist_returns_streaming_response(
        self, mock_proxy_cls, _network, _close
    ):
        redis = MagicMock()
        redis.get.return_value = None
        # Precheck poll: not published, not dead
        redis.pipeline.return_value.execute.return_value = (
            None, None, "connecting", 0, 0
        )
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls"]
        )

        with patch.object(
            hls_views,
            "_cold_start_playlist_chunks",
            return_value=iter(["#EXTM3U\n", "#EXT-X-VERSION:3\n"]),
        ) as chunks, patch(
            "apps.proxy.live_proxy.output.hls.views.ConfigHelper.channel_init_grace_period",
            return_value=45,
        ):
            response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.apple.mpegurl")
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(
            b"".join(response.streaming_content), b"#EXTM3U\n#EXT-X-VERSION:3\n"
        )
        # Resolved in the view (ORM-capable), before the connection is released.
        chunks.assert_called_once_with(
            redis, TOKEN, CHANNEL_ID, CLIENT_ID, "hls", 45.0
        )

    @patch("apps.proxy.live_proxy.output.hls.views.close_old_connections")
    @patch("apps.proxy.live_proxy.output.hls.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.live_proxy.output.hls.views.ProxyServer")
    def test_dead_channel_before_stream_returns_410(
        self, mock_proxy_cls, _network, _close
    ):
        redis = MagicMock()
        redis.get.return_value = None
        redis.pipeline.return_value.execute.return_value = (
            None, None, "error", 0, 0
        )
        mock_proxy_cls.get_instance.return_value = self._proxy_with_touch(
            redis, [3, CHANNEL_ID, CLIENT_ID, "output_format", "hls"]
        )

        response = hls_views.hls_playlist(self._request(), TOKEN)

        self.assertEqual(response.status_code, 410)
        self.assertIn(b"Stream stopped", response.content)
        redis.delete.assert_called_with(RedisKeys.hls_session(TOKEN))


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
