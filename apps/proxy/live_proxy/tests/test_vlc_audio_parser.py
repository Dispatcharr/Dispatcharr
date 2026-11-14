"""VLC log parsing: audio language, pid, decoder details, partial merges, video size."""
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.services.channel_service import ChannelService
from apps.proxy.live_proxy.services.log_parsers import (
    VLCLogParser,
    merge_audio_track,
    select_best_audio_track,
)


class VLCAudioParserTests(SimpleTestCase):
    def setUp(self):
        self.parser = VLCLogParser()

    def test_parses_ts_demux_audio_pid_and_codec(self):
        line = "ts demux debug:  * pid=257 type=0x81 Audio AC-3"
        self.assertEqual(self.parser.can_parse(line), "vlc_audio")
        parsed = self.parser.parse_audio_stream(line)
        self.assertEqual(parsed["pid"], 257)
        self.assertEqual(parsed["audio_codec"], "ac3")
        self.assertEqual(parsed["audio_track"]["pid"], 257)

    def test_parses_found_language(self):
        line = "ts demux debug:       found language: eng"
        self.assertEqual(self.parser.can_parse(line), "vlc_audio")
        parsed = self.parser.parse_audio_stream(line)
        self.assertEqual(parsed["audio_language"], "eng")
        self.assertEqual(parsed["audio_track"], {"audio_language": "eng"})

    def test_ignores_undetermined_language(self):
        parsed = self.parser.parse_audio_stream(
            "ts demux debug:       found language: und"
        )
        # "und" is FFmpeg/VLC's untagged placeholder. Do not create a track.
        self.assertIsNone(parsed)

    def test_parses_a52_decoder_line(self):
        line = "a52 debug: A/52 channels:6 samplerate:48000 bitrate:384000"
        self.assertEqual(self.parser.can_parse(line), "vlc_audio")
        parsed = self.parser.parse_audio_stream(line)
        self.assertEqual(parsed["audio_codec"], "ac3")
        self.assertEqual(parsed["audio_channels"], "5.1")
        self.assertEqual(parsed["sample_rate"], 48000)
        self.assertEqual(parsed["audio_bitrate"], 384.0)

    def test_parses_aac_decoder_line(self):
        line = "main debug: AAC channels: 2 samplerate: 48000"
        self.assertEqual(self.parser.can_parse(line), "vlc_audio")
        parsed = self.parser.parse_audio_stream(line)
        self.assertEqual(parsed["audio_codec"], "aac")
        self.assertEqual(parsed["audio_channels"], "stereo")
        self.assertEqual(parsed["sample_rate"], 48000)

    def test_zero_bitrate_is_left_unset(self):
        parsed = self.parser.parse_audio_stream(
            "a52 debug: A/52 channels:2 samplerate:48000 bitrate:0"
        )
        self.assertNotIn("audio_bitrate", parsed)
        self.assertNotIn("audio_bitrate", parsed["audio_track"])

    def test_pid_is_only_taken_from_a_pmt_line(self):
        parsed = self.parser.parse_audio_stream(
            "ts demux debug: AAC channels: 2 samplerate: 48000 (pid 99)"
        )
        self.assertNotIn("pid", parsed)

    def test_decoder_line_with_only_samplerate_is_audio(self):
        # Same classification as before the packetizer lines were added.
        self.assertEqual(
            self.parser.can_parse("avcodec decoder debug: samplerate: 48000"),
            "vlc_audio",
        )

    def test_decoder_video_line_is_still_video(self):
        self.assertEqual(
            self.parser.can_parse("avcodec decoder debug: 1920x1080 at 59.94 fps"),
            "vlc_video",
        )

    def test_audio_output_line_is_not_mistaken_for_a_track(self):
        # aout often reports the PCM sink with both channels: and samplerate:,
        # which would otherwise look like a packetizer line (PCM is a codec
        # token). Reject the audio-output module, keep real packetizers.
        for line in (
            "main audio output debug: format PCM channels: 2",
            "aout debug: format PCM channels: 2 samplerate: 48000",
            "pulse audio output debug: using format pcm, channels:2, samplerate:48000",
        ):
            self.assertIsNone(self.parser.can_parse(line), line)
        self.assertEqual(
            self.parser.can_parse(
                "packetizer debug: A/52 channels:6 samplerate:48000 bitrate:384000"
            ),
            "vlc_audio",
        )

    def test_private_pes_pmt_line_is_not_audio(self):
        # stream_type 0x06 can be subtitles, DTS or AC-3. It names no codec.
        line = "ts demux debug:  * pid=262 type=0x6 PES packets containing private data"
        self.assertIsNone(self.parser.can_parse(line))


