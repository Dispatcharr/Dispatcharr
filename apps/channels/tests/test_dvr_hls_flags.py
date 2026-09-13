from django.test import SimpleTestCase

from apps.channels.tasks import _DVR_HLS_FLAGS, _dvr_build_ffmpeg_cmd


class DvrHlsFlagsTests(SimpleTestCase):
    def test_previous_flags_are_kept_verbatim(self):
        self.assertTrue(
            _DVR_HLS_FLAGS.startswith(
                "append_list+omit_endlist+independent_segments"
            )
        )

    def test_program_date_time_is_added(self):
        self.assertEqual(
            _DVR_HLS_FLAGS,
            "append_list+omit_endlist+independent_segments+program_date_time",
        )

    def test_command_carries_the_flags_on_every_attempt(self):
        for start in (0, 4):
            cmd = _dvr_build_ffmpeg_cmd(
                "http://127.0.0.1/proxy/ts/stream/x", 1, "/tmp/index.m3u8",
                "/tmp/seg_%05d.ts", start, user_agent="ua",
            )
            self.assertEqual(cmd[cmd.index("-hls_flags") + 1], _DVR_HLS_FLAGS)
            self.assertEqual(cmd[cmd.index("-start_number") + 1], str(start))

    def test_flags_are_a_single_argument(self):
        self.assertNotIn(" ", _DVR_HLS_FLAGS)
        self.assertNotIn(",", _DVR_HLS_FLAGS)
        self.assertTrue(all(_DVR_HLS_FLAGS.split("+")))
