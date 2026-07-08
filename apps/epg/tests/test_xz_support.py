"""Tests for native xz (.xz) support in EPG source ingestion.

Covers the three dispatch points that previously only recognized gzip/zip:
- detect_file_format() format sniffing (magic bytes, extension, mimetype)
- extract_compressed_file() decompression
- EPGSource.get_cache_file() extension inference for uploaded files
"""
import lzma
import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.epg.models import EPGSource
from apps.epg.tasks import detect_file_format, extract_compressed_file

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


class DetectFileFormatXzTests(SimpleTestCase):
    def test_detects_xz_by_magic_bytes(self):
        compressed = lzma.compress(SAMPLE_XML.encode("utf-8"))

        format_type, is_compressed, file_extension = detect_file_format(
            content=compressed[:64]
        )

        self.assertEqual(format_type, "xz")
        self.assertTrue(is_compressed)
        self.assertEqual(file_extension, ".xz")

    def test_detects_xz_by_extension(self):
        format_type, is_compressed, file_extension = detect_file_format(
            file_path="/tmp/epg_source.xz"
        )

        self.assertEqual(format_type, "xz")
        self.assertTrue(is_compressed)
        self.assertEqual(file_extension, ".xz")

    def test_detects_xz_with_compound_extension(self):
        # Compound extensions like .xml.xz must prioritize the compression
        # extension, matching the existing .xml.gz behavior.
        format_type, is_compressed, file_extension = detect_file_format(
            file_path="/tmp/epg_source.xml.xz"
        )

        self.assertEqual(format_type, "xz")
        self.assertTrue(is_compressed)
        self.assertEqual(file_extension, ".xz")

    def test_detects_xz_by_mimetype_fallback(self):
        # Python's stdlib mimetypes module treats .xz as an *encoding*
        # suffix rather than a full MIME type (mirroring .gz), so the
        # mimetype branch is only reachable when guess_type is coerced to
        # return the MIME type directly (e.g. a customized mimetypes
        # configuration). Exercise that fallback branch directly, matching
        # how the existing gzip/zip mimetype fallback branches are tested.
        with patch("mimetypes.guess_type", return_value=("application/x-xz", None)):
            format_type, is_compressed, file_extension = detect_file_format(
                file_path="/tmp/epg_source_with_no_known_suffix"
            )

        self.assertEqual(format_type, "xz")
        self.assertTrue(is_compressed)
        self.assertEqual(file_extension, ".xz")

    def test_content_magic_bytes_take_priority_over_extension(self):
        compressed = lzma.compress(SAMPLE_XML.encode("utf-8"))

        # Mismatched extension should not override a confident content match.
        format_type, is_compressed, file_extension = detect_file_format(
            file_path="/tmp/misleading_name.gz", content=compressed[:64]
        )

        self.assertEqual(format_type, "xz")
        self.assertTrue(is_compressed)
        self.assertEqual(file_extension, ".xz")


class ExtractCompressedFileXzTests(SimpleTestCase):
    def test_round_trips_lzma_compressed_xmltv_to_identical_xml(self):
        xz_path = None
        xml_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".xml.xz", delete=False
            ) as xz_file:
                xz_path = xz_file.name
                xz_file.write(lzma.compress(SAMPLE_XML.encode("utf-8")))

            xml_path = f"{os.path.splitext(os.path.splitext(xz_path)[0])[0]}.xml"

            extracted_path = extract_compressed_file(xz_path, xml_path)

            self.assertEqual(extracted_path, xml_path)
            with open(extracted_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), SAMPLE_XML)
        finally:
            if xz_path and os.path.exists(xz_path):
                os.unlink(xz_path)
            if xml_path and os.path.exists(xml_path):
                os.unlink(xml_path)

    def test_extracts_xz_file_detected_purely_by_magic_bytes(self):
        # No .xz suffix at all - detection must rely on the LZMA magic
        # number, not the filename.
        xz_path = None
        xml_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".bin", delete=False
            ) as xz_file:
                xz_path = xz_file.name
                xz_file.write(lzma.compress(SAMPLE_XML.encode("utf-8")))

            xml_path = f"{os.path.splitext(xz_path)[0]}.xml"

            extracted_path = extract_compressed_file(xz_path, xml_path)

            self.assertEqual(extracted_path, xml_path)
            with open(extracted_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), SAMPLE_XML)
        finally:
            if xz_path and os.path.exists(xz_path):
                os.unlink(xz_path)
            if xml_path and os.path.exists(xml_path):
                os.unlink(xml_path)

    def test_deletes_original_when_requested(self):
        xz_path = None
        xml_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".xml.xz", delete=False
            ) as xz_file:
                xz_path = xz_file.name
                xz_file.write(lzma.compress(SAMPLE_XML.encode("utf-8")))

            xml_path = f"{os.path.splitext(os.path.splitext(xz_path)[0])[0]}.xml"

            extracted_path = extract_compressed_file(
                xz_path, xml_path, delete_original=True
            )

            self.assertEqual(extracted_path, xml_path)
            self.assertFalse(os.path.exists(xz_path))
        finally:
            xz_path = None  # already deleted by extract_compressed_file
            if xml_path and os.path.exists(xml_path):
                os.unlink(xml_path)


