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


def _make_stream_manager(redis_client, buffering_timeout=1.0, buffering_speed=1.0):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = CHANNEL_ID
    sm.channel_name = "BBC News"
    sm.buffering = True
    sm.buffering_timeout = buffering_timeout
    sm.buffering_speed = buffering_speed
    sm.buffering_start_time = 0.0
    # Avoid the bitrate-to-DB flush path; these tests only care about state.
    sm.current_stream_id = None
    sm._bitrate_warmup_samples = 10
    sm._smoothed_output_bitrate = None
    sm._last_bitrate_db_save_time = 0
    sm._bitrate_db_save_interval = 60

    buffer = MagicMock()
    buffer.redis_client = redis_client
    buffer.channel_id = CHANNEL_ID
    sm.buffer = buffer
    return sm


class BufferingTimeoutFailoverStateTests(TestCase):
    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=True)
    def test_successful_switch_clears_redis_buffering(self, _try_next, _update_stats):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        redis.hashes[metadata_key] = {
            ChannelMetadataField.STATE: ChannelState.BUFFERING,
        }
        sm = _make_stream_manager(redis)

        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time:
            mock_time.time.return_value = 10.0
            with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
                sm._parse_ffmpeg_stats(
                    "frame=100 fps=30 q=28.0 size=1024kB time=00:00:03.00 "
                    "bitrate=500.0kbits/s speed=0.5x"
                )

        self.assertFalse(sm.buffering)
        self.assertIsNone(sm.buffering_start_time)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.ACTIVE,
        )

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=True)
    def test_good_speed_after_switch_does_not_re_latch_buffering(
        self, _try_next, _update_stats
    ):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        sm = _make_stream_manager(redis)

        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time:
            mock_time.time.return_value = 10.0
            with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
                sm._parse_ffmpeg_stats(
                    "frame=100 fps=30 q=28.0 size=1024kB time=00:00:03.00 "
                    "bitrate=500.0kbits/s speed=0.5x"
                )

        # New stream is healthy; recovery must not depend on self.buffering.
        sm._parse_ffmpeg_stats(
            "frame=200 fps=30 q=28.0 size=2048kB time=00:00:06.00 "
            "bitrate=700.0kbits/s speed=1.05x"
        )

        self.assertFalse(sm.buffering)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.ACTIVE,
        )

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_failed_switch_keeps_buffering_state(self, _try_next, _update_stats):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        sm = _make_stream_manager(redis)

        with patch("apps.proxy.live_proxy.input.manager.time") as mock_time:
            mock_time.time.return_value = 10.0
            with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
                sm._parse_ffmpeg_stats(
                    "frame=100 fps=30 q=28.0 size=1024kB time=00:00:03.00 "
                    "bitrate=500.0kbits/s speed=0.5x"
                )

        self.assertTrue(sm.buffering)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.BUFFERING,
        )
