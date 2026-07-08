"""End-to-end coverage for fetch_xmltv() against a local xz-compressed
XMLTV file (no URL), mirroring FetchM3uLinesXzUploadTests in
apps/m3u/tests/test_xz_playlist.py.

fetch_xmltv is mocked everywhere else in the suite, so this exercises the
local-file-with-no-url branch (apps/epg/tasks.py fetch_xmltv) end to end:
detection, extraction via extract_compressed_file(), and the
extracted_file_path bookkeeping - with no mocking beyond what's needed to
keep the test hermetic (Celery Beat periodic task scheduling touches the
django_celery_beat tables in ways unrelated to this behavior).
"""
import lzma
import os
import tempfile

from django.test import TestCase

from apps.epg.models import EPGSource
from apps.epg.tasks import fetch_xmltv

SAMPLE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<tv>\n"
    '  <channel id="xz.channel"/>\n'
    '  <programme channel="xz.channel" '
    'start="20000101000000 +0000" stop="20991231235959 +0000">\n'
    "    <title>XZ Title</title>\n"
    "  </programme>\n"
    "</tv>\n"
)


class FetchXmltvXzLocalFileTests(TestCase):
    def setUp(self):
        self.xz_path = None
        self.source = None

    def tearDown(self):
        if self.xz_path and os.path.exists(self.xz_path):
            os.unlink(self.xz_path)
        if (
            self.source
            and self.source.extracted_file_path
            and os.path.exists(self.source.extracted_file_path)
        ):
            os.unlink(self.source.extracted_file_path)

    def test_fetch_xmltv_extracts_local_xz_file(self):
        with tempfile.NamedTemporaryFile(suffix=".xz", delete=False) as xz_file:
            self.xz_path = xz_file.name
            xz_file.write(lzma.compress(SAMPLE_XML.encode("utf-8")))

        self.source = EPGSource.objects.create(
            name="XZ local file source",
            source_type="xmltv",
            file_path=self.xz_path,
        )

        result = fetch_xmltv(self.source)

        self.assertTrue(result)

        self.source.refresh_from_db()
        self.assertEqual(self.source.status, EPGSource.STATUS_SUCCESS)
        self.assertTrue(self.source.extracted_file_path)
        self.assertTrue(os.path.exists(self.source.extracted_file_path))

        with open(self.source.extracted_file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), SAMPLE_XML)

        # The original compressed file is kept - fetch_xmltv extracts
        # without deleting the source upload.
        self.assertTrue(os.path.exists(self.xz_path))
