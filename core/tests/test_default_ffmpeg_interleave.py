"""The locked FFmpeg stream profile maps every input stream and caps the
muxer interleave window so an empty data PID cannot hold the startup buffer.
"""
from django.test import TestCase

from core.models import FFMPEG_PROFILE_NAME, StreamProfile


class SeededFfmpegProfileInterleaveTests(TestCase):
    def test_locked_ffmpeg_profile_exact_parameters(self):
        profile = StreamProfile.objects.get(name=FFMPEG_PROFILE_NAME, locked=True)
        self.assertEqual(
            profile.parameters,
            (
                "-fflags +genpts+discardcorrupt "
                "-user_agent {userAgent} "
                "-i {streamUrl} "
                "-map 0 "
                "-max_interleave_delta 100K "
                "-c copy "
                "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
                "-f mpegts pipe:1"
            ),
        )
