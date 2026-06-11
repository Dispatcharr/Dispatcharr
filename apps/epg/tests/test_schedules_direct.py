"""
Tests for the Schedules Direct EPG integration.

Covers:
- EPGSource model: username field presence and help text
- EPGSource serializer: username field included in output
- fetch_schedules_direct: credential validation
- fetch_schedules_direct: SHA1 password hashing and token exchange
- fetch_schedules_direct: graceful error handling on auth failure
- fetch_schedules_direct: schedule MD5 delta, backfill, and cache invalidation
- parse_schedules_direct_time: correct UTC parsing
- fetch_sd_guide_for_epg: per-channel guide fetch on map
- EPG signals: SD sources queue guide fetch when a channel is mapped
"""

import hashlib
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel
from apps.epg.models import EPGSource, EPGData, ProgramData, SDScheduleMD5
from apps.epg.serializers import EPGSourceSerializer
from apps.epg.tasks import (
    _sd_backfill_schedule_dates_without_data,
    _sd_compute_schedule_changes_from_md5,
    _sd_programs_needing_metadata,
)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class EPGSourceUsernameFieldTests(TestCase):
    """EPGSource.username must exist, be nullable, and carry help text."""

    def test_username_field_exists(self):
        source = EPGSource.objects.create(
            name='SD Test',
            source_type='schedules_direct',
            username='testuser',
            password='testpass',
        )
        source.refresh_from_db()
        self.assertEqual(source.username, 'testuser')

    def test_username_nullable(self):
        source = EPGSource.objects.create(
            name='SD Nullable',
            source_type='schedules_direct',
        )
        source.refresh_from_db()
        self.assertIsNone(source.username)

    def test_username_help_text(self):
        field = EPGSource._meta.get_field('username')
        self.assertIn('Schedules Direct', field.help_text)


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------

class EPGSourceSerializerSDTests(TestCase):
    """EPGSourceSerializer must include the username field."""

    def test_username_in_serializer_fields(self):
        source = EPGSource.objects.create(
            name='SD Serializer Test',
            source_type='schedules_direct',
            username='sduser',
            password='sdpass',
        )
        data = EPGSourceSerializer(source).data
        self.assertIn('username', data)
        self.assertEqual(data['username'], 'sduser')

    def test_password_not_in_serializer_output(self):
        source = EPGSource.objects.create(
            name='SD API Key Test',
            source_type='schedules_direct',
            password='secret',
        )
        data = EPGSourceSerializer(source).data
        self.assertNotIn('password', data)


# ---------------------------------------------------------------------------
# fetch_schedules_direct tests
# ---------------------------------------------------------------------------

class FetchSchedulesDirectCredentialTests(TestCase):
    """fetch_schedules_direct must reject sources missing credentials."""

    def _make_source(self, username=None, password=None):
        return EPGSource.objects.create(
            name='SD Cred Test',
            source_type='schedules_direct',
            username=username,
            password=password,
        )

    def test_missing_username_sets_error_status(self):
        from apps.epg.tasks import fetch_schedules_direct
        source = self._make_source(username=None, password='pass')
        fetch_schedules_direct(source)
        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_ERROR)

    def test_missing_password_sets_error_status(self):
        from apps.epg.tasks import fetch_schedules_direct
        source = self._make_source(username='user', password=None)
        fetch_schedules_direct(source)
        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_ERROR)

    def test_empty_username_sets_error_status(self):
        from apps.epg.tasks import fetch_schedules_direct
        source = self._make_source(username='   ', password='pass')
        fetch_schedules_direct(source)
        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_ERROR)


