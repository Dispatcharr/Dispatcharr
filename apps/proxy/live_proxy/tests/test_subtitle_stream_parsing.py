"""Tests for subtitle stream detection in FFmpeg log output.

DVB subtitle and teletext streams are reported by FFmpeg on the same
``Stream #...`` lines as video and audio, but were not parsed, so a channel
carrying them looked identical to one that did not.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.proxy.live_proxy.services.channel_service import ChannelService
from apps.proxy.live_proxy.services.log_parsers import (
    FFmpegLogParser,
    LogParserFactory,
    StreamlinkLogParser,
    VLCLogParser,
)

# Real lines captured from an AU FTA broadcast carrying teletext.
TELETEXT_LINE = (
    "Stream #0:3[0x912](eng): Subtitle: dvb_teletext ([6][0][0][0] / 0x0006), "
    "start 45419.465767"
)
# Same source, second stage of the pipeline: no PID bracket.
TELETEXT_LINE_NO_PID = (
    "Stream #0:2(eng): Subtitle: dvb_teletext ([6][0][0][0] / 0x0006)"
)
# Bitmap DVB subtitles, as reported in Dispatcharr#1502.
DVB_SUBTITLE_LINE = "Stream #0:2[0x102](eng): Subtitle: dvb_subtitle (dvbsub)"


class FFmpegSubtitleDetectionTests(TestCase):
    def test_can_parse_identifies_a_subtitle_stream_line(self):
        parser = FFmpegLogParser()
        self.assertEqual(parser.can_parse(TELETEXT_LINE), "subtitle")

    def test_parses_teletext_codec(self):
        parser = FFmpegLogParser()
        result = parser.parse_subtitle_stream(TELETEXT_LINE)
        self.assertEqual(result["subtitle_codec"], "dvb_teletext")

    def test_parses_dvb_subtitle_codec(self):
        parser = FFmpegLogParser()
        result = parser.parse_subtitle_stream(DVB_SUBTITLE_LINE)
        self.assertEqual(result["subtitle_codec"], "dvb_subtitle")

    def test_parses_language_tag(self):
        parser = FFmpegLogParser()
        result = parser.parse_subtitle_stream(TELETEXT_LINE)
        self.assertEqual(result["subtitle_language"], "eng")

    def test_parses_language_when_no_pid_bracket_is_present(self):
        parser = FFmpegLogParser()
        result = parser.parse_subtitle_stream(TELETEXT_LINE_NO_PID)
        self.assertEqual(result["subtitle_language"], "eng")

    def test_returns_none_for_a_line_with_no_subtitle_stream(self):
        parser = FFmpegLogParser()
        self.assertIsNone(parser.parse_subtitle_stream("Stream #0:0: Video: h264"))


class SubtitleFactoryRoutingTests(TestCase):
    def test_auto_parse_routes_a_subtitle_line_to_the_subtitle_parser(self):
        result = LogParserFactory.auto_parse(TELETEXT_LINE)
        self.assertIsNotNone(result)
        stream_type, parsed = result
        self.assertEqual(stream_type, "subtitle")
        self.assertEqual(parsed["subtitle_codec"], "dvb_teletext")


class SubtitleParsingLeavesOtherStreamsAloneTests(TestCase):
    """Guards: the new can_parse branch must not steal video or audio lines."""

    def test_video_line_still_routes_to_video(self):
        parser = FFmpegLogParser()
        line = (
            "Stream #0:0[0x100]: Video: h264 (High), yuv420p(tv, bt709), "
            "1920x1080 [SAR 1:1 DAR 16:9], 25 fps, 25 tbr, 90k tbn"
        )
        self.assertEqual(parser.can_parse(line), "video")

    def test_audio_line_still_routes_to_audio(self):
        parser = FFmpegLogParser()
        line = "Stream #0:1[0x101](eng): Audio: mp2, 48000 Hz, stereo, fltp, 256 kb/s"
        self.assertEqual(parser.can_parse(line), "audio")


class SubtitleCodecReachesStreamStatsTests(TestCase):
    """The DVR sidecar reads subtitle_codec back off Stream.stream_stats
    (apps/channels/tasks.py), so parsing it here is useless unless it's
    actually forwarded to the DB write - it wasn't."""

    @patch("apps.proxy.live_proxy.services.channel_service.ChannelService._update_stream_info_in_redis")
    @patch("apps.proxy.live_proxy.services.channel_service.ChannelService._update_stream_stats_in_db")
    def test_subtitle_codec_and_language_are_forwarded_to_db_write(self, mock_db, mock_redis):
        ChannelService.parse_and_store_stream_info(
            channel_id=1, stream_info_line=TELETEXT_LINE,
            stream_type="subtitle", stream_id=99,
        )
        mock_db.assert_called_once()
        _, kwargs = mock_db.call_args
        self.assertEqual(kwargs.get("subtitle_codec"), "dvb_teletext")
        self.assertEqual(kwargs.get("subtitle_language"), "eng")


class OtherParsersIgnoreSubtitlesTests(TestCase):
    """The base-class default must be concrete, so these parsers need no stubs."""

    def test_vlc_parser_returns_none_for_subtitle_lines(self):
        self.assertIsNone(VLCLogParser().parse_subtitle_stream(TELETEXT_LINE))

    def test_streamlink_parser_returns_none_for_subtitle_lines(self):
        self.assertIsNone(StreamlinkLogParser().parse_subtitle_stream(TELETEXT_LINE))