class VLCAudioMergeTests(SimpleTestCase):
    def test_merges_language_onto_latest_demux_shell(self):
        tracks = merge_audio_track(
            [],
            {"pid": 257, "audio_codec": "ac3"},
        )
        tracks = merge_audio_track(
            tracks, {"audio_language": "eng"}, accept_language=True
        )
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["audio_language"], "eng")
        self.assertEqual(tracks[0]["pid"], 257)

    def test_merges_decoder_details_into_demux_shells_in_order(self):
        tracks = []
        for track in (
            {"pid": 257, "audio_codec": "ac3", "audio_language": "eng"},
            {"pid": 258, "audio_codec": "aac", "audio_language": "eng"},
            {"pid": 259, "audio_codec": "ac3", "audio_language": "spa"},
            {"pid": 260, "audio_codec": "aac", "audio_language": "spa"},
        ):
            tracks = merge_audio_track(tracks, track)

        for track in (
            {
                "audio_codec": "ac3",
                "audio_channels": "5.1",
                "sample_rate": 48000,
                "audio_bitrate": 384.0,
            },
            {
                "audio_codec": "aac",
                "audio_channels": "stereo",
                "sample_rate": 48000,
                "audio_bitrate": 96.0,
            },
            {
                "audio_codec": "ac3",
                "audio_channels": "stereo",
                "sample_rate": 48000,
                "audio_bitrate": 384.0,
            },
            {
                "audio_codec": "aac",
                "audio_channels": "stereo",
                "sample_rate": 24000,
            },
        ):
            tracks = merge_audio_track(tracks, track)

        self.assertEqual(len(tracks), 4)
        self.assertEqual(tracks[0]["audio_channels"], "5.1")
        self.assertEqual(tracks[0]["audio_language"], "eng")
        self.assertEqual(tracks[0]["pid"], 257)
        self.assertEqual(tracks[1]["audio_codec"], "aac")
        self.assertEqual(tracks[2]["audio_language"], "spa")
        self.assertEqual(tracks[3]["sample_rate"], 24000)

        best = select_best_audio_track(tracks)
        self.assertEqual(best["audio_channels"], "5.1")
        self.assertEqual(best["audio_codec"], "ac3")
        self.assertEqual(best["audio_language"], "eng")
        self.assertEqual(best["pid"], 257)

    def test_drops_subtitle_language_instead_of_adding_a_track(self):
        tracks = merge_audio_track([], {"pid": 257, "audio_codec": "ac3"})
        tracks = merge_audio_track(
            tracks, {"audio_language": "eng"}, accept_language=True
        )
        # A later language line (subtitle ES) is not accepted.
        tracks = merge_audio_track(
            tracks, {"audio_language": "spa"}, accept_language=False
        )
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["audio_language"], "eng")

    def test_does_not_attach_language_to_an_older_track(self):
        tracks = [
            {"pid": 257, "audio_codec": "ac3"},
            {"pid": 258, "audio_codec": "aac", "audio_language": "eng"},
        ]
        tracks = merge_audio_track(
            tracks, {"audio_language": "spa"}, accept_language=True
        )
        self.assertEqual(len(tracks), 2)
        self.assertNotIn("audio_language", tracks[0])
        self.assertEqual(tracks[1]["audio_language"], "eng")

    def test_decoder_line_does_not_fill_a_different_codec(self):
        tracks = [
            {"pid": 258, "audio_codec": "aac", "audio_language": "eng"},
            {"pid": 257, "audio_codec": "ac3", "audio_language": "eng"},
        ]
        tracks = merge_audio_track(
            tracks,
            {
                "audio_codec": "ac3",
                "audio_channels": "5.1",
                "sample_rate": 48000,
                "audio_bitrate": 384.0,
            },
        )
        self.assertEqual(len(tracks), 2)
        self.assertNotIn("audio_channels", tracks[0])
        self.assertEqual(tracks[1]["audio_channels"], "5.1")
        self.assertEqual(tracks[1]["pid"], 257)

    def test_same_codec_shells_fill_in_log_order(self):
        # No pid on a decoder line, so two AAC shells take lines in the order
        # VLC prints them. Reversing the lines reverses which shell is filled.
        shells = [
            {"pid": 258, "audio_codec": "aac", "audio_language": "eng"},
            {"pid": 260, "audio_codec": "aac", "audio_language": "spa"},
        ]
        first = {"audio_codec": "aac", "audio_channels": "stereo", "sample_rate": 24000}
        second = {"audio_codec": "aac", "audio_channels": "stereo", "sample_rate": 48000}
        forward = merge_audio_track(
            merge_audio_track([dict(s) for s in shells], first), second
        )
        backward = merge_audio_track(
            merge_audio_track([dict(s) for s in shells], second), dict(first)
        )
        self.assertEqual(forward[0]["sample_rate"], 24000)
        self.assertEqual(forward[1]["sample_rate"], 48000)
        self.assertEqual(backward[0]["sample_rate"], 48000)
        self.assertEqual(backward[1]["sample_rate"], 24000)

    def test_repeat_decoder_line_does_not_duplicate_filled_shells(self):
        tracks = [
            {
                "pid": 258,
                "audio_codec": "aac",
                "audio_language": "eng",
                "audio_channels": "stereo",
                "sample_rate": 24000,
            },
            {
                "pid": 260,
                "audio_codec": "aac",
                "audio_language": "spa",
                "audio_channels": "stereo",
                "sample_rate": 24000,
            },
        ]
        tracks = merge_audio_track(
            tracks,
            {
                "audio_codec": "aac",
                "audio_channels": "stereo",
                "sample_rate": 24000,
            },
        )
        self.assertEqual(len(tracks), 2)

    def test_upserts_by_pid(self):
        tracks = merge_audio_track(
            [],
            {"pid": 257, "audio_codec": "ac3"},
        )
        tracks = merge_audio_track(
            tracks,
            {"pid": 257, "audio_language": "eng"},
        )
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["audio_language"], "eng")
        self.assertEqual(tracks[0]["audio_codec"], "ac3")


