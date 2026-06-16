import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.db import connection, transaction
from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel
from apps.epg.models import EPGSource, EPGData, ProgramData
from apps.epg.tasks import (
    parse_programs_for_source,
    _flush_epg_program_staging_batch,
    _swap_staged_epg_programs,
    _EPG_PARSE_BATCH_SIZE,
)


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


class ParseProgramsForSourceTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name='XMLTV Parse Test',
            source_type='xmltv',
        )
        self.mapped_epg = EPGData.objects.create(
            epg_source=self.source,
            tvg_id='mapped.channel',
            name='Mapped Channel',
        )
        self.unmapped_epg = EPGData.objects.create(
            epg_source=self.source,
            tvg_id='unmapped.channel',
            name='Unmapped Channel',
        )
        Channel.objects.create(
            channel_number=1,
            name='Mapped Channel',
            epg_data=self.mapped_epg,
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

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_replaces_programs_for_mapped_channels(self, _send_update, _log_event):
        old_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=old_start,
            end_time=old_start + timedelta(hours=1),
            title='Old Programme',
            tvg_id=self.mapped_epg.tvg_id,
        )
        orphan_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=self.unmapped_epg,
            start_time=orphan_start,
            end_time=orphan_start + timedelta(hours=1),
            title='Orphan Programme',
            tvg_id=self.unmapped_epg.tvg_id,
        )

        programmes = (
            _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
            + _programme_xml('unmapped.channel', 'Skipped Show', self.start, self.stop)
        )
        self._configure_source_file(programmes)

        result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        mapped_programs = ProgramData.objects.filter(epg=self.mapped_epg)
        self.assertEqual(mapped_programs.count(), 1)
        self.assertEqual(mapped_programs.get().title, 'New Show')
        self.assertFalse(ProgramData.objects.filter(epg=self.unmapped_epg).exists())

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_atomic_failure_rolls_back_and_preserves_existing_programs(self, _send_update, _log_event):
        old_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=old_start,
            end_time=old_start + timedelta(hours=1),
            title='Keep Me',
            tvg_id=self.mapped_epg.tvg_id,
        )

        self._configure_source_file(
            _programme_xml('mapped.channel', 'Replacement', self.start, self.stop)
        )

        swap_path = (
            'apps.epg.tasks._swap_staged_epg_programs'
            if connection.vendor == 'postgresql'
            else 'apps.epg.tasks._swap_parsed_epg_programs'
        )
        with patch(swap_path, side_effect=RuntimeError('simulated insert failure')):
            result = parse_programs_for_source(self.source)

        self.assertFalse(result)
        self.assertEqual(ProgramData.objects.filter(epg=self.mapped_epg).count(), 1)
        self.assertEqual(
            ProgramData.objects.get(epg=self.mapped_epg).title,
            'Keep Me',
        )

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_streams_batches_without_holding_full_program_list(self, _send_update, _log_event):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL staging batches are required for this assertion')

        programme_count = _EPG_PARSE_BATCH_SIZE * 2
        programmes = ''.join(
            _programme_xml(
                'mapped.channel',
                f'Show {idx}',
                self.start,
                self.stop,
            )
            for idx in range(programme_count)
        )
        self._configure_source_file(programmes)
        flush_sizes = []
        original_flush = _flush_epg_program_staging_batch

        def tracking_flush(batch):
            flush_sizes.append(len(batch))
            return original_flush(batch)

        with patch('apps.epg.tasks._flush_epg_program_staging_batch', side_effect=tracking_flush):
            result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        self.assertEqual(ProgramData.objects.filter(epg=self.mapped_epg).count(), programme_count)
        self.assertEqual(sum(flush_sizes), programme_count)
        self.assertTrue(all(size <= _EPG_PARSE_BATCH_SIZE for size in flush_sizes))
        self.assertGreater(len(flush_sizes), 1)

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_live_programs_remain_until_swap_commits(self, _send_update, _log_event):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL staging swap is required for this assertion')

        old_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=old_start,
            end_time=old_start + timedelta(hours=1),
            title='Old Programme',
            tvg_id=self.mapped_epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        observed_titles_at_swap = []

        def swap_with_visibility_check(mapped_epg_ids, epg_source, *args, **kwargs):
            observed_titles_at_swap.append(
                ProgramData.objects.get(epg=self.mapped_epg).title
            )
            return _swap_staged_epg_programs(mapped_epg_ids, epg_source, *args, **kwargs)

        with patch('apps.epg.tasks._swap_staged_epg_programs', side_effect=swap_with_visibility_check):
            result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        self.assertEqual(observed_titles_at_swap, ['Old Programme'])
        self.assertEqual(ProgramData.objects.get(epg=self.mapped_epg).title, 'New Show')

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_swap_delete_is_rolled_back_when_insert_fails(self, _send_update, _log_event):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL staging swap is required for this assertion')

        old_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=old_start,
            end_time=old_start + timedelta(hours=1),
            title='Keep Me',
            tvg_id=self.mapped_epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('mapped.channel', 'Replacement', self.start, self.stop)
        )

        def failing_swap(mapped_epg_ids, epg_source, *args, **kwargs):
            with transaction.atomic():
                ProgramData.objects.filter(epg_id__in=mapped_epg_ids).delete()
                raise RuntimeError('simulated insert failure')

        with patch('apps.epg.tasks._swap_staged_epg_programs', side_effect=failing_swap):
            result = parse_programs_for_source(self.source)

        self.assertFalse(result)
        self.assertEqual(ProgramData.objects.get(epg=self.mapped_epg).title, 'Keep Me')
