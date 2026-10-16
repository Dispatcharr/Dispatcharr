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
    _delete_orphaned_epg_programs,
    _dispatch_late_mapped_epg_parses,
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
        """A stale row inside the freshly-parsed window is replaced, not kept alongside it."""
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=self.base_time,
            end_time=self.base_time + timedelta(hours=1),
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
    def test_replaces_a_stale_row_that_only_overlaps_the_feed_window(self, _send_update, _log_event):
        """A stale row need not be fully contained in the feed window to be superseded."""
        overlap_start = self.base_time - timedelta(minutes=30)
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=overlap_start,
            end_time=overlap_start + timedelta(hours=1),
            title='Overlapping Stale Programme',
            tvg_id=self.mapped_epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        titles = set(
            ProgramData.objects.filter(epg=self.mapped_epg).values_list('title', flat=True)
        )
        self.assertEqual(titles, {'New Show'})

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_retains_history_outside_the_current_pull(self, _send_update, _log_event):
        """A recent programme absent from this pull survives, it's not just what the feed re-sent."""
        recent_start = self.base_time - timedelta(hours=6)
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=recent_start,
            end_time=recent_start + timedelta(hours=1),
            title='Earlier Today',
            tvg_id=self.mapped_epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        titles = set(
            ProgramData.objects.filter(epg=self.mapped_epg).values_list('title', flat=True)
        )
        self.assertEqual(titles, {'Earlier Today', 'New Show'})

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_prunes_programs_past_the_retention_window(self, _send_update, _log_event):
        """A programme old enough that no catchup_days could reach it gets pruned regardless."""
        stale_start = self.base_time - timedelta(days=40)
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=stale_start,
            end_time=stale_start + timedelta(hours=1),
            title='Ancient Programme',
            tvg_id=self.mapped_epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        titles = set(
            ProgramData.objects.filter(epg=self.mapped_epg).values_list('title', flat=True)
        )
        self.assertEqual(titles, {'New Show'})

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_retains_extra_history_for_catchup_enabled_channel(self, _send_update, _log_event):
        """A channel's own catchup_days extends the retention window past the one-day default."""
        channel = Channel.objects.get(epg_data=self.mapped_epg)
        channel.is_catchup = True
        channel.catchup_days = 7
        channel.save(update_fields=['is_catchup', 'catchup_days'])

        old_start = self.base_time - timedelta(days=5)
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=old_start,
            end_time=old_start + timedelta(hours=1),
            title='Five Days Ago',
            tvg_id=self.mapped_epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        titles = set(
            ProgramData.objects.filter(epg=self.mapped_epg).values_list('title', flat=True)
        )
        self.assertEqual(titles, {'Five Days Ago', 'New Show'})

    def _fmt(self, when):
        return when.strftime('%Y%m%d%H%M%S +0000')

    def _stored(self, title, start, hours=1):
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=start,
            end_time=start + timedelta(hours=hours),
            title=title,
            tvg_id=self.mapped_epg.tvg_id,
        )

    def _titles(self):
        return set(
            ProgramData.objects.filter(epg=self.mapped_epg).values_list('title', flat=True)
        )

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_keeps_a_row_that_ends_exactly_at_first_start(self, _send_update, _log_event):
        self._stored('Ends At First Start', self.base_time - timedelta(hours=1))
        self._configure_source_file(
            _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        self.assertTrue(parse_programs_for_source(self.source))

        self.assertEqual(self._titles(), {'Ends At First Start', 'New Show'})

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_replaces_rows_after_a_shorter_pull(self, _send_update, _log_event):
        """A stored row that sits after the new pull's last end is replaced too."""
        self._stored('Stale Tail', self.base_time + timedelta(hours=5))
        self._configure_source_file(
            _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        self.assertTrue(parse_programs_for_source(self.source))

        self.assertEqual(self._titles(), {'New Show'})

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_programme_spanning_the_cutoff_is_added_on_first_import(self, _send_update, _log_event):
        """Without a stored copy, the programme across the cutoff is still inserted."""
        span_start = self.base_time - timedelta(days=1, minutes=30)
        span_end = span_start + timedelta(hours=2)
        self._configure_source_file(
            _programme_xml('mapped.channel', 'Across Cutoff', self._fmt(span_start), self._fmt(span_end))
            + _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        self.assertTrue(parse_programs_for_source(self.source))

        rows = ProgramData.objects.filter(epg=self.mapped_epg)
        self.assertEqual(rows.filter(title='Across Cutoff').count(), 1)
        self.assertEqual(rows.filter(title='New Show').count(), 1)

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_programme_spanning_the_cutoff_is_not_duplicated(self, _send_update, _log_event):
        """The stored copy of the programme across the one-day cutoff is kept, not doubled."""
        span_start = self.base_time - timedelta(days=1, minutes=30)
        span_end = span_start + timedelta(hours=2)
        self._stored('Across Cutoff', span_start, hours=2)
        self._stored('After Cutoff', span_end)
        self._configure_source_file(
            _programme_xml('mapped.channel', 'Across Cutoff', self._fmt(span_start), self._fmt(span_end))
            + _programme_xml(
                'mapped.channel', 'After Cutoff',
                self._fmt(span_end), self._fmt(span_end + timedelta(hours=1)),
            )
            + _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        self.assertTrue(parse_programs_for_source(self.source))

        rows = ProgramData.objects.filter(epg=self.mapped_epg)
        self.assertEqual(rows.filter(title='Across Cutoff').count(), 1)
        self.assertEqual(rows.filter(title='After Cutoff').count(), 1)
        self.assertEqual(rows.filter(title='New Show').count(), 1)

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_bad_early_timestamp_does_not_delete_retained_history(self, _send_update, _log_event):
        """A programme starting before the retention cutoff doesn't pull first_start back."""
        self._stored('Earlier Today', self.base_time - timedelta(hours=6))
        bogus_start = self.base_time - timedelta(days=10)
        self._configure_source_file(
            _programme_xml(
                'mapped.channel', 'Bogus Early',
                self._fmt(bogus_start), self._fmt(bogus_start + timedelta(hours=1)),
            )
            + _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        self.assertTrue(parse_programs_for_source(self.source))

        self.assertIn('Earlier Today', self._titles())
        self.assertIn('New Show', self._titles())
        # Expired rows in the pull are not inserted either.
        self.assertNotIn('Bogus Early', self._titles())

    @patch('apps.epg.tasks._epg_program_staging_supported', return_value=False)
    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_in_memory_fallback_applies_the_same_rules(self, _send_update, _log_event, _staging):
        span_start = self.base_time - timedelta(days=1, minutes=30)
        span_end = span_start + timedelta(hours=2)
        bogus_start = self.base_time - timedelta(days=10)
        self._stored('Earlier Today', self.base_time - timedelta(hours=6))
        self._stored('Across Cutoff', span_start, hours=2)
        self._stored('Stale Tail', self.base_time + timedelta(hours=5))
        self._configure_source_file(
            _programme_xml(
                'mapped.channel', 'Bogus Early',
                self._fmt(bogus_start), self._fmt(bogus_start + timedelta(hours=1)),
            )
            + _programme_xml('mapped.channel', 'Across Cutoff', self._fmt(span_start), self._fmt(span_end))
            + _programme_xml('mapped.channel', 'New Show', self.start, self.stop)
        )

        self.assertTrue(parse_programs_for_source(self.source))

        rows = ProgramData.objects.filter(epg=self.mapped_epg)
        self.assertEqual(rows.filter(title='Across Cutoff').count(), 1)
        self.assertEqual(
            self._titles(), {'Earlier Today', 'Across Cutoff', 'New Show'}
        )

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_empty_parse_does_not_wipe_existing_guide(self, _send_update, _log_event):
        """A mapped channel absent from this particular pull keeps its existing guide data."""
        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=self.base_time,
            end_time=self.base_time + timedelta(hours=1),
            title='Keep Me',
            tvg_id=self.mapped_epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('unmapped.channel', 'Unrelated', self.start, self.stop)
        )

        result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        self.assertEqual(
            ProgramData.objects.get(epg=self.mapped_epg).title, 'Keep Me'
        )

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

        ProgramData.objects.create(
            epg=self.mapped_epg,
            start_time=self.base_time,
            end_time=self.base_time + timedelta(hours=1),
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

    def test_orphan_cleanup_respects_channels_mapped_during_bulk_parse(self):
        late_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=self.unmapped_epg,
            start_time=late_start,
            end_time=late_start + timedelta(hours=1),
            title='Late Match Programme',
            tvg_id=self.unmapped_epg.tvg_id,
        )
        Channel.objects.create(
            channel_number=2,
            name='Late Mapped Channel',
            epg_data=self.unmapped_epg,
        )

        deleted = _delete_orphaned_epg_programs(self.source)

        self.assertEqual(deleted, 0)
        self.assertEqual(ProgramData.objects.filter(epg=self.unmapped_epg).count(), 1)

    @patch('apps.epg.tasks.dispatch_program_refresh_for_epg_ids', return_value=1)
    def test_late_mapped_dispatches_per_channel_parse(self, mock_dispatch):
        Channel.objects.create(
            channel_number=2,
            name='Late Mapped Channel',
            epg_data=self.unmapped_epg,
        )
        bulk_snapshot = {self.mapped_epg.id}

        dispatched = _dispatch_late_mapped_epg_parses(self.source, bulk_snapshot)

        self.assertEqual(dispatched, 1)
        mock_dispatch.assert_called_once_with({self.unmapped_epg.id})

    @patch('apps.epg.tasks.log_system_event')
    @patch('apps.epg.tasks.send_epg_update')
    def test_override_only_epg_is_treated_as_mapped(self, _send_update, _log_event):
        """Hand-assigned EPG on ChannelOverride must import ProgramData for XMLTV."""
        from apps.channels.models import ChannelOverride

        override_epg = EPGData.objects.create(
            epg_source=self.source,
            tvg_id='override.channel',
            name='Override Channel',
        )
        channel = Channel.objects.create(
            channel_number=9,
            name='Provider Name',
            epg_data=None,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel, epg_data=override_epg)

        programmes = (
            _programme_xml('mapped.channel', 'Mapped Show', self.start, self.stop)
            + _programme_xml('override.channel', 'Override Show', self.start, self.stop)
            + _programme_xml('unmapped.channel', 'Skipped Show', self.start, self.stop)
        )
        self._configure_source_file(programmes)

        result = parse_programs_for_source(self.source)

        self.assertTrue(result)
        self.assertEqual(ProgramData.objects.filter(epg=override_epg).count(), 1)
        self.assertEqual(
            ProgramData.objects.get(epg=override_epg).title,
            'Override Show',
        )
        self.assertFalse(ProgramData.objects.filter(epg=self.unmapped_epg).exists())

    def test_orphan_cleanup_keeps_override_mapped_programs(self):
        from apps.channels.models import ChannelOverride

        override_epg = EPGData.objects.create(
            epg_source=self.source,
            tvg_id='override.orphan',
            name='Override Orphan Check',
        )
        channel = Channel.objects.create(
            channel_number=9,
            name='Provider Name',
            epg_data=None,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel, epg_data=override_epg)
        late_start = self.base_time - timedelta(days=1)
        ProgramData.objects.create(
            epg=override_epg,
            start_time=late_start,
            end_time=late_start + timedelta(hours=1),
            title='Override Programme',
            tvg_id=override_epg.tvg_id,
        )

        deleted = _delete_orphaned_epg_programs(self.source)

        self.assertEqual(deleted, 0)
        self.assertEqual(ProgramData.objects.filter(epg=override_epg).count(), 1)