class VLCVideoParserTests(SimpleTestCase):
    def setUp(self):
        self.parser = VLCLogParser()

    def test_decoder_line_reports_the_frame_rate_not_the_coded_height(self):
        # Real decoder line: visible size, coded size, then fps. A bare
        # "N fps" match used to read the coded height (368) as the frame rate.
        line = "[0000] mpegvideo decoder debug: size 640x360/640x368 fps=25.000"
        self.assertEqual(self.parser.can_parse(line), "vlc_video")
        parsed = self.parser.parse_video_stream(line)
        self.assertEqual(parsed["resolution"], "640x360")
        self.assertEqual(parsed["source_fps"], 25.0)

    def test_transcode_source_fps_fraction_is_unchanged(self):
        parsed = self.parser.parse_video_stream(
            "stream_out_transcode debug: source fps 30000/1001"
        )
        self.assertAlmostEqual(parsed["source_fps"], 29.97, places=2)

    def test_plain_number_before_fps_still_parses(self):
        parsed = self.parser.parse_video_stream("decoder debug: video 50 fps")
        self.assertEqual(parsed["source_fps"], 50.0)


class VLCLanguageWindowTests(SimpleTestCase):
    def _manager(self):
        manager = StreamManager.__new__(StreamManager)
        manager.channel_id = "ch"
        manager.parser_type = "vlc"
        manager.ffmpeg_input_phase = False
        manager.current_stream_id = 1
        manager._vlc_audio_lang_pending = False
        manager._probe_db_stats = {}
        manager._probe_stream_id = 1
        manager._probe_generation = 1
        manager._vlc_db_flush_timer = None
        return manager

    @patch("apps.proxy.live_proxy.input.manager.threading.Timer")
    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.parse_and_store_stream_info"
    )
    def test_language_is_accepted_only_after_an_audio_es(self, parse, _timer):
        manager = self._manager()
        lines = [
            "ts demux debug:  * pid=257 type=0x81 Audio AC-3",
            "ts demux debug:       found language: eng",
            "ts demux debug:  * pid=262 type=0x06 Subtitles",
            "ts demux debug:       found language: spa",
        ]
        for line in lines:
            manager._log_stderr_content(line)

        # The audio pid line and its language are stored. The subtitle pid line
        # is not an audio line, and its language is dropped before storing.
        accepted = [call.kwargs["accept_language"] for call in parse.call_args_list]
        self.assertEqual(accepted, [False, True])
        self.assertFalse(manager._vlc_audio_lang_pending)

    @patch("apps.proxy.live_proxy.input.manager.threading.Timer")
    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.parse_and_store_stream_info"
    )
    def test_language_without_a_preceding_pid_line_is_not_stored(self, parse, _timer):
        manager = self._manager()
        manager._log_stderr_content("ts demux debug:       found language: eng")
        parse.assert_not_called()

    @patch("apps.proxy.live_proxy.input.manager.threading.Timer")
    @patch.object(ChannelService, "flush_probe_stats")
    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.parse_and_store_stream_info"
    )
    def test_vlc_audio_lines_flush_once_when_the_log_goes_quiet(
        self, parse, flush, timer
    ):
        parse.side_effect = [
            {"audio_codec": "ac3", "pid": 257},
            {"audio_codec": "ac3", "audio_language": "eng", "audio_channels": "5.1"},
        ]
        manager = self._manager()
        manager._log_stderr_content("ts demux debug:  * pid=257 type=0x81 Audio AC-3")
        manager._log_stderr_content("ts demux debug:       found language: eng")

        self.assertTrue(
            all(call.kwargs["persist_db"] is False for call in parse.call_args_list)
        )
        flush.assert_not_called()
        delay, callback = timer.call_args.args[:2]
        self.assertEqual(delay, StreamManager._VLC_DB_FLUSH_DELAY)
        callback(*timer.call_args.kwargs.get("args", ()))
        flush.assert_called_once_with(
            1,
            {
                "audio_codec": "ac3",
                "pid": 257,
                "audio_language": "eng",
                "audio_channels": "5.1",
            },
        )

    @patch("apps.proxy.live_proxy.input.manager.threading.Timer")
    @patch.object(ChannelService, "flush_probe_stats")
    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.parse_and_store_stream_info"
    )
    def test_video_size_logged_after_the_first_flush_is_still_stored(
        self, parse, flush, timer
    ):
        # VLC logs the video size only after the first decoded frame, which
        # real captures put about two seconds after the audio lines. That is
        # past the idle delay, so the first flush must not close the probe.
        parse.side_effect = [
            {"audio_codec": "ac3", "audio_channels": "stereo", "sample_rate": 44100},
            {"resolution": "640x360", "source_fps": 25.0},
        ]
        manager = self._manager()
        manager._log_stderr_content(
            "[0000] a52 decoder debug: A/52 channels:2 samplerate:44100 bitrate:192000"
        )
        first = timer.call_args
        first.args[1](*first.kwargs.get("args", ()))
        flush.assert_called_once_with(
            1,
            {"audio_codec": "ac3", "audio_channels": "stereo", "sample_rate": 44100},
        )

        manager._log_stderr_content(
            "[0000] mpegvideo decoder debug: size 640x360/640x368 fps=25.000"
        )
        self.assertEqual(parse.call_count, 2)
        self.assertEqual(timer.call_count, 2)
        second = timer.call_args
        second.args[1](*second.kwargs.get("args", ()))

        self.assertEqual(flush.call_count, 2)
        self.assertEqual(
            flush.call_args.args[1],
            {
                "audio_codec": "ac3",
                "audio_channels": "stereo",
                "sample_rate": 44100,
                "resolution": "640x360",
                "source_fps": 25.0,
            },
        )

    @patch.object(ChannelService, "flush_probe_stats")
    def test_stale_vlc_flush_does_not_write_the_new_probe(self, flush):
        manager = self._manager()
        manager._probe_db_stats = {"audio_codec": "aac"}
        manager._flush_vlc_probe_stats(generation=0)
        flush.assert_not_called()
