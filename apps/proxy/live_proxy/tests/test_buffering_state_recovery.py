"""Tests for Redis channel state after buffering-timeout failover.

After a buffering timeout switch, Redis must not stay latched at buffering
once the in-memory buffering flag is cleared. The switch path writes ACTIVE
(same as normal buffering recovery) so mid-session clients are not forced
through the connecting init-wait path.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys


CHANNEL_ID = "00000000-0000-0000-0000-000000000149"


class _DictRedis:
    """Minimal Redis stand-in that records hash field writes."""

    def __init__(self):
        self.hashes = {}

    def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.hashes.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        elif field is not None:
            bucket[field] = value

    def hdel(self, key, *fields):
        bucket = self.hashes.get(key, {})
        for field in fields:
            bucket.pop(field, None)


def _make_stream_manager(redis_client, buffering_timeout=1.0):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = CHANNEL_ID
    sm.channel_name = "Test Channel"
    sm.buffering = True
    sm.buffering_timeout = buffering_timeout
    sm.buffering_speed = 1.0
    sm.experimental_ingest_buffer = False
    sm.buffering_start_time = 0.0
    sm.buffering_timeout_error_stream_id = StreamManager._NO_BUFFERING_TIMEOUT_ERROR
    sm.current_stream_id = None
    sm._bitrate_warmup_samples = 10
    sm._smoothed_output_bitrate = None
    sm._last_bitrate_db_save_time = 0
    sm._bitrate_db_save_interval = 60
    sm.running = True
    sm.stopping = False
    sm._init_ingest_lag_state()

    buffer = MagicMock()
    buffer.redis_client = redis_client
    buffer.channel_id = CHANNEL_ID
    sm.buffer = buffer
    return sm


class BufferingTimeoutFailoverStateTests(TestCase):
    @patch.object(StreamManager, "_try_next_stream", return_value=True)
    def test_successful_switch_clears_redis_buffering(self, _try_next):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        redis.hashes[metadata_key] = {
            ChannelMetadataField.STATE: ChannelState.BUFFERING,
        }
        sm = _make_stream_manager(redis)

        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time:
            mock_time.time.return_value = 10.0
            with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
                sm._update_buffering_state(True, speed=0.5)

        self.assertFalse(sm.buffering)
        self.assertIsNone(sm.buffering_start_time)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.ACTIVE,
        )

    @patch.object(StreamManager, "_try_next_stream", return_value=True)
    def test_recovery_after_switch_does_not_re_latch_buffering(self, _try_next):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        sm = _make_stream_manager(redis)

        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time:
            mock_time.time.return_value = 10.0
            with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
                sm._update_buffering_state(True, speed=0.5)

        sm._update_buffering_state(False, speed=1.05)

        self.assertFalse(sm.buffering)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.ACTIVE,
        )

    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_failed_switch_keeps_buffering_state(self, _try_next):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        sm = _make_stream_manager(redis)

        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time:
            mock_time.time.return_value = 10.0
            with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
                sm._update_buffering_state(True, speed=0.5)

        # Redis started empty. A failed switch must still leave the label.
        self.assertTrue(sm.buffering)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.BUFFERING,
        )

    def test_buffering_label_is_refreshed_while_latched_but_not_every_call(self):
        # Another writer (for example a cancelled shutdown) can set ACTIVE
        # while the manager is still latched. The label comes back within the
        # refresh interval, without a Redis write on every evaluation.
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        sm = _make_stream_manager(redis, buffering_timeout=1000.0)
        sm.buffering = False
        sm.buffering_start_time = None
        clock = [100.0]
        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time, patch(
            "apps.proxy.live_proxy.input.manager.log_system_event"
        ):
            mock_time.time.side_effect = lambda: clock[0]
            sm._update_buffering_state(True)
            self.assertEqual(
                redis.hashes[metadata_key][ChannelMetadataField.STATE],
                ChannelState.BUFFERING,
            )
            redis.hashes[metadata_key][ChannelMetadataField.STATE] = ChannelState.ACTIVE
            clock[0] = 100.2
            sm._update_buffering_state(True)
            self.assertEqual(
                redis.hashes[metadata_key][ChannelMetadataField.STATE],
                ChannelState.ACTIVE,
            )
            clock[0] = 100.0 + sm._BUFFERING_STATE_REFRESH_SECONDS + 0.1
            sm._update_buffering_state(True)
            self.assertEqual(
                redis.hashes[metadata_key][ChannelMetadataField.STATE],
                ChannelState.BUFFERING,
            )

    @patch.object(StreamManager, "_try_next_stream", return_value=True)
    def test_experimental_ingest_timeout_clears_redis_buffering(self, _try_next):
        # Same timeout path as FFmpeg mode: after a successful switch Redis
        # must leave BUFFERING so mid-session clients are not stuck.
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        redis.hashes[metadata_key] = {
            ChannelMetadataField.STATE: ChannelState.BUFFERING,
        }
        sm = _make_stream_manager(redis)
        sm.experimental_ingest_buffer = True

        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time:
            mock_time.time.return_value = 10.0
            with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
                sm._update_buffering_state(True, speed=0.5)

        self.assertFalse(sm.buffering)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.ACTIVE,
        )


STALLED_LINE = (
    "frame=100 fps=30 q=28.0 size=1024kB time=00:00:03.00 "
    "bitrate=500.0kbits/s speed=0.5x"
)
HEALTHY_LINE = (
    "frame=100 fps=30 q=28.0 size=1024kB time=00:00:03.00 "
    "bitrate=500.0kbits/s speed=1.0x"
)


class FfmpegStatsBufferingWiringTests(TestCase):
    """The default path still ties FFmpeg ``speed=`` to buffering."""

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    def test_slow_ffmpeg_speed_starts_buffering_when_experimental_is_off(self, _stats):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        sm = _make_stream_manager(redis, buffering_timeout=1000.0)
        sm.buffering = False
        sm.buffering_start_time = None

        with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
            sm._parse_ffmpeg_stats(STALLED_LINE)

        self.assertTrue(sm.buffering)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.BUFFERING,
        )
        # The speed is published as before.
        self.assertEqual(_stats.call_args.args[0], 0.5)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    def test_healthy_ffmpeg_speed_clears_buffering_when_experimental_is_off(self, _stats):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        sm = _make_stream_manager(redis)
        sm.buffering = True

        sm._parse_ffmpeg_stats(HEALTHY_LINE)

        self.assertFalse(sm.buffering)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.ACTIVE,
        )

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    def test_experimental_mode_ignores_ffmpeg_speed_for_buffering_and_badge(self, _stats):
        redis = _DictRedis()
        sm = _make_stream_manager(redis, buffering_timeout=1000.0)
        sm.experimental_ingest_buffer = True
        sm.buffering = False
        sm.buffering_start_time = None

        with patch("apps.proxy.live_proxy.input.manager.log_system_event") as log:
            sm._parse_ffmpeg_stats(STALLED_LINE)

        self.assertFalse(sm.buffering)
        log.assert_not_called()
        self.assertEqual(redis.hashes, {})
        # FFmpeg speed must not overwrite the ingest speed on the badge. The
        # other stats still publish.
        self.assertIsNone(_stats.call_args.args[0])
