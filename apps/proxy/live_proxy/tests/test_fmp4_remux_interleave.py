"""fMP4 remux maps every input stream, so it uses the same short interleave
window as the locked FFmpeg profiles.
"""
from django.test import SimpleTestCase

from apps.proxy.live_proxy.output.fmp4.manager import FFMPEG_REMUX_CMD


class Fmp4RemuxInterleaveTests(SimpleTestCase):
    def test_remux_command_caps_interleave_delta(self):
        map_at = FFMPEG_REMUX_CMD.index("-map")
        self.assertEqual(FFMPEG_REMUX_CMD[map_at + 1], "0")
        self.assertEqual(
            FFMPEG_REMUX_CMD[map_at + 2 : map_at + 4],
            ["-max_interleave_delta", "100K"],
        )
