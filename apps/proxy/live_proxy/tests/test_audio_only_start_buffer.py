"""Audio-only streams start with a smaller initial buffer."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys

CHANNEL = "audio-only-test"

RADIO_INPUT = [
    "Input #0, mpegts, from 'http://provider.test/live/u/p/1.ts':",
    "Duration: N/A, start: 1.400000, bitrate: N/A",
    "Stream #0:0[0x100]: Audio: mp3 (mp3float) ([3][0][0][0] / 0x0003), 48000 Hz, stereo, fltp, 128 kb/s",
    "Output #0, mpegts, to 'pipe:1':",
]

# Audio listed before video, as providers often do.
TV_INPUT = [
    "Input #0, mpegts, from 'http://provider.test/live/u/p/2.ts':",
    "Stream #0:0[0x101]: Audio: aac (LC) ([15][0][0][0] / 0x000F), 48000 Hz, stereo, fltp, 128 kb/s",
    "Stream #0:1[0x100]: Video: h264 (High) ([27][0][0][0] / 0x001B), yuv420p, 1920x1080, 25 fps",
    "Output #0, mpegts, to 'pipe:1':",
]


class FakeRedis:
    def __init__(self):
        self.hashes = {}

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)


def _manager(redis):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = CHANNEL
    sm.parser_type = "ffmpeg"
    sm.ffmpeg_input_phase = True
    sm._in_input_section = False
    sm._input_has_audio = False
    sm._input_has_video = False
    sm.current_stream_id = 1
    sm.buffer = SimpleNamespace(redis_client=redis)
    return sm


def _feed(sm, lines):
    with patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.parse_and_store_stream_info"
    ):
        for line in lines:
            sm._log_stderr_content(line)


def _flag(redis):
    return redis.hget(RedisKeys.channel_metadata(CHANNEL), ChannelMetadataField.AUDIO_ONLY)


class AudioOnlyDetectionTests(SimpleTestCase):
    def test_radio_input_is_flagged_audio_only(self):
        redis = FakeRedis()
        _feed(_manager(redis), RADIO_INPUT)
        self.assertEqual(_flag(redis), "1")

    def test_video_after_audio_is_not_audio_only(self):
        redis = FakeRedis()
        _feed(_manager(redis), TV_INPUT)
        self.assertEqual(_flag(redis), "0")

    def test_no_flag_until_input_section_ends(self):
        redis = FakeRedis()
        _feed(_manager(redis), RADIO_INPUT[:-1])
        self.assertIsNone(_flag(redis))

    def test_new_input_clears_previous_flag(self):
        redis = FakeRedis()
        sm = _manager(redis)
        _feed(sm, RADIO_INPUT)
        _feed(sm, TV_INPUT[:2])
        self.assertIsNone(_flag(redis))
        _feed(sm, TV_INPUT[2:])
        self.assertEqual(_flag(redis), "0")

    def test_input_metadata_encoder_line_does_not_hide_video(self):
        """An "encoder" metadata line flips ffmpeg_input_phase; video must still count."""
        redis = FakeRedis()
        lines = TV_INPUT[:2] + ["encoder         : Lavf58.76.100"] + TV_INPUT[2:]
        _feed(_manager(redis), lines)
        self.assertEqual(_flag(redis), "0")

    def test_new_connection_clears_stale_flag(self):
        redis = FakeRedis()
        sm = _manager(redis)
        _feed(sm, RADIO_INPUT)
        sm._reset_audio_only()
        self.assertIsNone(_flag(redis))


class InitialChunksNeededTests(SimpleTestCase):
    def _needed(self, flag):
        redis = FakeRedis()
        if flag is not None:
            redis.hset(RedisKeys.channel_metadata(CHANNEL), ChannelMetadataField.AUDIO_ONLY, flag)
        return ConfigHelper.initial_chunks_needed(redis, CHANNEL)

    def test_audio_only_uses_smaller_threshold(self):
        self.assertEqual(self._needed("1"), 2)
        self.assertEqual(self._needed(b"1"), 2)

    def test_video_or_unknown_keeps_default(self):
        self.assertEqual(self._needed("0"), 4)
        self.assertEqual(self._needed(None), 4)

    def test_redis_error_keeps_default(self):
        redis = MagicMock()
        redis.hget.side_effect = ConnectionError("down")
        self.assertEqual(ConfigHelper.initial_chunks_needed(redis, CHANNEL), 4)
