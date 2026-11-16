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
    sm.channel_name = "Test Channel"
    sm.buffering = True
    sm.buffering_timeout = buffering_timeout
    sm.buffering_speed = buffering_speed
    sm.buffering_start_time = 0.0
    sm.buffering_timeout_error_stream_id = StreamManager._NO_BUFFERING_TIMEOUT_ERROR
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


ALTERNATE_IDS = (416057, 416196, 416389, 415362)
CURRENT_STREAM_ID = 416283
BUFFERING_STATS_LINE = (
    "frame=100 fps=30 q=28.0 size=1024kB time=00:00:03.00 "
    "bitrate=500.0kbits/s speed=0.5x"
)
HEALTHY_STATS_LINE = (
    "frame=200 fps=30 q=28.0 size=2048kB time=00:00:06.00 "
    "bitrate=700.0kbits/s speed=1.05x"
)


def _parse_stats_at(sm, *times, line=BUFFERING_STATS_LINE):
    """Feed one stats line per timestamp, with the manager clock set to it.

    Returns the patched log_system_event mock so callers can inspect events.
    """
    with patch("apps.proxy.live_proxy.input.manager.time") as mock_time:
        with patch("apps.proxy.live_proxy.input.manager.log_system_event") as mock_event:
            for now in times:
                mock_time.time.return_value = now
                sm._parse_ffmpeg_stats(line)
    return mock_event


def _make_long_connection_manager(healthy_for, redis_client):
    """Manager buffering on a connection that earlier went through a full rotation."""
    buffering_start = 1000.0
    sm = _make_stream_manager(redis_client, buffering_timeout=1.0)
    sm.buffering_start_time = buffering_start
    sm.connection_start_time = buffering_start - healthy_for
    sm._stable_connection_threshold = 30
    sm.current_stream_id = CURRENT_STREAM_ID
    sm.tried_stream_ids = {CURRENT_STREAM_ID, *ALTERNATE_IDS}
    sm._had_successful_connection = True
    sm._failover_rotation_passes = 0
    sm._rotation_cooldown_until = None
    sm.url = "http://current"
    sm.user_agent = "ua"
    sm.transcode = False
    return sm


def _alternates():
    return [{"stream_id": i, "profile_id": 4} for i in ALTERNATE_IDS]


def _switch_info(url="http://alternate"):
    return {
        "url": url,
        "user_agent": "ua",
        "transcode": False,
        "stream_profile": 1,
    }


class BufferingTimeoutStableConnectionTests(TestCase):
    """Buffering-timeout failover after a long healthy connection.

    The connection settled after trying every stream at startup and then played
    well past the stable threshold. Those earlier attempts must not block the
    switch when it later starts buffering.
    """

    def _parse(self, sm, *times):
        """One stats line per timestamp. Defaults to a single line past the timeout.

        Failed switches are retried one buffering timeout apart (1s here), so
        multi-line tests space their timestamps at least that far.
        """
        _parse_stats_at(sm, *(times or (1020.0,)))

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch("apps.proxy.live_proxy.input.manager.get_stream_info_for_switch")
    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    @patch.object(StreamManager, "update_url", return_value=True)
    def test_stable_connection_switches_immediately(
        self, mock_update, mock_alts, mock_info, _update_stats
    ):
        sm = _make_long_connection_manager(2283.7, _DictRedis())
        mock_alts.return_value = _alternates()
        mock_info.return_value = _switch_info()

        self._parse(sm)

        mock_update.assert_called_once()
        self.assertIn(sm.current_stream_id, ALTERNATE_IDS)
        self.assertFalse(sm.buffering)
        self.assertEqual(sm._failover_rotation_passes, 0)
        self.assertIsNone(sm._rotation_cooldown_until)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch("apps.proxy.live_proxy.input.manager.get_stream_info_for_switch")
    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    @patch.object(StreamManager, "update_url", return_value=True)
    def test_unstable_connection_still_waits_on_cooldown(
        self, mock_update, mock_alts, mock_info, _update_stats
    ):
        sm = _make_long_connection_manager(10, _DictRedis())
        mock_alts.return_value = _alternates()
        mock_info.return_value = _switch_info()

        self._parse(sm)

        mock_update.assert_not_called()
        self.assertEqual(sm.current_stream_id, CURRENT_STREAM_ID)
        self.assertTrue(sm.buffering)
        self.assertEqual(sm._failover_rotation_passes, 1)
        self.assertIsNotNone(sm._rotation_cooldown_until)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch("apps.proxy.live_proxy.input.manager.get_stream_info_for_switch")
    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    @patch.object(StreamManager, "update_url", return_value=True)
    def test_repeated_stats_lines_do_not_clear_cooldown(
        self, mock_update, mock_alts, mock_info, _update_stats
    ):
        """Failed switches must still be throttled by the wrap cooldown.

        Every alternate fails to resolve, so buffering continues and the
        timeout failover is attempted again each buffering timeout. Only the
        first attempt may reset the rotation state.
        """
        sm = _make_long_connection_manager(2283.7, _DictRedis())
        mock_alts.return_value = _alternates()
        mock_info.return_value = {"error": "no URL"}

        # First attempt tries every alternate. The second finds them exhausted
        # and arms the cooldown.
        self._parse(sm, 1020.0, 1021.0)
        self.assertEqual(sm._failover_rotation_passes, 1)
        cooldown_until = sm._rotation_cooldown_until
        self.assertIsNotNone(cooldown_until)

        self._parse(sm, 1022.0, 1023.0, 1024.0, 1025.0, 1026.0)

        mock_update.assert_not_called()
        self.assertEqual(sm._failover_rotation_passes, 1)
        self.assertEqual(sm._rotation_cooldown_until, cooldown_until)
        # One lookup per alternate on the first line, none once the cooldown holds.
        self.assertEqual(mock_info.call_count, len(ALTERNATE_IDS))

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch("apps.proxy.live_proxy.input.manager.get_stream_info_for_switch")
    @patch("apps.proxy.live_proxy.input.manager.get_alternate_streams")
    @patch.object(StreamManager, "update_url", return_value=True)
    def test_recovered_episode_does_not_retry_the_rotation(
        self, mock_update, mock_alts, mock_info, _update_stats
    ):
        """A speed blip must not start the rotation over on the same connection.

        After the alternates fail, one healthy sample ends the episode. The next
        timeout is a new episode but the same connection, so the cooldown and
        pass count stay in place.
        """
        sm = _make_long_connection_manager(2283.7, _DictRedis())
        mock_alts.return_value = _alternates()
        mock_info.return_value = {"error": "no URL"}

        # First attempt tries every alternate. The second finds them exhausted
        # and arms the cooldown.
        self._parse(sm, 1020.0, 1021.0)
        self.assertEqual(sm._failover_rotation_passes, 1)
        cooldown_until = sm._rotation_cooldown_until
        self.assertEqual(mock_alts.call_count, 2)

        # Speed recovers, then a new episode starts and times out again.
        _parse_stats_at(sm, 1021.2, line=HEALTHY_STATS_LINE)
        self.assertFalse(sm.buffering)
        self._parse(sm, 1021.4, 1023.0)

        # The third attempt ran, and left the rotation state alone.
        self.assertEqual(mock_alts.call_count, 3)
        mock_update.assert_not_called()
        self.assertEqual(sm._failover_rotation_passes, 1)
        self.assertEqual(sm._rotation_cooldown_until, cooldown_until)
        self.assertEqual(mock_info.call_count, len(ALTERNATE_IDS))


