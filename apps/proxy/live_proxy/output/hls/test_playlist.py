"""
Unit tests for HLS playlist rendering and segment-journal parsing.

Standalone (no Django, no Redis): run with
    python -m unittest apps.proxy.live_proxy.output.hls.test_playlist
"""

import unittest

from .playlist import parse_segment_list_line, render_media_playlist


class SegmentJournalTests(unittest.TestCase):
    def test_parse_basic_line(self):
        name, start, end = parse_segment_list_line(
            "/tmp/dispatcharr-hls-abc/s001-000042.ts,168.480000,173.520000\n"
        )
        self.assertEqual(name, "/tmp/dispatcharr-hls-abc/s001-000042.ts")
        self.assertAlmostEqual(start, 168.48)
        self.assertAlmostEqual(end, 173.52)
        self.assertAlmostEqual(end - start, 5.04)

    def test_parse_rejects_malformed(self):
        for bad in ("", "\n", "no-times.ts", "a.ts,1.0", "a.ts,x,y", ",1.0,2.0"):
            with self.assertRaises(ValueError):
                parse_segment_list_line(bad)

    def test_parse_zero_start(self):
        name, start, end = parse_segment_list_line("s001-000000.ts,0.000000,4.200000")
        self.assertEqual(name, "s001-000000.ts")
        self.assertEqual(start, 0.0)
        self.assertAlmostEqual(end, 4.2)


class PlaylistTests(unittest.TestCase):
    def test_render_basic(self):
        window = [
            {"seq": 7, "dur": 4.0, "disc": False},
            {"seq": 8, "dur": 4.2, "disc": False},
            {"seq": 9, "dur": 3.9, "disc": True},
        ]
        text = render_media_playlist(window, 4)
        self.assertIn("#EXTM3U", text)
        self.assertIn("#EXT-X-VERSION:3", text)
        self.assertIn("#EXT-X-TARGETDURATION:5", text)       # ceil(4.2)
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:7", text)
        self.assertIn("#EXTINF:4.200,", text)
        self.assertIn("8.ts", text)
        self.assertNotIn("#EXT-X-ENDLIST", text)             # live
        # Live-edge start frozen at 2.5x the config target (2.5*4=10), emitted
        # because the window (12.1s) is deep enough to honor it.
        self.assertIn("#EXT-X-START:TIME-OFFSET=-10.000,PRECISE=YES", text)
        # Discontinuity tag must precede its segment
        lines = text.splitlines()
        self.assertEqual(lines[lines.index("#EXT-X-DISCONTINUITY") + 2], "9.ts")

    def test_render_empty_window(self):
        text = render_media_playlist([], 4)
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:0", text)
        self.assertIn("#EXT-X-TARGETDURATION:4", text)       # ceil(4)
        self.assertNotIn("#EXT-X-START", text)               # no segments to offset from

    def test_targetduration_constant_across_window_shift(self):
        # RFC 8216 6.2.1: TARGETDURATION MUST NOT change across reloads. With a
        # frozen adv_target the emitted value is identical no matter how the
        # window's max EXTINF flaps across integer ceilings.
        adv = 8
        w1 = [{"seq": 1, "dur": 4.05, "disc": False}, {"seq": 2, "dur": 4.60, "disc": False}]
        w2 = [{"seq": 2, "dur": 4.60, "disc": False}, {"seq": 3, "dur": 6.46, "disc": False}]
        w3 = [{"seq": 3, "dur": 6.46, "disc": False}, {"seq": 4, "dur": 5.01, "disc": False}]
        tds = set()
        starts = set()
        for w in (w1, w2, w3):
            text = render_media_playlist(w, 4, adv_target=adv)
            td = [ln for ln in text.splitlines() if ln.startswith("#EXT-X-TARGETDURATION")]
            self.assertEqual(td, ["#EXT-X-TARGETDURATION:8"])
            tds.update(td)
            starts.update(ln for ln in text.splitlines() if ln.startswith("#EXT-X-START"))
            # TD must be >= every rounded EXTINF (RFC 8216 4.3.3.1).
            for e in w:
                self.assertLessEqual(round(e["dur"]), adv)
        self.assertEqual(len(tds), 1)      # never changed
        self.assertEqual(len(starts), 1)   # EXT-X-START also byte-stable


if __name__ == "__main__":
    unittest.main()
