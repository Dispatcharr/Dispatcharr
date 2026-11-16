from django.test import SimpleTestCase

from core.models import StreamProfile


class StreamProfileBuildCommandTests(SimpleTestCase):
    def _profile(self, parameters):
        return StreamProfile(
            name="Test Profile",
            command="ffmpeg",
            parameters=parameters,
            locked=False,
        )

    def test_substitutes_all_tokens(self):
        profile = self._profile(
            '-i {streamUrl} -user_agent {userAgent} '
            '-metadata channel={channelId} '
            '-metadata title={channelName} '
            '-metadata tvg={tvgId}'
        )
        cmd = profile.build_command(
            "http://example.com/stream.ts",
            "Mozilla/5.0",
            channel_id=42,
            channel_name="News HD",
            tvg_id="epg.news.hd",
        )
        self.assertEqual(
            cmd,
            [
                "ffmpeg",
                "-i",
                "http://example.com/stream.ts",
                "-user_agent",
                "Mozilla/5.0",
                "-metadata",
                "channel=42",
                "-metadata",
                "title=News HD",
                "-metadata",
                "tvg=epg.news.hd",
            ],
        )

    def test_channel_id_defaults_to_empty_string(self):
        profile = self._profile('-metadata channel={channelId}')
        cmd = profile.build_command("http://example.com/stream.ts", "Mozilla/5.0")
        self.assertEqual(cmd, ["ffmpeg", "-metadata", "channel="])

    def test_channel_name_and_tvg_id_default_to_empty_string(self):
        profile = self._profile(
            '-metadata title={channelName} -metadata tvg={tvgId}'
        )
        cmd = profile.build_command("http://example.com/stream.ts", "Mozilla/5.0")
        self.assertEqual(
            cmd,
            ["ffmpeg", "-metadata", "title=", "-metadata", "tvg="],
        )

    def test_no_channel_id_placeholder_unaffected(self):
        profile = self._profile('-i {streamUrl}')
        cmd = profile.build_command(
            "http://example.com/stream.ts", "Mozilla/5.0", channel_id=7
        )
        self.assertEqual(cmd, ["ffmpeg", "-i", "http://example.com/stream.ts"])

    def test_channel_name_with_spaces_stays_single_arg(self):
        profile = self._profile('-metadata title={channelName}')
        cmd = profile.build_command(
            "http://example.com/stream.ts",
            "Mozilla/5.0",
            channel_name="Sports Center HD",
        )
        self.assertEqual(
            cmd,
            ["ffmpeg", "-metadata", "title=Sports Center HD"],
        )
