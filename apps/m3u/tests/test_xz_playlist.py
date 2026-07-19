"""Tests for native xz (.xz) support for uploaded M3U playlists.

Mirrors the existing .gz handling: an uploaded .xz playlist is treated as a
streamable text source (opened lazily via _open_m3u_text_source), never
loaded fully into memory like the .zip path.
"""
import lzma
import os
import tempfile

from django.test import SimpleTestCase, TestCase

from apps.m3u.models import M3UAccount
from apps.m3u.tasks import _open_m3u_text_source, fetch_m3u_lines

SAMPLE_M3U = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-id="channel.one",Channel One\n'
    "http://example.com/stream1\n"
)


class OpenM3uTextSourceXzTests(SimpleTestCase):
    def test_opens_xz_playlist_for_line_by_line_reading(self):
        xz_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xz", delete=False) as xz_file:
                xz_path = xz_file.name
                xz_file.write(lzma.compress(SAMPLE_M3U.encode("utf-8")))

            with _open_m3u_text_source(xz_path) as f:
                content = f.read()

            self.assertEqual(content, SAMPLE_M3U)
        finally:
            if xz_path and os.path.exists(xz_path):
                os.unlink(xz_path)


class FetchM3uLinesXzUploadTests(TestCase):
    def setUp(self):
        self.xz_path = None

    def tearDown(self):
        if self.xz_path and os.path.exists(self.xz_path):
            os.unlink(self.xz_path)

    def test_fetch_m3u_lines_returns_path_for_xz_upload(self):
        with tempfile.NamedTemporaryFile(suffix=".xz", delete=False) as xz_file:
            self.xz_path = xz_file.name
            xz_file.write(lzma.compress(SAMPLE_M3U.encode("utf-8")))

        account = M3UAccount.objects.create(
            name="XZ upload account",
            file_path=self.xz_path,
        )

        source, success = fetch_m3u_lines(account)

        self.assertTrue(success)
        # Like the .gz path, .xz playlists are streamed rather than loaded
        # into memory, so fetch_m3u_lines hands back the path itself.
        self.assertEqual(source, self.xz_path)

        with _open_m3u_text_source(source) as f:
            self.assertEqual(f.read(), SAMPLE_M3U)
