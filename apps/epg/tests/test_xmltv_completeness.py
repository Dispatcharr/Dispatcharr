"""Lightweight XMLTV completeness checks (trailing </tv>, incomplete downloads)."""
import gzip
import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.channels.models import Channel
from apps.epg.models import EPGSource, EPGData, ProgramData
from apps.epg.tasks import (
    _xmltv_file_is_complete,
    fetch_xmltv,
    parse_programs_for_source,
    parse_programs_for_tvg_id,
)


TRUNCATED_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<tv>\n'
    '  <channel id="mapped.channel"><display-name>Mapped</display-name></channel>\n'
    '  <programme start="{start}" stop="{stop}" channel="mapped.channel">\n'
    '    <title>Show</title>\n'
    '    <sub-title>Cut off mid'
)

CLOUDFLARE_EMAIL_DECODE = (
    b'<script data-cfasync="false" '
    b'src="/cdn-cgi/scripts/5c5dd728/cloudflare-static/email-decode.min.js"></script>'
)


class XmltvFileIsCompleteTests(TestCase):
    def test_complete_file_passes(self):
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as handle:
            handle.write(b'<?xml version="1.0"?><tv><channel id="a"/></tv>\n')
            path = handle.name
        try:
            self.assertTrue(_xmltv_file_is_complete(path))
        finally:
            os.unlink(path)

    def test_truncated_file_fails(self):
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as handle:
            handle.write(b'<?xml version="1.0"?><tv><programme channel="a"><title>X')
            path = handle.name
        try:
            self.assertFalse(_xmltv_file_is_complete(path))
        finally:
            os.unlink(path)

    def test_empty_or_missing_fails(self):
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as handle:
            path = handle.name
        try:
            self.assertFalse(_xmltv_file_is_complete(path))
        finally:
            os.unlink(path)
        self.assertFalse(_xmltv_file_is_complete('/tmp/does-not-exist-xmltv.xml'))

    def test_trailing_whitespace_still_passes(self):
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as handle:
            handle.write(b'<?xml version="1.0"?><tv></tv>\n\n  \n')
            path = handle.name
        try:
            self.assertTrue(_xmltv_file_is_complete(path))
        finally:
            os.unlink(path)

    def test_cdn_markup_after_root_still_passes(self):
        """Cloudflare appends its email-decode script to guides served as text/html."""
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as handle:
            handle.write(
                b'<?xml version="1.0"?><tv><channel id="a"/></tv>'
                + CLOUDFLARE_EMAIL_DECODE
            )
            path = handle.name
        try:
            self.assertTrue(_xmltv_file_is_complete(path))
        finally:
            os.unlink(path)

    def test_inline_script_after_root_still_passes(self):
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as handle:
            handle.write(
                b'<?xml version="1.0"?><tv><channel id="a"/></tv>\n'
                b'<script>if (a < b) { f("<x>"); }</script>\n'
            )
            path = handle.name
        try:
            self.assertTrue(_xmltv_file_is_complete(path))
        finally:
            os.unlink(path)

    def test_closing_tag_inside_cut_off_cdata_fails(self):
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as handle:
            handle.write(
                b'<?xml version="1.0"?><tv><programme channel="a">'
                b'<desc><![CDATA[ends with </tv> but the file was cut'
            )
            path = handle.name
        try:
            self.assertFalse(_xmltv_file_is_complete(path))
        finally:
            os.unlink(path)

    def test_guide_elements_after_closing_tag_fail(self):
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as handle:
            handle.write(
                b'<?xml version="1.0"?><tv><channel id="a"/></tv>\n'
                b'<tv><programme channel="a"><title>X'
            )
            path = handle.name
        try:
            self.assertFalse(_xmltv_file_is_complete(path))
        finally:
            os.unlink(path)


