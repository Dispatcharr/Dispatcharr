import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel
from apps.epg.models import EPGSource, EPGData, ProgramData
from apps.epg.tasks import parse_programs_for_tvg_id


def _programme_xml(channel_id, title, start, stop):
    return (
        f'  <programme start="{start}" stop="{stop}" channel="{channel_id}">\n'
        f'    <title>{title}</title>\n'
        f'  </programme>\n'
    )


def _xmltv_file(programmes):
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<tv generator-info-name="test">\n'
        f'{programmes}'
        '</tv>\n'
    )
    handle = tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.xml',
        delete=False,
        encoding='utf-8',
    )
    handle.write(body)
    handle.close()
    return handle.name


class ParseProgramsForTvgIdSwapTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name='Per-Channel Parse Test',
            source_type='xmltv',
        )
        self.epg = EPGData.objects.create(
            epg_source=self.source,
            tvg_id='test.channel',
            name='Test Channel',
        )
        self.channel = Channel.objects.create(
            channel_number=1,
            name='Test Channel',
            epg_data=self.epg,
        )
        self.base_time = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.start = self.base_time.strftime('%Y%m%d%H%M%S +0000')
        self.stop = (self.base_time + timedelta(hours=1)).strftime('%Y%m%d%H%M%S +0000')

    def tearDown(self):
        if getattr(self, 'xml_path', None) and os.path.exists(self.xml_path):
            os.unlink(self.xml_path)

    def _configure_source_file(self, programmes):
        self.xml_path = _xmltv_file(programmes)
        self.source.file_path = self.xml_path
        self.source.save(update_fields=['file_path'])

    def test_replaces_programs_for_channel(self):
        old_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=self.epg,
            start_time=old_start,
            end_time=old_start + timedelta(hours=1),
            title='Old Programme',
            tvg_id=self.epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        programs = ProgramData.objects.filter(epg=self.epg)
        self.assertEqual(programs.count(), 1)
        self.assertEqual(programs.get().title, 'New Show')

    def test_failed_insert_preserves_existing_programs(self):
        """A failed atomic swap must not leave the channel with no guide data."""
        old_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=self.epg,
            start_time=old_start,
            end_time=old_start + timedelta(hours=1),
            title='Keep Me',
            tvg_id=self.epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('test.channel', 'Replacement', self.start, self.stop)
        )

        with patch(
            'apps.epg.tasks.ProgramData.objects.bulk_create',
            side_effect=RuntimeError('simulated insert failure'),
        ):
            with self.assertRaises(RuntimeError):
                parse_programs_for_tvg_id(self.epg.id)

        remaining = ProgramData.objects.filter(epg=self.epg)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.get().title, 'Keep Me')

    def test_does_not_refetch_epg_data_mid_task(self):
        """The task must reuse the EPGData row loaded at task start."""
        self._configure_source_file(
            _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        with patch(
            'apps.epg.tasks.EPGData.objects.get',
            side_effect=AssertionError('should not re-fetch EPGData mid-task'),
        ) as mock_get:
            parse_programs_for_tvg_id(self.epg.id)

        mock_get.assert_not_called()
        self.assertEqual(
            ProgramData.objects.filter(epg=self.epg).get().title, 'New Show'
        )
