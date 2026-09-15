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
        mgr.adv_target = 8
        mgr.window_size = 10
        mgr._redis = None
        mgr.segment_buffer = MagicMock()
        mgr._has_hls_demand = MagicMock(return_value=True)
        mgr._heartbeat_ownership = MagicMock()
        mgr._store_segment = MagicMock()
        mgr._set_state = MagicMock()
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
