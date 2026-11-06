"""Probe stats stay in Redis until one DB flush of fields parsed this probe."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.services.channel_service import ChannelService


class StreamInfoPersistTests(SimpleTestCase):
    @patch.object(ChannelService, "_update_stream_stats_in_db")
    @patch.object(ChannelService, "_update_stream_info_in_redis")
    @patch.object(ChannelService, "_merge_and_select_audio")
    def test_persist_db_false_returns_fields_without_db_write(
        self, merge_audio, update_redis, update_db
    ):
        merge_audio.return_value = {
            "audio_streams": [{"index": 1, "audio_channels": "5.1"}],
            "audio_codec": "ac3",
            "audio_channels": "5.1",
            "audio_bitrate": 384.0,
            "sample_rate": 48000,
            "audio_language": "eng",
        }
        parsed = {
            "audio_track": {"index": 1, "audio_codec": "ac3"},
            "audio_codec": "ac3",
        }

        fields = ChannelService.parse_and_store_stream_info(
            "ch-1",
            "unused",
            "audio",
            stream_id=99,
            parsed_data=parsed,
            persist_db=False,
        )

        update_redis.assert_called_once()
        update_db.assert_not_called()
        self.assertEqual(fields["audio_codec"], "ac3")
        self.assertEqual(fields["audio_channels"], "5.1")
        self.assertEqual(fields["audio_language"], "eng")
        self.assertNotIn("video_codec", fields)

    @patch.object(ChannelService, "_update_stream_stats_in_db", return_value=True)
    def test_flush_probe_stats_writes_only_the_given_fields(self, update_db):
        stats = {
            "video_codec": "h264",
            "audio_channels": "5.1",
            "sample_rate": 48000,
            "audio_language": "eng",
            "audio_streams": [{"index": 1, "audio_channels": "5.1"}],
        }

        ok = ChannelService.flush_probe_stats(42, stats)

        self.assertTrue(ok)
        update_db.assert_called_once_with(42, **stats)

    @patch.object(ChannelService, "_update_stream_stats_in_db")
    def test_flush_probe_stats_skips_empty(self, update_db):
        self.assertFalse(ChannelService.flush_probe_stats(42, {}))
        self.assertFalse(ChannelService.flush_probe_stats(None, {"video_codec": "h264"}))
        update_db.assert_not_called()

    @patch.object(ChannelService, "_update_stream_stats_in_db")
    def test_reset_audio_streams_drops_redis_audio_fields(self, update_db):
        redis_client = MagicMock()
        proxy = MagicMock()
        proxy.redis_client = redis_client

        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance",
            return_value=proxy,
        ):
            ChannelService.reset_audio_streams("ch-1")

        redis_client.hdel.assert_called_once()
        dropped = redis_client.hdel.call_args.args[1:]
        self.assertIn(ChannelMetadataField.AUDIO_STREAMS, dropped)
        self.assertIn(ChannelMetadataField.AUDIO_CODEC, dropped)
        self.assertIn(ChannelMetadataField.AUDIO_LANGUAGE, dropped)
        update_db.assert_not_called()

    def test_redis_audio_streams_clear_stale_summary_fields(self):
        redis_client = MagicMock()
        proxy = MagicMock()
        proxy.redis_client = redis_client

        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance",
            return_value=proxy,
        ):
            ChannelService._update_stream_info_in_redis(
                "ch-1",
                codec=None,
                resolution=None,
                width=None,
                height=None,
                fps=None,
                pixel_format=None,
                video_bitrate=None,
                audio_codec="ac3",
                sample_rate=48000,
                channels="5.1",
                audio_bitrate=384.0,
                audio_language=None,
                audio_streams=[{"pid": 257, "audio_codec": "ac3", "audio_channels": "5.1"}],
            )

        dropped = redis_client.hdel.call_args.args[1:]
        self.assertIn(ChannelMetadataField.AUDIO_LANGUAGE, dropped)
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        self.assertEqual(mapping[ChannelMetadataField.AUDIO_CODEC], "ac3")
        self.assertEqual(mapping[ChannelMetadataField.AUDIO_CHANNELS], "5.1")
        self.assertNotIn(ChannelMetadataField.AUDIO_LANGUAGE, mapping)


class MergeAndSelectAudioTests(SimpleTestCase):
    @patch.object(ChannelService, "_load_audio_streams", return_value=[])
    def test_returns_nothing_when_the_line_produced_no_track(self, _load):
        # A language line with no audio track to attach to must not store a
        # summary language beside an empty track list.
        fields = ChannelService._merge_and_select_audio(
            "ch-1", {"audio_language": "spa"}
        )
        self.assertEqual(fields, {})

    @patch.object(
        ChannelService,
        "_load_audio_streams",
        return_value=[{"pid": 257, "audio_codec": "ac3"}],
    )
    def test_summary_comes_from_the_best_track(self, _load):
        fields = ChannelService._merge_and_select_audio(
            "ch-1", {"pid": 257, "audio_channels": "5.1"}
        )
        self.assertEqual(fields["audio_channels"], "5.1")
        self.assertEqual(fields["audio_codec"], "ac3")
        self.assertEqual(len(fields["audio_streams"]), 1)


class FFmpegInputPhaseTests(SimpleTestCase):
    def _manager(self):
        manager = StreamManager.__new__(StreamManager)
        manager.channel_id = "ch"
        manager.parser_type = "ffmpeg"
        manager.ffmpeg_input_phase = False
        manager._probe_db_stats = {}
        manager._probe_stats_flushed = True
        manager.current_stream_id = 1
        return manager

    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.parse_and_store_stream_info"
    )
    def test_decoder_word_does_not_reopen_input_phase(self, parse):
        manager = self._manager()
        manager._log_stderr_content(
            "Error while opening decoder for output stream #0:1"
        )
        self.assertFalse(manager.ffmpeg_input_phase)
        manager._log_stderr_content(
            "  Stream #0:1: Audio: pcm_s16le, 48000 Hz, stereo, s16, 1536 kb/s"
        )
        parse.assert_not_called()
        self.assertEqual(manager._probe_db_stats, {})

    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.parse_and_store_stream_info"
    )
    def test_probe_summary_does_not_keep_a_field_the_new_best_track_lacks(self, parse):
        # The best track changes from a tagged stereo track to an untagged 5.1
        # one. The DB flush must not pair the new codec with the old language.
        parse.side_effect = [
            {
                "audio_streams": [{"index": 1}],
                "audio_language": "eng",
                "audio_channels": "stereo",
                "audio_codec": "aac",
            },
            {
                "audio_streams": [{"index": 1}, {"index": 2}],
                "audio_channels": "5.1",
                "audio_codec": "ac3",
            },
        ]
        manager = self._manager()
        manager.ffmpeg_input_phase = True
        manager._log_stderr_content(
            "  Stream #0:1(eng): Audio: aac, 48000 Hz, stereo, fltp, 96 kb/s"
        )
        manager._log_stderr_content(
            "  Stream #0:2: Audio: ac3, 48000 Hz, 5.1, fltp, 384 kb/s"
        )

        self.assertNotIn("audio_language", manager._probe_db_stats)
        self.assertEqual(manager._probe_db_stats["audio_channels"], "5.1")
        self.assertEqual(manager._probe_db_stats["audio_codec"], "ac3")
        self.assertEqual(len(manager._probe_db_stats["audio_streams"]), 2)

    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.parse_and_store_stream_info",
        return_value={"stream_type": "mpegts"},
    )
    def test_input_line_starts_the_probe(self, parse):
        manager = self._manager()
        manager._probe_stats_flushed = False
        manager._log_stderr_content("Input #0, mpegts, from 'http://example':")
        self.assertTrue(manager.ffmpeg_input_phase)
        parse.assert_called_once()
        self.assertEqual(manager._probe_db_stats, {"stream_type": "mpegts"})


class ProbeLifecycleTests(SimpleTestCase):
    """A stream switch or reconnect reuses the manager, so each process needs a fresh probe."""

    def _manager(self, stream_id):
        manager = StreamManager.__new__(StreamManager)
        manager.channel_id = "ch"
        manager.parser_type = "ffmpeg"
        manager.ffmpeg_input_phase = True
        manager.current_stream_id = stream_id
        manager._probe_db_stats = {}
        manager._probe_stats_flushed = False
        manager._probe_stream_id = None
        manager._probe_generation = 0
        manager._vlc_db_flush_timer = None
        return manager

    @patch.object(ChannelService, "flush_probe_stats", return_value=True)
    @patch.object(ChannelService, "reset_audio_streams")
    def test_second_probe_flushes_to_its_own_stream(self, reset_audio, flush):
        manager = self._manager(stream_id=10)

        manager._begin_probe()
        manager._probe_db_stats = {"video_codec": "h264"}
        manager._flush_probe_stats()

        # Stream switch: same manager, new stream id, new process.
        manager.current_stream_id = 20
        manager._begin_probe()
        self.assertEqual(manager._probe_db_stats, {})
        self.assertFalse(manager._probe_stats_flushed)
        manager._probe_db_stats = {"video_codec": "hevc"}
        manager._flush_probe_stats()

        self.assertEqual(
            [call.args for call in flush.call_args_list],
            [(10, {"video_codec": "h264"}), (20, {"video_codec": "hevc"})],
        )
        self.assertEqual(reset_audio.call_count, 2)

    @patch.object(ChannelService, "flush_probe_stats", return_value=True)
    @patch.object(ChannelService, "reset_audio_streams")
    def test_late_flush_uses_the_stream_the_probe_started_on(self, _reset, flush):
        manager = self._manager(stream_id=10)
        manager._begin_probe()
        manager._probe_db_stats = {"stream_type": "mpegts"}

        # update_url already pointed the manager at the next stream.
        manager.current_stream_id = 20
        manager._flush_probe_stats()

        flush.assert_called_once_with(10, {"stream_type": "mpegts"})

    @patch.object(ChannelService, "flush_probe_stats", return_value=True)
    @patch.object(ChannelService, "reset_audio_streams")
    def test_flush_happens_at_most_once_per_probe(self, _reset, flush):
        manager = self._manager(stream_id=10)
        manager._begin_probe()
        manager._probe_db_stats = {"stream_type": "mpegts"}
        manager._flush_probe_stats()
        manager._flush_probe_stats()
        flush.assert_called_once()
