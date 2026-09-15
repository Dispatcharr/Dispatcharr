"""Live-proxy runtime events must say which stream they relate to (#1564).

channel_buffering, channel_failover, channel_reconnect, channel_error and
stream_switch are logged from the StreamManager, which already tracks
current_stream_id. These tests pin the attribution fields on each event and
the reason recorded for stream switches.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.tests.test_buffering_state_recovery import (
    CHANNEL_ID,
    _DictRedis,
    _make_stream_manager,
)


def _calls_for(mock_log, event_type):
    return [c for c in mock_log.call_args_list if c.args and c.args[0] == event_type]


class BufferingEventAttributionTests(SimpleTestCase):
    STALLED_LINE = (
        "frame=100 fps=30 q=28.0 size=1024kB time=00:00:03.00 "
        "bitrate=500.0kbits/s speed=0.5x"
    )

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    def test_buffering_start_names_current_stream(self, _update_stats):
        sm = _make_stream_manager(_DictRedis())
        sm.buffering = False
        sm.buffering_start_time = None
        sm.current_stream_id = 100

        with patch("apps.proxy.live_proxy.input.manager.log_system_event") as mock_log:
            sm._parse_ffmpeg_stats(self.STALLED_LINE)

        (call,) = _calls_for(mock_log, "channel_buffering")
        self.assertEqual(call.kwargs["channel_id"], CHANNEL_ID)
        self.assertEqual(call.kwargs["stream_id"], 100)
        self.assertEqual(call.kwargs["speed"], 0.5)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    def test_buffering_timeout_failover_names_failed_and_new_stream(self, _update_stats):
        sm = _make_stream_manager(_DictRedis())
        sm.current_stream_id = 100

        def fake_switch(reason=None):
            sm.current_stream_id = 200
            return True

        with patch.object(
            StreamManager, "_try_next_stream", side_effect=fake_switch
        ) as try_next, patch(
            "apps.proxy.live_proxy.input.manager.time"
        ) as mock_time, patch(
            "apps.proxy.live_proxy.input.manager.log_system_event"
        ) as mock_log:
            mock_time.time.return_value = 10.0
            sm._parse_ffmpeg_stats(self.STALLED_LINE)

        try_next.assert_called_once_with(reason="buffering_timeout")
        (call,) = _calls_for(mock_log, "channel_failover")
        self.assertEqual(call.kwargs["channel_id"], CHANNEL_ID)
        self.assertEqual(call.kwargs["previous_stream_id"], 100)
        self.assertEqual(call.kwargs["stream_id"], 200)
        self.assertEqual(call.kwargs["reason"], "buffering_timeout")
        self.assertEqual(call.kwargs["duration"], 10.0)


def _make_switchable_manager(current_stream_id=100, url="http://current"):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = CHANNEL_ID
    sm.channel_name = "BBC News"
    sm.url = url
    sm.user_agent = "ua"
    sm.transcode = False
    sm.socket = None
    sm.connected = True
    sm.current_stream_id = current_stream_id
    sm.tried_stream_ids = {current_stream_id} if current_stream_id else set()
    sm.url_switching = False
    sm.url_switch_start_time = None
    sm._smoothed_output_bitrate = None
    sm._last_bitrate_db_save_time = 0
    sm._bitrate_warmup_samples = 10
    sm._had_successful_connection = True
    sm._failover_rotation_passes = 0
    sm._rotation_cooldown_until = None
    sm.buffer = MagicMock()
    sm.buffer.redis_client = _DictRedis()
    return sm


class StreamSwitchEventAttributionTests(SimpleTestCase):
    @patch.object(StreamManager, "_clear_connection_failure_history")
    @patch.object(StreamManager, "_close_connection")
    @patch("apps.channels.models.Channel.objects")
    def test_update_url_records_previous_stream_and_reason(
        self, channel_objects, _close, _clear
    ):
        sm = _make_switchable_manager(current_stream_id=100)

        with patch("django.db.connection"), patch(
            "apps.proxy.live_proxy.input.manager.log_system_event"
        ) as mock_log:
            self.assertTrue(sm.update_url("http://next", 200, 7, reason="manual"))

        (call,) = _calls_for(mock_log, "stream_switch")
        self.assertEqual(call.kwargs["channel_id"], CHANNEL_ID)
        self.assertEqual(call.kwargs["previous_stream_id"], 100)
        self.assertEqual(call.kwargs["stream_id"], 200)
        self.assertEqual(call.kwargs["reason"], "manual")
        self.assertEqual(sm.current_stream_id, 200)

    @patch("apps.proxy.live_proxy.input.manager.get_stream_info_for_switch")
    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    @patch.object(StreamManager, "update_url", return_value=True)
    def test_try_next_stream_propagates_reason(self, mock_update, mock_alts, mock_info):
        sm = _make_switchable_manager(current_stream_id=100)
        mock_alts.return_value = [{"stream_id": 200, "profile_id": 7}]
        mock_info.return_value = {
            "url": "http://next",
            "user_agent": "ua",
            "transcode": False,
            "stream_profile": 1,
        }

        self.assertTrue(sm._try_next_stream(reason="buffering_timeout"))

        mock_update.assert_called_once_with("http://next", 200, 7, reason="buffering_timeout")

    @patch.object(StreamManager, "_try_next_stream", return_value=True)
    def test_cooldown_wrapper_propagates_reason(self, mock_try_next):
        sm = _make_switchable_manager(current_stream_id=100)

        self.assertTrue(sm._try_next_stream_with_cooldown(reason="health_monitor"))

        mock_try_next.assert_called_once_with(reason="health_monitor")
