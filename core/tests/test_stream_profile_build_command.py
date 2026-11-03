from django.test import SimpleTestCase, TestCase

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
            '-i {streamUrl} -user_agent {userAgent} -metadata channel={channelId}'
        )
        cmd = profile.build_command(
            "http://example.com/stream.ts", "Mozilla/5.0", channel_id=42
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
            ],
        )

    def test_channel_id_defaults_to_empty_string(self):
        profile = self._profile('-metadata channel={channelId}')
        cmd = profile.build_command("http://example.com/stream.ts", "Mozilla/5.0")
        self.assertEqual(cmd, ["ffmpeg", "-metadata", "channel="])

    def test_no_channel_id_placeholder_unaffected(self):
        profile = self._profile('-i {streamUrl}')
        cmd = profile.build_command("http://example.com/stream.ts", "Mozilla/5.0", channel_id=7)
        self.assertEqual(cmd, ["ffmpeg", "-i", "http://example.com/stream.ts"])


class StreamProfileReferenceExpansionTests(TestCase):
    """{streamProfile=Name} tokens inline another profile's parameters."""

    def setUp(self):
        self.referenced = StreamProfile.objects.create(
            name="TestRef",
            command="ffmpeg",
            parameters=(
                "-fflags +genpts -user_agent {userAgent} "
                "-i {streamUrl} -c copy -f mpegts pipe:1"
            ),
            locked=True,
        )

    def _profile(self, name, parameters, command="ffmpeg"):
        # Unsaved on purpose: building a command must not require a stored row.
        return StreamProfile(name=name, command=command, parameters=parameters)

    def test_expands_referenced_parameters(self):
        profile = self._profile("FFmpeg Custom", "-hide_banner {streamProfile=TestRef}")
        cmd = profile.build_command(
            "http://example.com/stream.ts", "Mozilla/5.0", channel_id=42
        )
        self.assertEqual(
            cmd,
            [
                "ffmpeg",
                "-hide_banner",
                "-fflags",
                "+genpts",
                "-user_agent",
                "Mozilla/5.0",
                "-i",
                "http://example.com/stream.ts",
                "-c",
                "copy",
                "-f",
                "mpegts",
                "pipe:1",
            ],
        )

    def test_reference_matches_name_case_insensitively(self):
        profile = self._profile("Lower", "-x {streamProfile=testref}")
        cmd = profile.build_command("http://example.com/stream.ts", "UA")
        self.assertEqual(
            cmd,
            ["ffmpeg", "-x", "-fflags", "+genpts", "-user_agent", "UA", "-i",
             "http://example.com/stream.ts", "-c", "copy", "-f", "mpegts",
             "pipe:1"],
        )

    def test_referenced_quoting_is_preserved(self):
        StreamProfile.objects.create(
            name="QuotedRef",
            command="ffmpeg",
            parameters='-vf "scale=1280:720" -c copy',
        )
        profile = self._profile("Quoted User", "-hide_banner {streamProfile=QuotedRef}")
        self.assertEqual(
            profile.build_command("http://example.com/stream.ts", "UA"),
            ["ffmpeg", "-hide_banner", "-vf", "scale=1280:720", "-c", "copy"],
        )

    def test_nested_references_expand(self):
        StreamProfile.objects.create(
            name="NestedLeaf", command="ffmpeg", parameters="-c copy"
        )
        StreamProfile.objects.create(
            name="NestedMiddle", command="ffmpeg", parameters="-map 0 {streamProfile=NestedLeaf}"
        )
        profile = self._profile("Top", "-hide_banner {streamProfile=NestedMiddle}")
        self.assertEqual(
            profile.build_command("http://example.com/stream.ts", "UA"),
            ["ffmpeg", "-hide_banner", "-map", "0", "-c", "copy"],
        )

    def test_embedded_token_splices_text(self):
        StreamProfile.objects.create(
            name="SuffixRef", command="ffmpeg", parameters="value"
        )
        profile = self._profile("Embedded", "--opt={streamProfile=SuffixRef}")
        self.assertEqual(
            profile.build_command("http://example.com/stream.ts", "UA"),
            ["ffmpeg", "--opt=value"],
        )

    def test_unknown_reference_builds_no_command(self):
        profile = self._profile("Broken", "-x {streamProfile=UnknownGhost}")
        with self.assertLogs("core.models", level="ERROR") as logs:
            cmd = profile.build_command("http://example.com/stream.ts", "UA")
        self.assertEqual(cmd, [])
        self.assertIn("UnknownGhost", logs.output[0])

    def test_circular_reference_builds_no_command(self):
        loop = StreamProfile.objects.create(
            name="Loop", command="ffmpeg", parameters="-c copy"
        )
        loop.parameters = "-x {streamProfile=Loop}"
        with self.assertLogs("core.models", level="ERROR") as logs:
            cmd = loop.build_command("http://example.com/stream.ts", "UA")
        self.assertEqual(cmd, [])
        self.assertIn("Circular", logs.output[0])

