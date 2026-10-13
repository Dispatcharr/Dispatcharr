"""Tests for tolerant decoding of non-UTF-8 bytes in M3U playlists.

Real-world provider playlists occasionally contain stray non-UTF-8 bytes
(e.g. a Latin-1 logo URL). Strict decoding crashed the whole refresh with
UnicodeDecodeError; all playlist read paths must degrade gracefully instead.
"""
import gzip
import lzma
import os
import tempfile
import zipfile

from django.test import SimpleTestCase, TestCase

from apps.m3u.models import M3UAccount
from apps.m3u.tasks import _open_m3u_text_source, fetch_m3u_lines

# One Latin-1 byte (0xee, "î") inside an otherwise valid playlist, mirroring
# a provider logo URL observed in production.
BAD_LINE = b'#EXTINF:-1 tvg-logo="http://cdn.example.com/cha\xeene.png",Some Channel\n'
SAMPLE_BAD_M3U = b"#EXTM3U\n" + BAD_LINE + b"http://example.com/stream1\n"
EXPECTED_LOGO_URL = "http://cdn.example.com/chane.png"


class OpenM3uTextSourceEncodingTests(SimpleTestCase):
    def _assert_reads_without_crashing(self, suffix, payload):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(payload)
            with _open_m3u_text_source(tmp_path) as f:
                content = f.read()
            self.assertIn("Some Channel", content)
            self.assertIn("http://example.com/stream1", content)
            self.assertIn(EXPECTED_LOGO_URL, content)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_plain_playlist_with_latin1_byte(self):
        self._assert_reads_without_crashing(".m3u", SAMPLE_BAD_M3U)

    def test_gz_playlist_with_latin1_byte(self):
        self._assert_reads_without_crashing(".gz", gzip.compress(SAMPLE_BAD_M3U))

    def test_xz_playlist_with_latin1_byte(self):
        self._assert_reads_without_crashing(".xz", lzma.compress(SAMPLE_BAD_M3U))


class FetchM3uLinesZipEncodingTests(TestCase):
    def setUp(self):
        self.zip_path = None

    def tearDown(self):
        if self.zip_path and os.path.exists(self.zip_path):
            os.unlink(self.zip_path)

    def test_zip_upload_with_latin1_byte(self):
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            self.zip_path = tmp.name
        with zipfile.ZipFile(self.zip_path, "w") as zf:
            zf.writestr("playlist.m3u", SAMPLE_BAD_M3U)

        account = M3UAccount.objects.create(
            name="ZIP encoding account",
            file_path=self.zip_path,
        )

        lines, success = fetch_m3u_lines(account)

        self.assertTrue(success)
        self.assertTrue(any("Some Channel" in line for line in lines))
        self.assertTrue(any(EXPECTED_LOGO_URL in line for line in lines))
