import os
import tempfile
from unittest.mock import patch

from django.test import TestCase

from apps.epg.models import EPGSource, EPGData
from apps.epg.tasks import parse_channels_only


def _channels_xml(channels):
    """Build a minimal XMLTV file from (tvg_id, name, icon_url) tuples."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n', '<tv>\n']
    for tvg_id, name, icon_url in channels:
        parts.append(f'  <channel id="{tvg_id}">\n')
        parts.append(f'    <display-name>{name}</display-name>\n')
        if icon_url:
            parts.append(f'    <icon src="{icon_url}"/>\n')
        parts.append('  </channel>\n')
    parts.append('</tv>\n')
    handle = tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.xml',
        delete=False,
        encoding='utf-8',
    )
    handle.write(''.join(parts))
    handle.close()
    return handle.name


class ParseChannelsOnlyPaginationTests(TestCase):
    def tearDown(self):
        if getattr(self, 'xml_path', None) and os.path.exists(self.xml_path):
            os.unlink(self.xml_path)

    def _configure_source_file(self, source, channels):
        self.xml_path = _channels_xml(channels)
        source.file_path = self.xml_path
        source.save(update_fields=['file_path'])

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_overlapping_tvg_id_does_not_skip_later_source_rows(
        self, _send_update, _log_event
    ):
        """A shared TVG ID in another source must not leave this source's icons stale.

        Source A has rows (a, shared, target). Source B inserts a higher-id
        'shared' row afterward. Refresh of A must still update A's 'target' icon.
        """
        source_a = EPGSource.objects.create(name='Source A', source_type='xmltv')
        source_b = EPGSource.objects.create(name='Source B', source_type='xmltv')

        EPGData.objects.create(
            epg_source=source_a, tvg_id='a', name='A', icon_url='http://old/a.png',
        )
        EPGData.objects.create(
            epg_source=source_a, tvg_id='shared', name='Shared',
            icon_url='http://old/shared.png',
        )
        target = EPGData.objects.create(
            epg_source=source_a, tvg_id='target', name='Target',
            icon_url='http://old/target.png',
        )
        EPGData.objects.create(
            epg_source=source_b, tvg_id='shared', name='Shared B',
            icon_url='http://other/shared.png',
        )

        self.assertGreater(
            EPGData.objects.get(epg_source=source_b, tvg_id='shared').id,
            target.id,
        )

        self._configure_source_file(source_a, [
            ('a', 'A', 'http://new/a.png'),
            ('shared', 'Shared', 'http://new/shared.png'),
            ('target', 'Target', 'http://new/target.png'),
        ])

        self.assertTrue(parse_channels_only(source_a))

        target.refresh_from_db()
        self.assertEqual(target.icon_url, 'http://new/target.png')
        self.assertEqual(
            EPGData.objects.get(epg_source=source_a, tvg_id='a').icon_url,
            'http://new/a.png',
        )
        self.assertEqual(
            EPGData.objects.get(epg_source=source_a, tvg_id='shared').icon_url,
            'http://new/shared.png',
        )
        # Source B's overlapping row must remain untouched.
        self.assertEqual(
            EPGData.objects.get(epg_source=source_b, tvg_id='shared').icon_url,
            'http://other/shared.png',
        )

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_refresh_updates_all_existing_icons(self, _send_update, _log_event):
        """Control: refresh updates every existing channel's icon for the source."""
        source = EPGSource.objects.create(name='Solo Source', source_type='xmltv')
        for tvg_id in ('a', 'b', 'c'):
            EPGData.objects.create(
                epg_source=source,
                tvg_id=tvg_id,
                name=tvg_id.upper(),
                icon_url=f'http://old/{tvg_id}.png',
            )

        self._configure_source_file(source, [
            ('a', 'A', 'http://new/a.png'),
            ('b', 'B', 'http://new/b.png'),
            ('c', 'C', 'http://new/c.png'),
        ])

        self.assertTrue(parse_channels_only(source))

        for tvg_id in ('a', 'b', 'c'):
            self.assertEqual(
                EPGData.objects.get(epg_source=source, tvg_id=tvg_id).icon_url,
                f'http://new/{tvg_id}.png',
            )
