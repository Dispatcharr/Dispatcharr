"""Proposal 1 (Dispatcharr#259 / #1502): the two seeded default OutputProfiles
must carry ``-c:s copy`` so a channel with a DVB teletext or DVB subtitle PID
does not crash the live proxy with ``Encoder not found`` (today's behaviour
with no explicit subtitle codec) while remaining byte-identical in behaviour
on subtitle-free streams.
"""
from django.test import TestCase

from core.models import OutputProfile


class SeededOutputProfilesCarrySubtitleCopyTests(TestCase):
    def test_media_server_profile_carries_c_s_copy(self):
        profile = OutputProfile.objects.get(name="Media Server (AC3 Audio)")
        self.assertIn("-c:s copy", profile.parameters)

    def test_web_player_profile_carries_c_s_copy(self):
        profile = OutputProfile.objects.get(name="Web Player (AAC Audio)")
        self.assertIn("-c:s copy", profile.parameters)

    def test_media_server_profile_exact_parameters(self):
        profile = OutputProfile.objects.get(name="Media Server (AC3 Audio)")
        self.assertEqual(
            profile.parameters,
            (
                "-fflags +discardcorrupt+genpts+nobuffer "
                "-probesize 512K "
                "-analyzeduration 0 "
                "-i pipe:0 "
                "-map 0 "
                "-c:v copy "
                "-c:a ac3 "
                "-b:a 384k "
                "-c:s copy "
                "-max_muxing_queue_size 4096 "
                "-flush_packets 1 "
                "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
                "-f mpegts pipe:1"
            ),
        )

    def test_web_player_profile_exact_parameters(self):
        profile = OutputProfile.objects.get(name="Web Player (AAC Audio)")
        self.assertEqual(
            profile.parameters,
            (
                "-fflags +discardcorrupt+genpts+nobuffer "
                "-probesize 512K "
                "-analyzeduration 0 "
                "-i pipe:0 "
                "-map 0 "
                "-c:v copy "
                "-c:a aac "
                "-b:a 192k "
                "-ac 2 "
                "-c:s copy "
                "-max_muxing_queue_size 4096 "
                "-flush_packets 1 "
                "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
                "-f mpegts pipe:1"
            ),
        )

    def test_profiles_remain_locked(self):
        for name in ("Media Server (AC3 Audio)", "Web Player (AAC Audio)"):
            self.assertTrue(OutputProfile.objects.get(name=name).locked)