class BufferingTimeoutRetryThrottleTests(TestCase):
    """A failed buffering-timeout switch is retried once per buffering timeout.

    Stats lines arrive about twice a second and the timeout stays exceeded
    after a failed switch, so without a retry delay every line would repeat the
    attempt, its log lines, and the alternate-stream lookup.
    """

    def _manager(self, redis_client=None):
        # buffering_timeout is 1s and buffering began at t=0.
        sm = _make_stream_manager(redis_client or _DictRedis())
        sm.current_stream_id = 7
        return sm

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_failed_switch_is_not_retried_on_every_stats_line(self, mock_try, _stats):
        _parse_stats_at(self._manager(), 10.0, 10.5, 10.9)

        self.assertEqual(mock_try.call_count, 1)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_failed_switch_is_retried_after_one_buffering_timeout(self, mock_try, _stats):
        _parse_stats_at(self._manager(), 10.0, 10.5, 11.0, 11.5, 12.0)

        # Attempts at 10.0, 11.0 and 12.0.
        self.assertEqual(mock_try.call_count, 3)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_throttled_lines_log_no_new_attempt(self, _try, _stats):
        sm = self._manager()

        with patch("apps.proxy.live_proxy.input.manager.logger") as mock_logger:
            _parse_stats_at(sm, 10.0, 10.2, 10.4, 10.6, 10.8, 11.0)

        timeouts = [
            call for call in mock_logger.error.call_args_list
            if str(call.args[0]).startswith("Buffering timeout reached")
        ]
        self.assertEqual(len(timeouts), 2)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_throttled_lines_keep_buffering_state(self, _try, _stats):
        redis = _DictRedis()
        metadata_key = RedisKeys.channel_metadata(CHANNEL_ID)
        sm = self._manager(redis)

        _parse_stats_at(sm, 10.0, 10.5)

        self.assertTrue(sm.buffering)
        # The buffering clock is the true onset; the retry delay must not move it.
        self.assertEqual(sm.buffering_start_time, 0.0)
        self.assertEqual(
            redis.hashes[metadata_key][ChannelMetadataField.STATE],
            ChannelState.BUFFERING,
        )

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_channel_error_event_is_still_emitted_once(self, _try, _stats):
        events = _parse_stats_at(self._manager(), 10.0, 11.0, 12.0)

        errors = [c for c in events.call_args_list if c.args[0] == "channel_error"]
        self.assertEqual(len(errors), 1)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", side_effect=[False, True])
    def test_retry_can_switch_and_reports_the_whole_stall(self, mock_try, _stats):
        sm = self._manager()

        events = _parse_stats_at(sm, 10.0, 10.5, 11.0)

        self.assertEqual(mock_try.call_count, 2)
        self.assertFalse(sm.buffering)
        (failover,) = [c for c in events.call_args_list if c.args[0] == "channel_failover"]
        # Measured from the onset of buffering, not from the last failed attempt.
        self.assertEqual(failover.kwargs["duration"], 11.0)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_new_episode_is_not_held_back_by_an_earlier_failure(self, mock_try, _stats):
        sm = self._manager()

        _parse_stats_at(sm, 10.0)
        self.assertEqual(mock_try.call_count, 1)

        # Speed recovers, a new stall begins at 10.4 and times out at 11.5.
        _parse_stats_at(sm, 10.2, line=HEALTHY_STATS_LINE)
        _parse_stats_at(sm, 10.4, 11.5)

        self.assertEqual(mock_try.call_count, 2)

    @patch.object(StreamManager, "_update_ffmpeg_stats_in_redis")
    @patch.object(StreamManager, "_try_next_stream", return_value=False)
    def test_manager_without_retry_state_still_attempts(self, mock_try, _stats):
        sm = self._manager()
        self.assertFalse(hasattr(sm, "_buffering_failover_retry_at"))

        _parse_stats_at(sm, 10.0)

        self.assertEqual(mock_try.call_count, 1)