class ExtractCompressedFileCorruptXzTests(SimpleTestCase):
    def test_corrupt_xz_fails_closed_with_no_partial_output(self):
        # Valid LZMA magic bytes (fd 37 7a 58 5a 00) followed by garbage: the
        # format sniff reports 'xz' (magic bytes match), but decompression
        # itself must fail. extract_compressed_file() wraps this in a
        # blanket except Exception so a corrupt/truncated upload can never
        # raise out of the Celery worker - it must return None instead.
        xz_path = None
        xml_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".xz", delete=False
            ) as xz_file:
                xz_path = xz_file.name
                xz_file.write(b"\xfd7zXZ\x00" + b"not actually lzma data" * 20)

            xml_path = f"{os.path.splitext(xz_path)[0]}.xml"

            extracted_path = extract_compressed_file(xz_path, xml_path)

            self.assertIsNone(extracted_path)
            self.assertFalse(
                os.path.exists(xml_path),
                "extract_compressed_file must not leave a partial output file "
                "behind when decompression fails",
            )
        finally:
            if xz_path and os.path.exists(xz_path):
                os.unlink(xz_path)
            if xml_path and os.path.exists(xml_path):
                os.unlink(xml_path)


class EPGSourceGetCacheFileXzTests(SimpleTestCase):
    def test_infers_xz_extension_from_mimetype(self):
        xz_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix="", delete=False
            ) as xz_file:
                xz_path = xz_file.name
                xz_file.write(lzma.compress(SAMPLE_XML.encode("utf-8")))

            source = EPGSource(
                name="XZ mimetype source",
                source_type="xmltv",
                file_path=xz_path,
            )

            with patch(
                "mimetypes.guess_type", return_value=("application/x-xz", None)
            ):
                cache_file = source.get_cache_file()

            self.assertTrue(cache_file.endswith(".xz"))
        finally:
            if xz_path and os.path.exists(xz_path):
                os.unlink(xz_path)

    def test_infers_xz_extension_from_magic_bytes(self):
        xz_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix="", delete=False
            ) as xz_file:
                xz_path = xz_file.name
                xz_file.write(lzma.compress(SAMPLE_XML.encode("utf-8")))

            source = EPGSource(
                name="XZ magic bytes source",
                source_type="xmltv",
                file_path=xz_path,
            )

            # No mimetype guess available and no extension on disk - must
            # fall back to sniffing the LZMA magic number.
            with patch("mimetypes.guess_type", return_value=(None, None)):
                cache_file = source.get_cache_file()

            self.assertTrue(cache_file.endswith(".xz"))
        finally:
            if xz_path and os.path.exists(xz_path):
                os.unlink(xz_path)


class EPGSourceGetCacheFileRawXmlTests(SimpleTestCase):
    """Regression coverage for the bare-<tv> raw-XML magic-byte detection.

    get_cache_file()'s magic-byte read was widened from f.read(4) to
    f.read(6) to fit the 6-byte xz signature. That widening broke the
    fixed-length slice comparison `header[:5] == b'<tv>'`: a 5-byte slice
    of a 6-byte header can never equal the 4-byte literal b'<tv>', so a
    raw (uncompressed) XMLTV file with no filename extension and no
    resolvable mimetype was silently misdetected as '.tmp' instead of
    '.xml'. Using header.startswith(...) instead of a fixed-length slice
    comparison is correct regardless of how many bytes are read.
    """

    def _cache_file_for_content(self, content):
        raw_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix="", delete=False) as raw_file:
                raw_path = raw_file.name
                raw_file.write(content)

            source = EPGSource(
                name="Raw XML source",
                source_type="xmltv",
                file_path=raw_path,
            )

            # No extension on disk and no resolvable mimetype - detection
            # must fall back to sniffing the magic bytes.
            with patch("mimetypes.guess_type", return_value=(None, None)):
                return source.get_cache_file()
        finally:
            if raw_path and os.path.exists(raw_path):
                os.unlink(raw_path)

    def test_infers_xml_extension_from_bare_tv_tag(self):
        cache_file = self._cache_file_for_content(SAMPLE_XML.split("\n", 1)[1].encode("utf-8"))

        self.assertTrue(cache_file.endswith(".xml"))

    def test_infers_xml_extension_from_xml_declaration(self):
        cache_file = self._cache_file_for_content(SAMPLE_XML.encode("utf-8"))

        self.assertTrue(cache_file.endswith(".xml"))