class FetchSchedulesDirectAuthTests(TestCase):
    """fetch_schedules_direct must SHA1-hash the password before sending."""

    @patch('apps.epg.tasks.requests.post')
    @patch('apps.epg.tasks.requests.get')
    def test_password_sha1_hashed_in_token_request(self, mock_get, mock_post):
        """The token POST body must contain the SHA1 hash of the plaintext password."""
        plaintext = 'mysecretpassword'
        expected_hash = hashlib.sha1(plaintext.encode('utf-8')).hexdigest()

        # Auth succeeds, status check returns empty data, lineups returns empty
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={'code': 0, 'token': 'tok123'}),
        )
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={}),
        )

        from apps.epg.tasks import fetch_schedules_direct
        source = EPGSource.objects.create(
            name='SD Hash Test',
            source_type='schedules_direct',
            username='sduser',
            password=plaintext,
        )

        with patch('apps.epg.tasks.send_epg_update'):
            fetch_schedules_direct(source)

        # Verify the POST was called and the body contained the hash
        self.assertTrue(mock_post.called)
        call_kwargs = mock_post.call_args
        posted_json = call_kwargs[1].get('json') or call_kwargs[0][1]
        self.assertEqual(posted_json.get('password'), expected_hash)
        self.assertEqual(posted_json.get('username'), 'sduser')

    @patch('apps.epg.tasks.requests.post')
    def test_auth_failure_sets_error_status(self, mock_post):
        """A non-zero SD response code must set STATUS_ERROR on the source."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                'code': 3000,
                'message': 'Invalid credentials',
            }),
        )

        from apps.epg.tasks import fetch_schedules_direct
        source = EPGSource.objects.create(
            name='SD Auth Fail',
            source_type='schedules_direct',
            username='baduser',
            password='badpass',
        )

        with patch('apps.epg.tasks.send_epg_update'):
            fetch_schedules_direct(source)

        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_ERROR)

    @patch('apps.epg.tasks.requests.post')
    def test_network_error_sets_error_status(self, mock_post):
        """A network-level exception must set STATUS_ERROR and not crash."""
        import requests as req_lib
        mock_post.side_effect = req_lib.exceptions.ConnectionError('timeout')

        from apps.epg.tasks import fetch_schedules_direct
        source = EPGSource.objects.create(
            name='SD Network Error',
            source_type='schedules_direct',
            username='user',
            password='pass',
        )

        with patch('apps.epg.tasks.send_epg_update'):
            fetch_schedules_direct(source)  # Must not raise

        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_ERROR)


class FetchSchedulesDirectStationsOnlyTests(TestCase):
    """stations_only fetch must signal channel parsing completion to the frontend."""

    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    @patch('apps.epg.tasks.requests.post')
    def test_stations_only_sends_parsing_channels_complete(
        self, mock_post, mock_get, mock_send_epg_update
    ):
        from apps.epg.tasks import fetch_schedules_direct

        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={'code': 0, 'token': 'tok123'}),
        )

        def get_side_effect(url, **kwargs):
            if url.endswith('/status'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={'systemStatus': [{'status': 'Online'}]}),
                )
            if url.endswith('/lineups'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={
                        'lineups': [{'lineupID': 'USA-TEST-X'}],
                    }),
                )
            if '/lineups/USA-TEST-X' in url:
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={
                        'stations': [{
                            'stationID': '10001',
                            'name': 'Test Station',
                            'callsign': 'TEST',
                        }],
                    }),
                )
            raise AssertionError(f'Unexpected GET URL: {url}')

        mock_get.side_effect = get_side_effect

        source = EPGSource.objects.create(
            name='SD Stations Only',
            source_type='schedules_direct',
            username='sduser',
            password='sdpass',
        )

        fetch_schedules_direct(source, stations_only=True)

        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_SUCCESS)
        self.assertEqual(EPGData.objects.filter(epg_source=source).count(), 1)

        parsing_channel_complete = [
            c
            for c in mock_send_epg_update.call_args_list
            if c[0][1] == 'parsing_channels' and c[0][2] == 100
        ]
        self.assertEqual(len(parsing_channel_complete), 1)
        complete_call = parsing_channel_complete[0]
        self.assertEqual(complete_call[0][0], source.id)
        self.assertEqual(complete_call[1]['status'], 'success')
        self.assertEqual(complete_call[1]['channels_count'], 1)


# ---------------------------------------------------------------------------
# Schedule MD5 delta, backfill, and cache tests
# ---------------------------------------------------------------------------

class SDScheduleMd5DeltaTests(TestCase):
    """Pure-function tests for schedule MD5 comparison."""

    DATE_LIST = ['2026-06-11', '2026-06-12', '2026-06-13']

    def test_detects_changed_md5(self):
        server_md5s = {
            ('10001', '2026-06-11'): {'md5': 'abc', 'last_modified': ''},
            ('10001', '2026-06-12'): {'md5': 'def', 'last_modified': ''},
        }
        cached_md5s = {
            ('10001', '2026-06-11'): 'abc',
            ('10001', '2026-06-12'): 'old',
        }
        changed = _sd_compute_schedule_changes_from_md5(
            server_md5s, cached_md5s, self.DATE_LIST,
        )
        self.assertEqual(changed['10001'], ['2026-06-12'])

    def test_missing_cache_treated_as_changed(self):
        server_md5s = {
            ('10001', '2026-06-11'): {'md5': 'abc', 'last_modified': ''},
        }
        changed = _sd_compute_schedule_changes_from_md5(server_md5s, {}, self.DATE_LIST)
        self.assertEqual(changed['10001'], ['2026-06-11'])

    def test_ignores_dates_outside_fetch_window(self):
        server_md5s = {
            ('10001', '2026-06-01'): {'md5': 'abc', 'last_modified': ''},
        }
        changed = _sd_compute_schedule_changes_from_md5(server_md5s, {}, self.DATE_LIST)
        self.assertEqual(changed, {})


class SDScheduleBackfillTests(TestCase):
    """Backfill must fix stale-cache gaps without re-fetching empty cached days."""

    DATE_LIST = ['2026-06-11', '2026-06-12', '2026-06-13']
    EPG_ID = 42
    EPG_ID_MAP = {'10001': 42}

    def _server_md5s(self):
        return {
            (sid, ds): {'md5': 'hash', 'last_modified': ''}
            for sid in ('10001', '10002')
            for ds in self.DATE_LIST
        }

    def test_backfills_when_no_cache_and_no_program_data(self):
        changed = {}
        count = _sd_backfill_schedule_dates_without_data(
            changed,
            self._server_md5s(),
            self.DATE_LIST,
            ['10001'],
            self.EPG_ID_MAP,
            set(),
            {},
            {'10001'},
        )
        self.assertEqual(count, 3)
        self.assertEqual(len(changed['10001']), 3)

    def test_stale_cache_ignored_when_station_has_zero_program_data(self):
        """Newly mapped channel: stale MD5 cache must not block backfill."""
        changed = {}
        cached_md5s = {
            (sid, ds): 'hash'
            for sid in ('10001',)
            for ds in self.DATE_LIST
        }
        count = _sd_backfill_schedule_dates_without_data(
            changed,
            self._server_md5s(),
            self.DATE_LIST,
            ['10001'],
            self.EPG_ID_MAP,
            set(),
            cached_md5s,
            {'10001'},
        )
        self.assertEqual(count, 3)
        self.assertEqual(len(changed['10001']), 3)

    def test_skips_cached_empty_day_when_station_has_other_program_data(self):
        """Legitimately empty schedule day must not be re-fetched every refresh."""
        changed = {}
        cached_md5s = {('10001', '2026-06-12'): 'hash'}
        dates_with_data = {(self.EPG_ID, date(2026, 6, 11))}
        count = _sd_backfill_schedule_dates_without_data(
            changed,
            self._server_md5s(),
            self.DATE_LIST,
            ['10001'],
            self.EPG_ID_MAP,
            dates_with_data,
            cached_md5s,
            set(),
        )
        self.assertEqual(count, 1)
        self.assertEqual(changed['10001'], ['2026-06-13'])

    def test_does_not_duplicate_dates_already_marked_changed(self):
        changed = {'10001': ['2026-06-11']}
        count = _sd_backfill_schedule_dates_without_data(
            changed,
            self._server_md5s(),
            self.DATE_LIST,
            ['10001'],
            self.EPG_ID_MAP,
            set(),
            {},
            {'10001'},
        )
        self.assertEqual(count, 2)
        self.assertEqual(sorted(changed['10001']), self.DATE_LIST)


class SDProgramMetadataDeltaTests(TestCase):
    def test_fetches_when_md5_changed(self):
        needed = _sd_programs_needing_metadata(
            {'EP0001'},
            {'EP0001': 'new'},
            {'EP0001': 'old'},
            {'EP0001'},
        )
        self.assertEqual(needed, {'EP0001'})

    def test_fetches_when_no_local_program_data(self):
        needed = _sd_programs_needing_metadata(
            {'EP0001', 'EP0002'},
            {'EP0001': 'same', 'EP0002': 'same'},
            {'EP0001': 'same', 'EP0002': 'same'},
            {'EP0001'},
        )
        self.assertEqual(needed, {'EP0002'})

    def test_skips_when_md5_matches_and_program_data_exists(self):
        needed = _sd_programs_needing_metadata(
            {'EP0001'},
            {'EP0001': 'same'},
            {'EP0001': 'same'},
            {'EP0001'},
        )
        self.assertEqual(needed, set())


class SDScheduleDeltaIntegrationTests(TestCase):
    """DB-backed tests for cache pruning and mapped-only MD5 API calls."""

    MAPPED_STATION = '10001'
    UNMAPPED_STATION = '10002'

    def _make_sd_source(self):
        return EPGSource.objects.create(
            name='SD Integration',
            source_type='schedules_direct',
            username='sduser',
            password='sdpass',
        )

    def _lineup_get_side_effect(self, url, **kwargs):
        if url.endswith('/status'):
            return MagicMock(
                status_code=200,
                json=MagicMock(return_value={'systemStatus': [{'status': 'Online'}]}),
            )
        if url.endswith('/lineups'):
            return MagicMock(
                status_code=200,
                json=MagicMock(return_value={'lineups': [{'lineupID': 'USA-TEST-X'}]}),
            )
        if '/lineups/USA-TEST-X' in url:
            return MagicMock(
                status_code=200,
                json=MagicMock(return_value={
                    'stations': [
                        {
                            'stationID': self.MAPPED_STATION,
                            'name': 'Mapped Station',
                            'callsign': 'MAP',
                        },
                        {
                            'stationID': self.UNMAPPED_STATION,
                            'name': 'Unmapped Station',
                            'callsign': 'UNM',
                        },
                    ],
                }),
            )
        raise AssertionError(f'Unexpected GET URL: {url}')

    def _build_date_list(self, days=3):
        today = date.today()
        return [(today + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)]

    def _seed_full_window_program_data(self, epg, days=3):
        today = date.today()
        for i in range(days):
            day = today + timedelta(days=i)
            start = datetime(day.year, day.month, day.day, 12, 0, tzinfo=dt_timezone.utc)
            ProgramData.objects.create(
                epg=epg,
                start_time=start,
                end_time=start + timedelta(hours=1),
                title='Show',
                tvg_id=epg.tvg_id,
            )

    @patch('apps.epg.tasks.SD_DAYS_TO_FETCH', 3)
    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    @patch('apps.epg.tasks.requests.post')
    def test_md5_api_only_requests_mapped_stations(
        self, mock_post, mock_get, mock_send_epg_update,
    ):
        from apps.epg.tasks import fetch_schedules_direct

        source = self._make_sd_source()
        mapped_epg = EPGData.objects.create(
            tvg_id=self.MAPPED_STATION,
            name='Mapped',
            epg_source=source,
        )
        Channel.objects.create(name='Mapped Ch', epg_data=mapped_epg)

        date_list = self._build_date_list(3)
        self._seed_full_window_program_data(mapped_epg, days=3)

        today = date.today()
        for i, ds in enumerate(date_list):
            SDScheduleMD5.objects.create(
                epg_source=source,
                station_id=self.MAPPED_STATION,
                date=today + timedelta(days=i),
                md5=f'md5-{ds}',
                last_modified=timezone.now(),
            )
        SDScheduleMD5.objects.create(
            epg_source=source,
            station_id=self.UNMAPPED_STATION,
            date=today,
            md5='unmapped-stale',
            last_modified=timezone.now(),
        )

        mock_get.side_effect = self._lineup_get_side_effect

        md5_response_payload = {
            self.MAPPED_STATION: {
                ds: {'code': 0, 'md5': f'md5-{ds}', 'lastModified': '2026-06-11T00:00:00Z'}
                for ds in date_list
            },
        }

        def post_side_effect(url, **kwargs):
            if url.endswith('/token'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={'code': 0, 'token': 'tok'}),
                )
            if url.endswith('/schedules/md5'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value=md5_response_payload),
                )
            raise AssertionError(f'Unexpected POST URL: {url}')

        mock_post.side_effect = post_side_effect

        fetch_schedules_direct(source, force=True)

        md5_calls = [c for c in mock_post.call_args_list if c[0][0].endswith('/schedules/md5')]
        self.assertEqual(len(md5_calls), 1)
        request_body = md5_calls[0][1]['json']
        station_ids_in_request = {entry['stationID'] for entry in request_body}
        self.assertEqual(station_ids_in_request, {self.MAPPED_STATION})

        self.assertFalse(
            SDScheduleMD5.objects.filter(
                epg_source=source,
                station_id=self.UNMAPPED_STATION,
            ).exists()
        )

        schedule_calls = [c for c in mock_post.call_args_list if c[0][0].endswith('/schedules')]
        self.assertEqual(len(schedule_calls), 0)

        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_SUCCESS)

    @patch('apps.epg.tasks.SD_DAYS_TO_FETCH', 3)
    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    @patch('apps.epg.tasks.requests.post')
    def test_newly_mapped_station_fetches_despite_stale_cache(
        self, mock_post, mock_get, mock_send_epg_update,
    ):
        from apps.epg.tasks import fetch_schedules_direct

        source = self._make_sd_source()
        mapped_epg = EPGData.objects.create(
            tvg_id=self.MAPPED_STATION,
            name='Mapped',
            epg_source=source,
        )
        Channel.objects.create(name='Mapped Ch', epg_data=mapped_epg)

        date_list = self._build_date_list(3)
        today = date.today()
        for i, ds in enumerate(date_list):
            SDScheduleMD5.objects.create(
                epg_source=source,
                station_id=self.MAPPED_STATION,
                date=today + timedelta(days=i),
                md5=f'md5-{ds}',
                last_modified=timezone.now(),
            )

        mock_get.side_effect = self._lineup_get_side_effect

        schedule_payload = [{
            'stationID': self.MAPPED_STATION,
            'metadata': {'startDate': date_list[0], 'md5': 'md5-' + date_list[0], 'modified': '2026-06-11T00:00:00Z'},
            'programs': [{
                'programID': 'EP000000000001',
                'airDateTime': f'{date_list[0]}T12:00:00Z',
                'duration': 3600,
                'md5': 'prog-md5-1',
            }],
        }]
        program_payload = [{
            'programID': 'EP000000000001',
            'titles': [{'title120': 'Test Show'}],
        }]

        def post_side_effect(url, **kwargs):
            if url.endswith('/token'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={'code': 0, 'token': 'tok'}),
                )
            if url.endswith('/schedules/md5'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={
                        self.MAPPED_STATION: {
                            ds: {'code': 0, 'md5': f'md5-{ds}', 'lastModified': '2026-06-11T00:00:00Z'}
                            for ds in date_list
                        },
                    }),
                )
            if url.endswith('/schedules'):
                return MagicMock(status_code=200, json=MagicMock(return_value=schedule_payload))
            if url.endswith('/programs'):
                return MagicMock(status_code=200, json=MagicMock(return_value=program_payload))
            raise AssertionError(f'Unexpected POST URL: {url}')

        mock_post.side_effect = post_side_effect

        fetch_schedules_direct(source, force=True)

        schedule_calls = [c for c in mock_post.call_args_list if c[0][0].endswith('/schedules')]
        self.assertGreaterEqual(len(schedule_calls), 1)
        self.assertEqual(
            ProgramData.objects.filter(epg=mapped_epg).count(),
            1,
        )

    @patch('apps.epg.tasks.SD_DAYS_TO_FETCH', 3)
    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    @patch('apps.epg.tasks.requests.post')
    def test_orphan_program_data_removed_on_post_refresh(
        self, mock_post, mock_get, mock_send_epg_update,
    ):
        from apps.epg.tasks import fetch_schedules_direct

        source = self._make_sd_source()
        mapped_epg = EPGData.objects.create(
            tvg_id=self.MAPPED_STATION,
            name='Mapped',
            epg_source=source,
        )
        orphan_epg = EPGData.objects.create(
            tvg_id=self.UNMAPPED_STATION,
            name='Orphan',
            epg_source=source,
        )
        Channel.objects.create(name='Mapped Ch', epg_data=mapped_epg)

        date_list = self._build_date_list(3)
        self._seed_full_window_program_data(mapped_epg, days=3)

        start = timezone.now()
        ProgramData.objects.create(
            epg=orphan_epg,
            start_time=start,
            end_time=start + timedelta(hours=1),
            title='Orphan Show',
            tvg_id=orphan_epg.tvg_id,
        )

        today = date.today()
        for i, ds in enumerate(date_list):
            SDScheduleMD5.objects.create(
                epg_source=source,
                station_id=self.MAPPED_STATION,
                date=today + timedelta(days=i),
                md5=f'md5-{ds}',
                last_modified=timezone.now(),
            )

        mock_get.side_effect = self._lineup_get_side_effect

        def post_side_effect(url, **kwargs):
            if url.endswith('/token'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={'code': 0, 'token': 'tok'}),
                )
            if url.endswith('/schedules/md5'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={
                        self.MAPPED_STATION: {
                            ds: {'code': 0, 'md5': f'md5-{ds}', 'lastModified': '2026-06-11T00:00:00Z'}
                            for ds in date_list
                        },
                    }),
                )
            raise AssertionError(f'Unexpected POST URL: {url}')

        mock_post.side_effect = post_side_effect

        fetch_schedules_direct(source, force=True)

        self.assertFalse(ProgramData.objects.filter(epg=orphan_epg).exists())

    def test_stale_program_md5_fetched_when_no_program_data(self):
        programs_with_data = set()
        needed = _sd_programs_needing_metadata(
            {'EP0001'},
            {'EP0001': 'cached-md5'},
            {'EP0001': 'cached-md5'},
            programs_with_data,
        )
        self.assertEqual(needed, {'EP0001'})

    def test_shared_program_skips_metadata_when_cached(self):
        needed = _sd_programs_needing_metadata(
            {'EP0001'},
            {'EP0001': 'cached-md5'},
            {'EP0001': 'cached-md5'},
            {'EP0001'},
        )
        self.assertEqual(needed, set())


# ---------------------------------------------------------------------------
# parse_schedules_direct_time tests
# ---------------------------------------------------------------------------

class ParseSchedulesDirectTimeTests(TestCase):
    """parse_schedules_direct_time must parse SD ISO timestamps to UTC-aware datetimes."""

    def test_parses_valid_timestamp(self):
        from apps.epg.tasks import parse_schedules_direct_time
        result = parse_schedules_direct_time('2026-05-16T20:00:00Z')
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 5)
        self.assertEqual(result.day, 16)
        self.assertEqual(result.hour, 20)
        self.assertIsNotNone(result.tzinfo)

    def test_result_is_utc_aware(self):
        from apps.epg.tasks import parse_schedules_direct_time
        result = parse_schedules_direct_time('2026-01-01T00:00:00Z')
        # Should be timezone-aware
        self.assertIsNotNone(result.tzinfo)

    def test_raises_on_invalid_format(self):
        from apps.epg.tasks import parse_schedules_direct_time
        with self.assertRaises(Exception):
            parse_schedules_direct_time('not-a-timestamp')


# ---------------------------------------------------------------------------
# Signal tests
# ---------------------------------------------------------------------------

class SDSingleEpgFetchTests(TestCase):
    """Per-channel SD guide fetch on map (epg_id_only path)."""

    MAPPED_STATION = '10001'

    def _make_sd_source(self, updated_at=None):
        source = EPGSource.objects.create(
            name='SD Single EPG',
            source_type='schedules_direct',
            username='sduser',
            password='sdpass',
        )
        if updated_at is not None:
            EPGSource.objects.filter(id=source.id).update(updated_at=updated_at)
            source.refresh_from_db()
        return source

    def _lineup_get_side_effect(self, url, **kwargs):
        if url.endswith('/status'):
            return MagicMock(
                status_code=200,
                json=MagicMock(return_value={'systemStatus': [{'status': 'Online'}]}),
            )
        if url.endswith('/lineups'):
            return MagicMock(
                status_code=200,
                json=MagicMock(return_value={'lineups': [{'lineupID': 'USA-TEST-X'}]}),
            )
        raise AssertionError(f'Unexpected GET URL: {url}')

    @patch('apps.epg.tasks.acquire_task_lock', return_value=True)
    @patch('apps.epg.tasks.release_task_lock')
    @patch('apps.epg.tasks.TaskLockRenewer')
    def test_fetch_sd_guide_skips_when_program_data_exists(
        self, mock_renewer, mock_release, mock_acquire,
    ):
        from apps.epg.tasks import fetch_sd_guide_for_epg

        source = self._make_sd_source()
        epg = EPGData.objects.create(
            tvg_id=self.MAPPED_STATION,
            name='Mapped',
            epg_source=source,
        )
        start = timezone.now()
        ProgramData.objects.create(
            epg=epg,
            start_time=start,
            end_time=start + timedelta(hours=1),
            title='Existing',
            tvg_id=epg.tvg_id,
        )

        with patch('apps.epg.tasks.fetch_schedules_direct') as mock_fetch:
            result = fetch_sd_guide_for_epg(epg.id)

        self.assertEqual(result, 'Guide data already present')
        mock_fetch.assert_not_called()

    @patch('apps.epg.tasks.acquire_task_lock', return_value=True)
    @patch('apps.epg.tasks.release_task_lock')
    @patch('apps.epg.tasks.TaskLockRenewer')
    def test_parse_programs_for_tvg_id_delegates_to_sd_fetch(
        self, mock_renewer, mock_release, mock_acquire,
    ):
        from apps.epg.tasks import parse_programs_for_tvg_id

        source = self._make_sd_source()
        epg = EPGData.objects.create(
            tvg_id=self.MAPPED_STATION,
            name='Mapped',
            epg_source=source,
        )

        with patch('apps.epg.tasks.fetch_sd_guide_for_epg', return_value='SD guide fetch complete') as mock_sd:
            result = parse_programs_for_tvg_id(epg.id)

        mock_sd.assert_called_once_with(epg.id, force=False)
        self.assertEqual(result, 'SD guide fetch complete')

    @patch('apps.epg.tasks.SD_DAYS_TO_FETCH', 3)
    @patch('apps.epg.tasks.send_epg_update')
    @patch('apps.epg.tasks.requests.get')
    @patch('apps.epg.tasks.requests.post')
    def test_single_epg_fetch_skips_lineup_sync_and_updated_at(
        self, mock_post, mock_get, mock_send_epg_update,
    ):
        from apps.epg.tasks import fetch_schedules_direct

        prior_updated = timezone.now() - timedelta(hours=1)
        source = self._make_sd_source(updated_at=prior_updated)
        epg = EPGData.objects.create(
            tvg_id=self.MAPPED_STATION,
            name='Mapped',
            epg_source=source,
        )
        Channel.objects.create(name='Mapped Ch', epg_data=epg)

        date_list = [
            (date.today() + timedelta(days=i)).strftime('%Y-%m-%d')
            for i in range(3)
        ]
        mock_get.side_effect = self._lineup_get_side_effect

        schedule_payload = [{
            'stationID': self.MAPPED_STATION,
            'metadata': {'startDate': date_list[0], 'md5': 'md5-new', 'modified': '2026-06-11T00:00:00Z'},
            'programs': [{
                'programID': 'EP000000000001',
                'airDateTime': f'{date_list[0]}T12:00:00Z',
                'duration': 3600,
                'md5': 'prog-md5-1',
            }],
        }]
        program_payload = [{
            'programID': 'EP000000000001',
            'titles': [{'title120': 'Test Show'}],
        }]

        def post_side_effect(url, **kwargs):
            if url.endswith('/token'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={'code': 0, 'token': 'tok'}),
                )
            if url.endswith('/schedules/md5'):
                return MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={
                        self.MAPPED_STATION: {
                            ds: {'code': 0, 'md5': f'md5-{ds}', 'lastModified': '2026-06-11T00:00:00Z'}
                            for ds in date_list
                        },
                    }),
                )
            if url.endswith('/schedules'):
                return MagicMock(status_code=200, json=MagicMock(return_value=schedule_payload))
            if url.endswith('/programs'):
                return MagicMock(status_code=200, json=MagicMock(return_value=program_payload))
            raise AssertionError(f'Unexpected POST URL: {url}')

        mock_post.side_effect = post_side_effect

        fetch_schedules_direct(source, epg_id_only=epg.id)

        lineup_detail_calls = [
            c for c in mock_get.call_args_list
            if '/lineups/' in c[0][0] and not c[0][0].endswith('/lineups')
        ]
        self.assertEqual(lineup_detail_calls, [])

        source.refresh_from_db()
        self.assertEqual(source.updated_at, prior_updated)
        self.assertEqual(ProgramData.objects.filter(epg=epg).count(), 1)


class SDSourceSignalTests(TestCase):
    """SD EPG sources queue per-EPG guide fetch when a channel is mapped."""

    @patch('apps.channels.signals.parse_programs_for_tvg_id')
    def test_sd_source_queues_guide_fetch_on_channel_create(self, mock_parse):
        from apps.epg.models import EPGData
        from apps.channels.models import Channel

        sd_source = EPGSource.objects.create(
            name='SD Signal Test',
            source_type='schedules_direct',
            username='u',
            password='p',
        )
        epg_data = EPGData.objects.create(
            tvg_id='sd-test-station',
            name='SD Test Station',
            epg_source=sd_source,
        )

        Channel.objects.create(
            name='SD Channel',
            epg_data=epg_data,
        )

        mock_parse.delay.assert_called_once_with(epg_data.id)


# ---------------------------------------------------------------------------
# Poster selection tests
# ---------------------------------------------------------------------------

class SDPosterSelectionTests(TestCase):
    """_sd_pick_poster_url must honour style preference with sensible fallbacks."""

    def _images(self):
        return [
            {
                'uri': 'assets/iconic_portrait.jpg',
                'width': '960',
                'aspect': '2x3',
                'category': 'Iconic',
            },
            {
                'uri': 'assets/banner_portrait.jpg',
                'width': '360',
                'aspect': '2x3',
                'category': 'Banner-L1',
            },
            {
                'uri': 'assets/iconic_landscape.jpg',
                'width': '1920',
                'aspect': '16x9',
                'category': 'Iconic',
            },
            {
                'uri': 'assets/banner_landscape.jpg',
                'width': '1280',
                'aspect': '16x9',
                'category': 'Banner-L1',
            },
        ]

    def test_portrait_iconic_prefers_iconic_over_banner(self):
        from apps.epg.tasks import _sd_pick_poster_url

        self.assertEqual(
            _sd_pick_poster_url(self._images(), 'portrait_iconic'),
            'assets/iconic_portrait.jpg',
        )

    def test_portrait_banner_prefers_banner(self):
        from apps.epg.tasks import _sd_pick_poster_url

        self.assertEqual(
            _sd_pick_poster_url(self._images(), 'portrait_banner'),
            'assets/banner_portrait.jpg',
        )

    def test_landscape_iconic_prefers_landscape_iconic(self):
        from apps.epg.tasks import _sd_pick_poster_url

        self.assertEqual(
            _sd_pick_poster_url(self._images(), 'landscape_iconic'),
            'assets/iconic_landscape.jpg',
        )

    def test_landscape_falls_back_to_portrait_when_unavailable(self):
        from apps.epg.tasks import _sd_pick_poster_url

        images = [img for img in self._images() if img['aspect'] in ('2x3', '3x4')]
        self.assertEqual(
            _sd_pick_poster_url(images, 'landscape_iconic'),
            'assets/iconic_portrait.jpg',
        )

    def test_unknown_style_defaults_to_sd_recommended(self):
        from apps.epg.tasks import _sd_pick_poster_url

        self.assertEqual(
            _sd_pick_poster_url(self._images(), 'not_a_real_style'),
            'assets/iconic_portrait.jpg',
        )

    def test_prefers_primary_when_category_and_aspect_match(self):
        from apps.epg.tasks import _sd_pick_poster_url

        images = [
            {
                'uri': 'assets/banner_small.jpg',
                'width': '120',
                'aspect': '2x3',
                'category': 'Banner-L1',
            },
            {
                'uri': 'assets/banner_primary.jpg',
                'width': '360',
                'aspect': '2x3',
                'category': 'Banner-L1',
                'primary': 'true',
            },
        ]
        self.assertEqual(
            _sd_pick_poster_url(images, 'portrait_banner'),
            'assets/banner_primary.jpg',
        )

    def test_sd_recommended_uses_primary_poster_category(self):
        from apps.epg.tasks import _sd_pick_poster_url

        images = [
            {
                'uri': 'assets/cast_primary.jpg',
                'width': '500',
                'aspect': '3x4',
                'category': 'Cast in Character',
                'primary': 'true',
            },
            {
                'uri': 'assets/iconic_primary.jpg',
                'width': '300',
                'aspect': '16x9',
                'category': 'Iconic',
                'primary': 'true',
            },
        ]
        self.assertEqual(
            _sd_pick_poster_url(images, 'sd_recommended'),
            'assets/iconic_primary.jpg',
        )

    def test_sd_recommended_falls_back_to_portrait_iconic(self):
        from apps.epg.tasks import _sd_pick_poster_url

        self.assertEqual(
            _sd_pick_poster_url(self._images(), 'sd_recommended'),
            'assets/iconic_portrait.jpg',
        )

    def test_default_style_is_sd_recommended(self):
        from apps.epg.tasks import _sd_pick_poster_url, SD_POSTER_STYLE_DEFAULT

        self.assertEqual(SD_POSTER_STYLE_DEFAULT, 'sd_recommended')
        images = [
            {
                'uri': 'assets/primary.jpg',
                'width': '960',
                'aspect': '16x9',
                'category': 'Iconic',
                'primary': 'true',
            },
        ]
        self.assertEqual(_sd_pick_poster_url(images), 'assets/primary.jpg')

    def test_style_fallback_uses_primary_before_cross_orientation(self):
        from apps.epg.tasks import _sd_pick_poster_url

        images = [
            {
                'uri': 'assets/iconic_portrait.jpg',
                'width': '960',
                'aspect': '2x3',
                'category': 'Iconic',
            },
            {
                'uri': 'assets/landscape_primary.jpg',
                'width': '1920',
                'aspect': '16x9',
                'category': 'Iconic',
                'primary': 'true',
            },
        ]
        # square_iconic has no 1x1 images; should pick SD primary before portrait iconic fallback
        self.assertEqual(
            _sd_pick_poster_url(images, 'square_iconic'),
            'assets/landscape_primary.jpg',
        )
