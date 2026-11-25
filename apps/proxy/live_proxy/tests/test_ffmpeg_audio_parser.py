"""FFmpeg audio log parsing: keep all tracks, summarize the best."""
from django.test import SimpleTestCase

from apps.proxy.live_proxy.services.log_parsers import (
    FFmpegLogParser,
    channel_layout_rank,
    decode_audio_streams,
    merge_audio_track,
    select_best_audio_track,
)


class DecodeAudioStreamsTests(SimpleTestCase):
    tracks = [{"index": 1, "audio_channels": "5.1"}]

    def test_decodes_json_text_and_bytes(self):
        self.assertEqual(decode_audio_streams('[{"index":1,"audio_channels":"5.1"}]'), self.tracks)
        self.assertEqual(decode_audio_streams(b'[{"index":1,"audio_channels":"5.1"}]'), self.tracks)

    def test_passes_through_a_list(self):
        self.assertEqual(decode_audio_streams(self.tracks), self.tracks)

    def test_returns_none_for_unusable_values(self):
        for value in (None, "", "[]", [], "not json", '{"a": 1}', 5):
            self.assertIsNone(decode_audio_streams(value), value)


class FFmpegAudioParserTests(SimpleTestCase):
    def setUp(self):
        self.parser = FFmpegLogParser()

    def test_parses_language_channels_and_index(self):
        line = (
            "  Stream #0:1[0x101](eng): Audio: ac3 (AC-3 / 0x332D4341), "
            "48000 Hz, 5.1(side), fltp, 384 kb/s, start 1.0"
        )
        parsed = self.parser.parse_audio_stream(line)
        self.assertEqual(parsed["audio_codec"], "ac3")
        self.assertEqual(parsed["audio_channels"], "5.1")
        self.assertEqual(parsed["audio_language"], "eng")
        self.assertEqual(parsed["index"], 1)
        self.assertEqual(parsed["audio_bitrate"], 384.0)
        self.assertEqual(parsed["audio_track"]["audio_language"], "eng")

    def test_parses_stereo_aac(self):
        line = (
            "  Stream #0:2[0x102](spa): Audio: aac (HE-AAC) "
            "([15][0][0][0] / 0x000F), 48000 Hz, stereo, fltp, 96 kb/s"
        )
        parsed = self.parser.parse_audio_stream(line)
        self.assertEqual(parsed["audio_codec"], "aac")
        self.assertEqual(parsed["audio_channels"], "stereo")
        self.assertEqual(parsed["audio_language"], "spa")
        self.assertEqual(parsed["index"], 2)

    def test_undetermined_language_is_not_reported(self):
        line = (
            "  Stream #0:1[0x101](und): Audio: aac (LC) ([15][0][0][0] / 0x000F), "
            "48000 Hz, stereo, fltp, 127 kb/s"
        )
        parsed = self.parser.parse_audio_stream(line)
        self.assertNotIn("audio_language", parsed)
        self.assertNotIn("audio_language", parsed["audio_track"])
        self.assertEqual(parsed["audio_channels"], "stereo")

    def test_parses_n_channels_fallback(self):
        line = "  Stream #0:1: Audio: aac (LC), 48000 Hz, 6 channels, fltp, 384 kb/s"
        parsed = self.parser.parse_audio_stream(line)
        self.assertEqual(parsed["audio_channels"], "5.1")

    def test_ignores_start_timestamp_as_layout(self):
        line = (
            "  Stream #0:1[0x101]: Audio: aac ([15][0][0][0] / 0x000F), "
            "0 channels, fltp, start 45961.400000"
        )
        parsed = self.parser.parse_audio_stream(line)
        # Incomplete probes should not invent a layout from the start time.
        self.assertNotIn("audio_channels", parsed)
        self.assertEqual(parsed["audio_codec"], "aac")


class AudioTrackSelectionTests(SimpleTestCase):
    def test_prefers_surround_over_later_stereo(self):
        tracks = []
        for track in (
            {
                "index": 1,
                "audio_language": "eng",
                "audio_codec": "ac3",
                "audio_channels": "5.1",
                "audio_bitrate": 384.0,
            },
            {
                "index": 2,
                "audio_language": "eng",
                "audio_codec": "aac",
                "audio_channels": "stereo",
                "audio_bitrate": 96.0,
            },
            {
                "index": 3,
                "audio_language": "spa",
                "audio_codec": "ac3",
                "audio_channels": "stereo",
                "audio_bitrate": 384.0,
            },
            {
                "index": 4,
                "audio_language": "spa",
                "audio_codec": "aac",
                "audio_channels": "stereo",
                "audio_bitrate": 96.0,
            },
        ):
            tracks = merge_audio_track(tracks, track)

        self.assertEqual(len(tracks), 4)
        best = select_best_audio_track(tracks)
        self.assertEqual(best["audio_channels"], "5.1")
        self.assertEqual(best["audio_codec"], "ac3")
        self.assertEqual(best["audio_language"], "eng")

    def test_upsert_by_index(self):
        tracks = merge_audio_track(
            [],
            {"index": 1, "audio_codec": "ac3", "audio_channels": "stereo"},
        )
        tracks = merge_audio_track(
            tracks,
            {"index": 1, "audio_channels": "5.1", "audio_bitrate": 384.0},
        )
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["audio_channels"], "5.1")
        self.assertEqual(tracks[0]["audio_codec"], "ac3")

    def test_merges_partial_unindexed_vlc_line_into_richer_line(self):
        tracks = merge_audio_track(
            [],
            {"audio_codec": "aac"},
        )
        tracks = merge_audio_track(
            tracks,
            {
                "audio_codec": "aac",
                "audio_channels": "stereo",
                "sample_rate": 48000,
            },
        )
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["audio_channels"], "stereo")
        self.assertEqual(tracks[0]["sample_rate"], 48000)

    def test_dedupes_unindexed_vlc_tracks_by_fingerprint(self):
        track = {
            "audio_codec": "aac",
            "audio_channels": "stereo",
            "sample_rate": 48000,
        }
        tracks = merge_audio_track([], track)
        tracks = merge_audio_track(tracks, dict(track))
        tracks = merge_audio_track(
            tracks,
            {
                "audio_codec": "ac3",
                "audio_channels": "5.1",
                "sample_rate": 48000,
            },
        )
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0]["audio_codec"], "aac")
        self.assertEqual(tracks[1]["audio_channels"], "5.1")

    def test_channel_rank_orders_layouts(self):
        self.assertGreater(channel_layout_rank("5.1"), channel_layout_rank("stereo"))
        self.assertGreater(channel_layout_rank("7.1"), channel_layout_rank("5.1"))
        self.assertGreater(channel_layout_rank("stereo"), channel_layout_rank("mono"))