class FetchXmltvCompletenessTests(TestCase):
    def setUp(self):
        self._media = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media)
        self._override.enable()
        self.source = EPGSource.objects.create(
            name='Completeness Fetch',
            source_type='xmltv',
            url='https://example.test/epg.xml',
        )
        self.cache_dir = os.path.join(self._media, 'cached_epg')
        os.makedirs(self.cache_dir, exist_ok=True)
        self.good_xml = os.path.join(self.cache_dir, f'{self.source.id}.xml')
        with open(self.good_xml, 'wb') as handle:
            handle.write(b'<?xml version="1.0"?><tv><channel id="keep"/></tv>\n')
        self.source.file_path = self.good_xml
        self.source.save(update_fields=['file_path'])

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._media, ignore_errors=True)

    def _mock_response(self, body: bytes, content_length=None, wire_bytes=None):
        response = MagicMock()
        response.status_code = 200
        response.headers = {}
        if content_length is not None:
            response.headers['content-length'] = str(content_length)
        response.iter_content = MagicMock(return_value=[body])
        # Content-Length is the on-the-wire size; tell() reports that, which may
        # differ from len(body) when Content-Encoding was decoded by requests.
        if wire_bytes is None:
            wire_bytes = content_length if content_length is not None else len(body)
        response.raw.tell = MagicMock(return_value=wire_bytes)
        response.raise_for_status = MagicMock()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    def test_truncated_download_keeps_previous_cache(self, mock_get, _send):
        mock_get.return_value = self._mock_response(
            b'<?xml version="1.0"?><tv><programme channel="a"><title>X'
        )

        result = fetch_xmltv(self.source)

        self.assertFalse(result)
        self.assertTrue(os.path.exists(self.good_xml))
        with open(self.good_xml, 'rb') as handle:
            self.assertIn(b'<channel id="keep"/>', handle.read())
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, EPGSource.STATUS_ERROR)
        self.assertIn('</tv>', self.source.last_message)
        self.assertFalse(
            os.path.exists(os.path.join(self.cache_dir, f'{self.source.id}.incoming.xml'))
        )

    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    def test_content_length_mismatch_keeps_previous_cache(self, mock_get, _send):
        body = b'<?xml version="1.0"?><tv></tv>\n'
        mock_get.return_value = self._mock_response(
            body, content_length=len(body) + 50, wire_bytes=len(body)
        )

        result = fetch_xmltv(self.source)

        self.assertFalse(result)
        self.assertTrue(os.path.exists(self.good_xml))
        with open(self.good_xml, 'rb') as handle:
            self.assertIn(b'<channel id="keep"/>', handle.read())
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, EPGSource.STATUS_ERROR)
        self.assertIn('incomplete', self.source.last_message.lower())

    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    def test_content_length_uses_wire_bytes_with_content_encoding(self, mock_get, _send):
        """Content-Length is wire size; decoded body may be larger and still succeed."""
        body = b'<?xml version="1.0"?><tv><channel id="new"/></tv>\n'
        wire_size = 10
        response = self._mock_response(
            body, content_length=wire_size, wire_bytes=wire_size
        )
        response.headers['content-encoding'] = 'gzip'
        mock_get.return_value = response

        result = fetch_xmltv(self.source)

        self.assertTrue(result)
        with open(self.good_xml, 'rb') as handle:
            self.assertIn(b'<channel id="new"/>', handle.read())

    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    def test_complete_download_replaces_cache(self, mock_get, _send):
        body = b'<?xml version="1.0"?><tv><channel id="new"/></tv>\n'
        mock_get.return_value = self._mock_response(body, content_length=len(body))

        result = fetch_xmltv(self.source)

        self.assertTrue(result)
        with open(self.good_xml, 'rb') as handle:
            self.assertIn(b'<channel id="new"/>', handle.read())
        self.source.refresh_from_db()
        self.assertEqual(self.source.file_path, self.good_xml)

    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    def test_download_with_cdn_trailer_replaces_cache(self, mock_get, _send):
        body = b'<?xml version="1.0"?><tv><channel id="new"/></tv>' + CLOUDFLARE_EMAIL_DECODE
        mock_get.return_value = self._mock_response(body)

        result = fetch_xmltv(self.source)

        self.assertTrue(result)
        with open(self.good_xml, 'rb') as handle:
            self.assertIn(b'<channel id="new"/>', handle.read())
        self.source.refresh_from_db()
        self.assertNotEqual(self.source.status, EPGSource.STATUS_ERROR)

    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    def test_truncated_gzip_keeps_previous_cache(self, mock_get, _send):
        # Valid gzip header/body that decompresses to truncated XML.
        truncated = b'<?xml version="1.0"?><tv><programme channel="a"><title>X'
        body = gzip.compress(truncated)
        mock_get.return_value = self._mock_response(body)

        result = fetch_xmltv(self.source)

        self.assertFalse(result)
        with open(self.good_xml, 'rb') as handle:
            self.assertIn(b'<channel id="keep"/>', handle.read())


class ParseProgramsRejectsIncompleteXmlTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name='Incomplete Parse',
            source_type='xmltv',
        )
        self.mapped_epg = EPGData.objects.create(
            epg_source=self.source,
            tvg_id='mapped.channel',
            name='Mapped Channel',
        )
        Channel.objects.create(
            channel_number=1,
            name='Mapped Channel',
            epg_data=self.mapped_epg,
        )
        self.base_time = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.start = self.base_time.strftime('%Y%m%d%H%M%S +0000')
        self.stop = (self.base_time + timedelta(hours=1)).strftime('%Y%m%d%H%M%S +0000')
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=self.base_time,
            end_time=self.base_time + timedelta(hours=1),
            title='Keep Me',
            tvg_id=self.mapped_epg.tvg_id,
        )
        self.xml_path = None

    def tearDown(self):
        if self.xml_path and os.path.exists(self.xml_path):
            os.unlink(self.xml_path)

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_incomplete_file_does_not_swap_programs(self, _send, _log):
        handle = tempfile.NamedTemporaryFile(
            mode='w', suffix='.xml', delete=False, encoding='utf-8'
        )
        handle.write(TRUNCATED_XML.format(start=self.start, stop=self.stop))
        handle.close()
        self.xml_path = handle.name
        self.source.file_path = self.xml_path
        self.source.save(update_fields=['file_path'])

        result = parse_programs_for_source(self.source)

        self.assertFalse(result)
        self.assertEqual(ProgramData.objects.get(epg=self.mapped_epg).title, 'Keep Me')
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, EPGSource.STATUS_ERROR)

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_cdn_trailer_after_root_still_parses(self, _send, _log):
        handle = tempfile.NamedTemporaryFile(mode='wb', suffix='.xml', delete=False)
        handle.write(
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n<tv>\n'
                f'  <programme start="{self.start}" stop="{self.stop}" channel="mapped.channel">'
                '<title>New Show</title></programme>\n</tv>'
            ).encode('utf-8')
            + CLOUDFLARE_EMAIL_DECODE
        )
        handle.close()
        self.xml_path = handle.name
        self.source.file_path = self.xml_path
        self.source.save(update_fields=['file_path'])

        result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        self.assertEqual(
            list(ProgramData.objects.filter(epg=self.mapped_epg).values_list('title', flat=True)),
            ['New Show'],
        )

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_per_channel_parse_rejects_incomplete_file(self, _send, _log):
        """The single-channel path must not replace a guide from a truncated file."""
        handle = tempfile.NamedTemporaryFile(
            mode='w', suffix='.xml', delete=False, encoding='utf-8'
        )
        handle.write(TRUNCATED_XML.format(start=self.start, stop=self.stop))
        handle.close()
        self.xml_path = handle.name
        self.source.file_path = self.xml_path
        self.source.save(update_fields=['file_path'])

        with patch('apps.epg.tasks.is_task_lock_held', return_value=False), \
                patch('apps.epg.tasks.acquire_task_lock', return_value=True), \
                patch('apps.epg.tasks.release_task_lock'):
            parse_programs_for_tvg_id(self.mapped_epg.id)

        self.assertEqual(ProgramData.objects.get(epg=self.mapped_epg).title, 'Keep Me')
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, EPGSource.STATUS_ERROR)
        self.assertIn('</tv>', self.source.last_message)


class FetchXmltvLocalFileCompletenessTests(TestCase):
    """Sources with a local file and no URL go through a separate branch."""

    def setUp(self):
        self.xml_path = None

    def tearDown(self):
        if self.xml_path and os.path.exists(self.xml_path):
            os.unlink(self.xml_path)

    def _source_with_file(self, body: bytes):
        handle = tempfile.NamedTemporaryFile(suffix='.xml', delete=False)
        handle.write(body)
        handle.close()
        self.xml_path = handle.name
        return EPGSource.objects.create(
            name='Local XMLTV',
            source_type='xmltv',
            file_path=self.xml_path,
        )

    @patch('apps.epg.tasks.send_epg_update')
    def test_truncated_local_file_is_rejected(self, _send):
        source = self._source_with_file(
            b'<?xml version="1.0"?><tv><programme channel="a"><title>X'
        )

        self.assertFalse(fetch_xmltv(source))

        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_ERROR)
        self.assertIn('</tv>', source.last_message)

    @patch('apps.epg.tasks.send_epg_update')
    def test_complete_local_file_is_accepted(self, _send):
        source = self._source_with_file(
            b'<?xml version="1.0"?><tv><channel id="a"/></tv>\n'
        )

        self.assertTrue(fetch_xmltv(source))

        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_SUCCESS)
