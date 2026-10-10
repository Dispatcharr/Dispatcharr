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
        self._lock_patches = [
            patch('apps.epg.tasks.is_task_lock_held', return_value=False),
            patch('apps.epg.tasks.acquire_task_lock', return_value=True),
            patch('apps.epg.tasks.release_task_lock'),
        ]
        for p in self._lock_patches:
            p.start()

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
        for p in self._lock_patches:
            p.stop()
        if getattr(self, 'xml_path', None) and os.path.exists(self.xml_path):
            os.unlink(self.xml_path)

    def _configure_source_file(self, programmes):
        self.xml_path = _xmltv_file(programmes)
        self.source.file_path = self.xml_path
        self.source.save(update_fields=['file_path'])

    def test_replaces_programs_for_channel(self):
        """A stale row inside the freshly-parsed window is replaced, not kept alongside it."""
        ProgramData.objects.create(
            epg=self.epg,
            start_time=self.base_time,
            end_time=self.base_time + timedelta(hours=1),
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

    def test_replaces_a_stale_row_that_only_overlaps_the_feed_window(self):
        """A stale row need not be fully contained in the feed window to be superseded."""
        overlap_start = self.base_time - timedelta(minutes=30)
        ProgramData.objects.create(
            epg=self.epg,
            start_time=overlap_start,
            end_time=overlap_start + timedelta(hours=1),
            title='Overlapping Stale Programme',
            tvg_id=self.epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        titles = set(ProgramData.objects.filter(epg=self.epg).values_list('title', flat=True))
        self.assertEqual(titles, {'New Show'})

    def test_retains_history_outside_the_current_pull(self):
        """A recent programme absent from this pull survives, it's not just what the feed re-sent."""
        recent_start = self.base_time - timedelta(hours=6)
        ProgramData.objects.create(
            epg=self.epg,
            start_time=recent_start,
            end_time=recent_start + timedelta(hours=1),
            title='Earlier Today',
            tvg_id=self.epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        titles = set(ProgramData.objects.filter(epg=self.epg).values_list('title', flat=True))
        self.assertEqual(titles, {'Earlier Today', 'New Show'})

    def test_prunes_programs_past_the_retention_window(self):
        """A programme old enough that no catchup_days could reach it gets pruned regardless."""
        stale_start = self.base_time - timedelta(days=40)
        ProgramData.objects.create(
            epg=self.epg,
            start_time=stale_start,
            end_time=stale_start + timedelta(hours=1),
            title='Ancient Programme',
            tvg_id=self.epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        titles = set(ProgramData.objects.filter(epg=self.epg).values_list('title', flat=True))
        self.assertEqual(titles, {'New Show'})

    def test_retains_extra_history_for_catchup_enabled_channel(self):
        """A channel's own catchup_days extends the retention window past the one-day default."""
        self.channel.is_catchup = True
        self.channel.catchup_days = 7
        self.channel.save(update_fields=['is_catchup', 'catchup_days'])

        old_start = self.base_time - timedelta(days=5)
        ProgramData.objects.create(
            epg=self.epg,
            start_time=old_start,
            end_time=old_start + timedelta(hours=1),
            title='Five Days Ago',
            tvg_id=self.epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        titles = set(ProgramData.objects.filter(epg=self.epg).values_list('title', flat=True))
        self.assertEqual(titles, {'Five Days Ago', 'New Show'})

    def _fmt(self, when):
        return when.strftime('%Y%m%d%H%M%S +0000')

    def _stored(self, title, start, hours=1):
        ProgramData.objects.create(
            epg=self.epg,
            start_time=start,
            end_time=start + timedelta(hours=hours),
            title=title,
            tvg_id=self.epg.tvg_id,
        )

    def _titles(self):
        return set(ProgramData.objects.filter(epg=self.epg).values_list('title', flat=True))

    def test_keeps_a_row_that_ends_exactly_at_first_start(self):
        self._stored('Ends At First Start', self.base_time - timedelta(hours=1))
        self._configure_source_file(
            _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        self.assertEqual(self._titles(), {'Ends At First Start', 'New Show'})

    def test_replaces_rows_after_a_shorter_pull(self):
        """A stored row that sits after the new pull's last end is replaced too."""
        self._stored('Stale Tail', self.base_time + timedelta(hours=5))
        self._configure_source_file(
            _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        self.assertEqual(self._titles(), {'New Show'})

    def test_programme_spanning_the_cutoff_is_added_on_first_import(self):
        """Without a stored copy, the programme across the cutoff is still inserted."""
        span_start = self.base_time - timedelta(days=1, minutes=30)
        span_end = span_start + timedelta(hours=2)
        self._configure_source_file(
            _programme_xml('test.channel', 'Across Cutoff', self._fmt(span_start), self._fmt(span_end))
            + _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        rows = ProgramData.objects.filter(epg=self.epg)
        self.assertEqual(rows.filter(title='Across Cutoff').count(), 1)
        self.assertEqual(rows.filter(title='New Show').count(), 1)

    def test_programme_spanning_the_cutoff_is_not_duplicated(self):
        """The stored copy of the programme across the one-day cutoff is kept, not doubled."""
        span_start = self.base_time - timedelta(days=1, minutes=30)
        span_end = span_start + timedelta(hours=2)
        self._stored('Across Cutoff', span_start, hours=2)
        self._stored('After Cutoff', span_end)
        self._configure_source_file(
            _programme_xml('test.channel', 'Across Cutoff', self._fmt(span_start), self._fmt(span_end))
            + _programme_xml(
                'test.channel', 'After Cutoff',
                self._fmt(span_end), self._fmt(span_end + timedelta(hours=1)),
            )
            + _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        rows = ProgramData.objects.filter(epg=self.epg)
        self.assertEqual(rows.filter(title='Across Cutoff').count(), 1)
        self.assertEqual(rows.filter(title='After Cutoff').count(), 1)
        self.assertEqual(rows.filter(title='New Show').count(), 1)

    def test_bad_early_timestamp_does_not_delete_retained_history(self):
        """A programme starting before the retention cutoff doesn't pull first_start back."""
        self._stored('Earlier Today', self.base_time - timedelta(hours=6))
        bogus_start = self.base_time - timedelta(days=10)
        self._configure_source_file(
            _programme_xml(
                'test.channel', 'Bogus Early',
                self._fmt(bogus_start), self._fmt(bogus_start + timedelta(hours=1)),
            )
            + _programme_xml('test.channel', 'New Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        self.assertIn('Earlier Today', self._titles())
        self.assertIn('New Show', self._titles())
        # Expired rows in the pull are not inserted either.
        self.assertNotIn('Bogus Early', self._titles())

    def test_pull_entirely_before_cutoff_only_prunes_by_cutoff(self):
        """With no programme inside the retention window, only the cutoff applies."""
        self._stored('Earlier Today', self.base_time - timedelta(hours=6))
        old_start = self.base_time - timedelta(days=10)
        self._configure_source_file(
            _programme_xml(
                'test.channel', 'Only Old',
                self._fmt(old_start), self._fmt(old_start + timedelta(hours=1)),
            )
        )

        parse_programs_for_tvg_id(self.epg.id)

        self.assertEqual(self._titles(), {'Earlier Today'})

    def test_inverted_programme_does_not_wipe_guide(self):
        """A malformed row that is filtered out must not move first_start."""
        self._stored('Keep Me', self.base_time + timedelta(hours=2))
        self._configure_source_file(
            _programme_xml(
                'test.channel', 'Inverted',
                self._fmt(self.base_time + timedelta(hours=1)),
                self._fmt(self.base_time - timedelta(days=10)),
            )
        )

        parse_programs_for_tvg_id(self.epg.id)

        self.assertEqual(self._titles(), {'Keep Me'})

    def test_empty_parse_does_not_wipe_existing_guide(self):
        """A parse that matches nothing (e.g. a transient upstream hiccup) must not clear the guide."""
        ProgramData.objects.create(
            epg=self.epg,
            start_time=self.base_time,
            end_time=self.base_time + timedelta(hours=1),
            title='Keep Me',
            tvg_id=self.epg.tvg_id,
        )
        self._configure_source_file(
            _programme_xml('some.other.channel', 'Unrelated', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        self.assertEqual(
            ProgramData.objects.filter(epg=self.epg).get().title, 'Keep Me'
        )

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

    def test_parses_when_epg_only_on_channel_override(self):
        """Override-only EPG must not early-exit as unmapped."""
        from apps.channels.models import ChannelOverride

        self.channel.epg_data = None
        self.channel.auto_created = True
        self.channel.save(update_fields=['epg_data', 'auto_created'])
        ChannelOverride.objects.create(channel=self.channel, epg_data=self.epg)

        self._configure_source_file(
            _programme_xml('test.channel', 'Override Show', self.start, self.stop)
        )

        parse_programs_for_tvg_id(self.epg.id)

        self.assertEqual(
            ProgramData.objects.filter(epg=self.epg).get().title,
            'Override Show',
        )

    def test_skips_when_epg_not_mapped_on_channel_or_override(self):
        self.channel.epg_data = None
        self.channel.save(update_fields=['epg_data'])
        self._configure_source_file(
            _programme_xml('test.channel', 'Should Skip', self.start, self.stop)
        )

        result = parse_programs_for_tvg_id(self.epg.id)

        self.assertIsNone(result)
        self.assertFalse(ProgramData.objects.filter(epg=self.epg).exists())
