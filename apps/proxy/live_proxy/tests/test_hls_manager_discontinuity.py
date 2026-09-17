"""HLS manager: buffer discontinuity sidecar triggers a cut at the right chunk."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.output.hls.manager import HLSOutputManager


CHANNEL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
WORKER_ID = "worker-test-1"


class _TrackingSegmenter:
    """Stand-in for TSSegmenter that records cut/feed order."""

    def __init__(self, *args, **kwargs):
        self.events = []

    def flag_discontinuity(self):
        self.events.append("cut")
        return None

    def feed(self, data):
        self.events.append(("feed", data))
        return []


class HLSOutputManagerStartTests(SimpleTestCase):
    def _manager(self):
        mgr = HLSOutputManager.__new__(HLSOutputManager)
        mgr.channel_id = CHANNEL_ID
        mgr.worker_id = WORKER_ID
        mgr.fmt = "hls"
        mgr.running = False
        mgr._thread = None
        mgr._owns_output = False
        mgr._stopped = False
        mgr.segment_duration = 4.0
        mgr.segment_buffer = MagicMock()
        mgr.segment_buffer.chunk_ttl = 100
        mgr._set_state = MagicMock()
        mgr._write_playlist_state = MagicMock()
        mgr._acquire_owner_lock = MagicMock(return_value=True)
        return mgr

    def test_start_republishes_pruned_seed_without_bumping_ts(self):
        mgr = self._manager()
        mgr._last_segment_ts = 99.0
        with patch("apps.proxy.live_proxy.output.hls.manager.threading.Thread") as thread_cls:
            thread_cls.return_value = MagicMock()
            self.assertTrue(mgr.start())
        mgr._write_playlist_state.assert_called_once()

    def test_start_skips_republish_before_any_segment(self):
        mgr = self._manager()
        mgr._last_segment_ts = None
        with patch("apps.proxy.live_proxy.output.hls.manager.threading.Thread") as thread_cls:
            thread_cls.return_value = MagicMock()
            self.assertTrue(mgr.start())
        mgr._write_playlist_state.assert_not_called()


class HLSManagerDiscontinuityTests(SimpleTestCase):
    def _manager(self, ts_buffer):
        mgr = HLSOutputManager.__new__(HLSOutputManager)
        mgr.channel_id = CHANNEL_ID
        mgr.worker_id = WORKER_ID
        mgr.fmt = "hls"
        mgr.ts_buffer = ts_buffer
        mgr.running = True
        mgr._window = []
        mgr._owns_output = True
        mgr._stopped = False
        mgr.segment_duration = 4.0
        mgr.adv_target = 6
        mgr.window_size = 10
        mgr._redis = None
        mgr.segment_buffer = MagicMock()
        mgr._has_hls_demand = MagicMock(return_value=True)
        mgr._heartbeat_ownership = MagicMock()
        mgr._store_segment = MagicMock()
        mgr._set_state = MagicMock()
        mgr._prune_playlist_window = MagicMock(return_value=False)
        mgr._write_playlist_state = MagicMock()
        mgr._last_segment_ts = 1.0
        return mgr

    @patch(
        "apps.proxy.live_proxy.output.hls.manager.ConfigHelper.new_client_behind_seconds",
        return_value=5,
    )
    @patch(
        "apps.proxy.live_proxy.output.hls.manager.TSSegmenter",
        _TrackingSegmenter,
    )
    def test_sidecar_index_cuts_before_discontinuity_chunk(self, _behind):
        """
        When the input buffer reports a discontinuity at chunk index D, the
        segmenter loop must hard-cut before feeding that chunk so pre-switch
        and post-switch bytes never share a segment.
        """
        chunk_pre = b"PRE-SWITCH"
        chunk_post = b"POST-SWITCH"

        ts_buffer = MagicMock()
        ts_buffer.index = 2
        ts_buffer.find_chunk_index_by_time.return_value = 0
        ts_buffer.discontinuities_in_range.return_value = [2]

        def get_data(local_index):
            if local_index == 0:
                # Contiguous chunks 1 and 2; index 2 is the new-source era.
                return [chunk_pre, chunk_post], 2
            # Second poll: stop the loop.
            mgr.running = False
            return [], local_index

        ts_buffer.get_optimized_client_data.side_effect = get_data

        mgr = self._manager(ts_buffer)
        # Capture the segmenter instance the loop constructs.
        constructed = []

        real_cls = _TrackingSegmenter

        def capture(*args, **kwargs):
            seg = real_cls(*args, **kwargs)
            constructed.append(seg)
            return seg

        with patch(
            "apps.proxy.live_proxy.output.hls.manager.TSSegmenter",
            side_effect=capture,
        ):
            mgr._segmenter_loop()

        self.assertEqual(len(constructed), 1)
        events = constructed[0].events
        self.assertEqual(
            events,
            [("feed", chunk_pre), "cut", ("feed", chunk_post)],
        )
        ts_buffer.discontinuities_in_range.assert_called_with(0, 2)

    @patch(
        "apps.proxy.live_proxy.output.hls.manager.ConfigHelper.new_client_behind_seconds",
        return_value=5,
    )
    def test_no_cut_when_sidecar_empty(self, _behind):
        chunk = b"STEADY"
        ts_buffer = MagicMock()
        ts_buffer.index = 1
        ts_buffer.find_chunk_index_by_time.return_value = 0
        ts_buffer.discontinuities_in_range.return_value = []

        def get_data(local_index):
            if local_index == 0:
                return [chunk], 1
            mgr.running = False
            return [], local_index

        ts_buffer.get_optimized_client_data.side_effect = get_data
        mgr = self._manager(ts_buffer)
        constructed = []

        def capture(*args, **kwargs):
            seg = _TrackingSegmenter(*args, **kwargs)
            constructed.append(seg)
            return seg

        with patch(
            "apps.proxy.live_proxy.output.hls.manager.TSSegmenter",
            side_effect=capture,
        ):
            mgr._segmenter_loop()

        self.assertEqual(constructed[0].events, [("feed", chunk)])

    @patch(
        "apps.proxy.live_proxy.output.hls.manager.ConfigHelper.new_client_behind_seconds",
        return_value=5,
    )
    def test_heartbeat_does_not_refresh_playlist_state(self, _behind):
        """
        Heartbeat may prune a stalled window, but a no-op prune must not
        rewrite the descriptor. Playlist "ts" is last segment production,
        so a rewrite-on-every-heartbeat would mask a stall.
        """
        ts_buffer = MagicMock()
        ts_buffer.index = 0
        ts_buffer.find_chunk_index_by_time.return_value = 0

        def get_data(local_index):
            # No new chunks; stop right after the heartbeat fires once.
            mgr.running = False
            return [], local_index

        ts_buffer.get_optimized_client_data.side_effect = get_data

        mgr = self._manager(ts_buffer)
        t0 = 1_000_000.0
        with patch(
            "apps.proxy.live_proxy.output.hls.manager.time.time",
            side_effect=[t0, t0 + 11],
        ):
            mgr._segmenter_loop()

        mgr._heartbeat_ownership.assert_called_once()
        mgr._prune_playlist_window.assert_called_once()
        mgr._write_playlist_state.assert_not_called()

    @patch(
        "apps.proxy.live_proxy.output.hls.manager.ConfigHelper.new_client_behind_seconds",
        return_value=5,
    )
    def test_heartbeat_republishes_when_prune_changes_window(self, _behind):
        """Stalled input still drops expired advertised URIs; ts is not touched."""
        ts_buffer = MagicMock()
        ts_buffer.index = 0
        ts_buffer.find_chunk_index_by_time.return_value = 0

        def get_data(local_index):
            mgr.running = False
            return [], local_index

        ts_buffer.get_optimized_client_data.side_effect = get_data
        mgr = self._manager(ts_buffer)
        mgr._prune_playlist_window.return_value = True
        t0 = 1_000_000.0
        with patch(
            "apps.proxy.live_proxy.output.hls.manager.time.time",
            side_effect=[t0, t0 + 11],
        ):
            mgr._segmenter_loop()
        mgr._write_playlist_state.assert_called_once()

    @patch(
        "apps.proxy.live_proxy.output.hls.manager.ConfigHelper.new_client_behind_seconds",
        return_value=5,
    )
    def test_heartbeat_skips_republish_before_first_segment(self, _behind):
        ts_buffer = MagicMock()
        ts_buffer.index = 0
        ts_buffer.find_chunk_index_by_time.return_value = 0

        def get_data(local_index):
            mgr.running = False
            return [], local_index

        ts_buffer.get_optimized_client_data.side_effect = get_data
        mgr = self._manager(ts_buffer)
        mgr._last_segment_ts = None
        mgr._prune_playlist_window.return_value = True
        t0 = 1_000_000.0
        with patch(
            "apps.proxy.live_proxy.output.hls.manager.time.time",
            side_effect=[t0, t0 + 11],
        ):
            mgr._segmenter_loop()
        mgr._write_playlist_state.assert_not_called()


class HLSPlaylistWindowPruneTests(SimpleTestCase):
    def _manager(self):
        mgr = HLSOutputManager.__new__(HLSOutputManager)
        mgr.channel_id = CHANNEL_ID
        mgr.fmt = "hls"
        mgr.segment_duration = 4.0
        mgr._disc_sequence = 0
        mgr._window = []
        mgr.segment_buffer = MagicMock()
        mgr.segment_buffer.chunk_ttl = 100.0
        return mgr

    def test_prune_drops_expired_and_bumps_disc_sequence(self):
        import time

        mgr = self._manager()
        now = time.time()
        mgr._window = [
            {"seq": 1, "dur": 4.0, "disc": True},
            {"seq": 2, "dur": 4.0, "disc": False},
            {"seq": 3, "dur": 4.0, "disc": False},
        ]
        # Seq 1 gone from Redis; 2 and 3 still fresh.
        mgr.segment_buffer.surviving_chunk_scores.return_value = {
            2: now - 10,
            3: now - 5,
        }
        changed = mgr._prune_playlist_window()
        self.assertTrue(changed)
        self.assertEqual([e["seq"] for e in mgr._window], [2, 3])
        self.assertEqual(mgr._disc_sequence, 1)

    def test_prune_omits_oldest_within_one_segment_of_expiry(self):
        import time

        mgr = self._manager()
        now = time.time()
        mgr._window = [
            {"seq": 10, "dur": 4.0, "disc": False},
            {"seq": 11, "dur": 4.0, "disc": False},
            {"seq": 12, "dur": 4.0, "disc": False},
        ]
        # Remaining TTL for 10 is ~2s (< segment_duration 4); keep 11 and 12.
        mgr.segment_buffer.surviving_chunk_scores.return_value = {
            10: now - 98,
            11: now - 20,
            12: now - 10,
        }
        changed = mgr._prune_playlist_window()
        self.assertTrue(changed)
        self.assertEqual([e["seq"] for e in mgr._window], [11, 12])

    def test_prune_omits_all_front_entries_within_expiry_margin(self):
        """Short-segment bursts can leave several front entries near TTL."""
        import time

        mgr = self._manager()
        now = time.time()
        mgr._window = [
            {"seq": 10, "dur": 1.0, "disc": True},
            {"seq": 11, "dur": 1.0, "disc": False},
            {"seq": 12, "dur": 4.0, "disc": False},
            {"seq": 13, "dur": 4.0, "disc": False},
        ]
        # 10 and 11 both have < segment_duration remaining; 12 is still safe.
        mgr.segment_buffer.surviving_chunk_scores.return_value = {
            10: now - 99,
            11: now - 97,
            12: now - 20,
            13: now - 10,
        }
        changed = mgr._prune_playlist_window()
        self.assertTrue(changed)
        self.assertEqual([e["seq"] for e in mgr._window], [12, 13])
        self.assertEqual(mgr._disc_sequence, 1)

    def test_prune_keeps_sole_segment_even_if_near_expiry(self):
        import time

        mgr = self._manager()
        now = time.time()
        mgr._window = [{"seq": 1, "dur": 4.0, "disc": False}]
        mgr.segment_buffer.surviving_chunk_scores.return_value = {1: now - 98}
        changed = mgr._prune_playlist_window()
        self.assertFalse(changed)
        self.assertEqual([e["seq"] for e in mgr._window], [1])

    def test_prune_noop_without_redis_scores(self):
        mgr = self._manager()
        mgr._window = [{"seq": 1, "dur": 4.0, "disc": False}]
        mgr.segment_buffer.surviving_chunk_scores.return_value = {}
        self.assertFalse(mgr._prune_playlist_window())
        self.assertEqual(len(mgr._window), 1)

    def test_prune_falls_back_to_local_cap_when_scores_unavailable(self):
        """
        If surviving_chunk_scores() keeps failing (e.g. a flaky Redis read)
        while put_chunk() keeps succeeding, _window must not grow without
        bound. chunk_ttl=100 / segment_duration=4 + 5 => cap of 30.
        """
        mgr = self._manager()
        mgr._window = [
            {"seq": i, "dur": 4.0, "disc": False} for i in range(1, 36)
        ]
        mgr.segment_buffer.surviving_chunk_scores.return_value = {}
        changed = mgr._prune_playlist_window()
        self.assertTrue(changed)
        self.assertEqual(len(mgr._window), 30)
        # Oldest entries are the ones dropped.
        self.assertEqual(mgr._window[0]["seq"], 6)

    def test_prune_does_not_punch_mid_window_holes(self):
        """
        FIFO expiry is prefix-only. Dropping a later discontinuity and
        bumping the sequence would change the DSN of still-listed earlier
        segments.
        """
        import time

        mgr = self._manager()
        now = time.time()
        mgr._window = [
            {"seq": 1, "dur": 4.0, "disc": False},
            {"seq": 2, "dur": 4.0, "disc": True},
            {"seq": 3, "dur": 4.0, "disc": False},
        ]
        mgr.segment_buffer.surviving_chunk_scores.return_value = {
            1: now - 10,
            3: now - 5,
        }
        changed = mgr._prune_playlist_window()
        self.assertFalse(changed)
        self.assertEqual([e["seq"] for e in mgr._window], [1, 2, 3])
        self.assertEqual(mgr._disc_sequence, 0)

    def test_write_playlist_state_preserves_last_segment_ts(self):
        import json

        mgr = self._manager()
        mgr._last_segment_ts = 1234.5
        mgr._window = [{"seq": 1, "dur": 4.0, "disc": False}]
        mgr.adv_target = 6
        mgr.start_behind = 5.0
        mgr._redis = MagicMock()
        mgr._write_playlist_state()
        args, kwargs = mgr._redis.setex.call_args
        state = json.loads(args[2])
        self.assertEqual(state["ts"], 1234.5)
