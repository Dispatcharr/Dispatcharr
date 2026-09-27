"""Live-proxy runtime events must say which stream they relate to (#1564).

channel_buffering, channel_failover, channel_reconnect, channel_error and
stream_switch are logged from the StreamManager, which already tracks
current_stream_id. These tests pin the attribution fields on each event and
the reason recorded for stream switches.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.tests.test_buffering_state_recovery import (
    CHANNEL_ID,
    _DictRedis,
    _make_stream_manager,
)


def _calls_for(mock_log, event_type):
    return [c for c in mock_log.call_args_list if c.args and c.args[0] == event_type]


STALLED_LINE = (
    "frame=100 fps=30 q=28.0 size=1024kB time=00:00:03.00 "
    "bitrate=500.0kbits/s speed=0.5x"
)


class BufferingEventAttributionTests(SimpleTestCase):
    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    def test_buffering_start_names_current_stream(self, _update_stats):
        sm = _make_stream_manager(_DictRedis())
        sm.buffering = False
        sm.buffering_start_time = None
        sm.current_stream_id = 100

        with patch("apps.proxy.live_proxy.input.manager.log_system_event") as mock_log:
            sm._parse_ffmpeg_stats(STALLED_LINE)

        (call,) = _calls_for(mock_log, "channel_buffering")
        self.assertEqual(call.kwargs["channel_id"], CHANNEL_ID)
        self.assertEqual(call.kwargs["stream_id"], 100)
        self.assertEqual(call.kwargs["speed"], 0.5)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    def test_buffering_timeout_failover_names_failed_and_new_stream(self, _update_stats):
        sm = _make_stream_manager(_DictRedis())
        sm.current_stream_id = 100

        def fake_switch(reason=None, previous_stream_info=None):
            previous_stream_info.update(stream_name="Feed A", provider_name="Provider")
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
            sm._parse_ffmpeg_stats(STALLED_LINE)

        self.assertEqual(try_next.call_args.kwargs["reason"], "buffering_timeout")
        (call,) = _calls_for(mock_log, "channel_failover")
        self.assertEqual(call.kwargs["channel_id"], CHANNEL_ID)
        self.assertEqual(call.kwargs["previous_stream_id"], 100)
        self.assertEqual(call.kwargs["previous_stream_name"], "Feed A")
        self.assertEqual(call.kwargs["previous_provider_name"], "Provider")
        self.assertEqual(call.kwargs["stream_id"], 200)
        self.assertEqual(call.kwargs["reason"], "buffering_timeout")
        self.assertEqual(call.kwargs["duration"], 10.0)
        self.assertEqual(_calls_for(mock_log, "channel_error"), [])

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_buffering_timeout_without_switch_logs_error_against_stalled_stream(
        self, _try_next, _update_stats
    ):
        sm = _make_stream_manager(_DictRedis())
        sm.current_stream_id = 100

        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time, patch(
            "apps.proxy.live_proxy.input.manager.log_system_event"
        ) as mock_log:
            mock_time.time.return_value = 10.0
            sm._parse_ffmpeg_stats(STALLED_LINE)

        (call,) = _calls_for(mock_log, "channel_error")
        self.assertEqual(call.kwargs["channel_id"], CHANNEL_ID)
        self.assertEqual(call.kwargs["stream_id"], 100)
        self.assertEqual(call.kwargs["error_type"], "buffering_timeout")
        self.assertEqual(_calls_for(mock_log, "stream_switch"), [])
        self.assertEqual(_calls_for(mock_log, "channel_failover"), [])
        self.assertTrue(sm.buffering)


def _make_switchable_manager(current_stream_id=100, url="http://current", redis_client=None):
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
    sm.buffer.redis_client = redis_client if redis_client is not None else _DictRedis()
    return sm


STREAM_INFO = {
    "url": "http://next",
    "user_agent": "ua",
    "transcode": False,
    "stream_profile": 1,
    "stream_name": "Feed B",
}


class StreamSwitchEventAttributionTests(SimpleTestCase):
    @patch.object(StreamManager, "_clear_connection_failure_history")
    @patch.object(StreamManager, "_close_connection")
    @patch("apps.channels.models.Channel.objects")
    def test_manual_switch_reads_previous_name_from_metadata_hash(
        self, channel_objects, _close, _clear
    ):
        redis = MagicMock()
        redis.hget.return_value = b"Feed A"
        sm = _make_switchable_manager(current_stream_id=100, redis_client=redis)

        with patch("django.db.connection"), patch(
            "apps.proxy.live_proxy.input.manager.log_system_event"
        ) as mock_log:
            self.assertTrue(sm.update_url("http://next", 200, 7, reason="manual"))

        redis.hget.assert_called_once_with(
            RedisKeys.channel_metadata(CHANNEL_ID), ChannelMetadataField.STREAM_NAME
        )
        (call,) = _calls_for(mock_log, "stream_switch")
        self.assertEqual(call.kwargs["channel_id"], CHANNEL_ID)
        self.assertEqual(call.kwargs["previous_stream_id"], 100)
        self.assertEqual(call.kwargs["previous_stream_name"], "Feed A")
        self.assertIsNone(call.kwargs["previous_provider_name"])
        self.assertEqual(call.kwargs["stream_id"], 200)
        self.assertEqual(call.kwargs["reason"], "manual")
        self.assertEqual(sm.current_stream_id, 200)

    @patch.object(StreamManager, "_clear_connection_failure_history")
    @patch.object(StreamManager, "_close_connection")
    @patch("apps.channels.models.Channel.objects")
    def test_update_url_prefers_supplied_previous_names(self, channel_objects, _close, _clear):
        redis = MagicMock()
        sm = _make_switchable_manager(current_stream_id=100, redis_client=redis)

        with patch("django.db.connection"), patch(
            "apps.proxy.live_proxy.input.manager.log_system_event"
        ) as mock_log:
            sm.update_url(
                "http://next", 200, 7, reason="buffering_timeout",
                previous_stream_name="Feed A", previous_provider_name="Provider",
            )

        redis.hget.assert_not_called()
        (call,) = _calls_for(mock_log, "stream_switch")
        self.assertEqual(call.kwargs["previous_stream_name"], "Feed A")
        self.assertEqual(call.kwargs["previous_provider_name"], "Provider")

    @patch("apps.proxy.live_proxy.input.manager.get_stream_info_for_switch", return_value=STREAM_INFO)
    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    @patch.object(StreamManager, "update_url", return_value=True)
    def test_try_next_stream_passes_skipped_stream_names_and_records_reason(
        self, mock_update, mock_alts, _mock_info
    ):
        sm = _make_switchable_manager(current_stream_id=100)

        def alternates(channel_id, current_stream_id, current_stream_info=None):
            current_stream_info.update(stream_name="Feed A", provider_name="Provider")
            return [{"stream_id": 200, "profile_id": 7}]

        mock_alts.side_effect = alternates

        self.assertTrue(sm._try_next_stream(reason="buffering_timeout"))

        mock_update.assert_called_once_with(
            "http://next", 200, 7, reason="buffering_timeout",
            previous_stream_name="Feed A", previous_provider_name="Provider",
        )
        metadata = sm.buffer.redis_client.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
        self.assertEqual(metadata[ChannelMetadataField.STREAM_SWITCH_REASON], "buffering_timeout")
        self.assertEqual(metadata[ChannelMetadataField.STREAM_ID], "200")
        self.assertEqual(metadata[ChannelMetadataField.STREAM_NAME], "Feed B")

    @patch.object(StreamManager, "_try_next_stream", return_value=True)
    def test_cooldown_wrapper_propagates_reason(self, mock_try_next):
        sm = _make_switchable_manager(current_stream_id=100)

        self.assertTrue(sm._try_next_stream_with_cooldown(reason="health_monitor"))

        mock_try_next.assert_called_once_with(reason="health_monitor")


class AlternateStreamSkipTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("core.utils.RedisClient.get_client", return_value=None)
    @patch("apps.channels.models.Stream.objects")
    @patch("apps.proxy.live_proxy.url_utils.get_stream_object")
    def test_skip_captures_current_stream_name_and_provider(
        self, mock_get_object, stream_objects, _redis, _close
    ):
        current = MagicMock()
        current.id = 100
        current.name = "Feed A"
        current.m3u_account.name = "Provider A"

        profile = MagicMock()
        profile.id = 7
        profile.is_default = True
        alternate = MagicMock()
        alternate.id = 200
        alternate.name = "Feed B"
        alternate.m3u_account.is_active = True
        alternate.m3u_account.profiles.filter.return_value = [profile]

        streams_qs = MagicMock()
        streams_qs.values_list.return_value = [100, 200]
        streams_qs.__iter__ = lambda self: iter([current, alternate])
        channel = MagicMock()
        channel.streams.select_related.return_value.order_by.return_value = streams_qs
        mock_get_object.return_value = channel

        from apps.proxy.live_proxy.url_utils import get_alternate_streams

        info = {}
        result = get_alternate_streams(CHANNEL_ID, current_stream_id=100, current_stream_info=info)

        self.assertEqual([s["stream_id"] for s in result], [200])
        self.assertEqual(info, {"stream_name": "Feed A", "provider_name": "Provider A"})
        channel.streams.select_related.assert_called_once_with("m3u_account")
        stream_objects.get.assert_not_called()
        stream_objects.filter.assert_not_called()
