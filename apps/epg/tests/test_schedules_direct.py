"""
Tests for the Schedules Direct EPG integration.

Covers:
- EPGSource model: username field presence and help text
- EPGSource serializer: username field included in output
- fetch_schedules_direct: credential validation
- fetch_schedules_direct: SHA1 password hashing and token exchange
- fetch_schedules_direct: graceful error handling on auth failure
- parse_schedules_direct_time: correct UTC parsing
- EPG signals: SD sources skip the XMLTV program parser
"""

import hashlib
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.epg.models import EPGSource, EPGData
from apps.epg.serializers import EPGSourceSerializer


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

class SDSourceSignalTests(TestCase):
    """SD EPG sources must skip the XMLTV program parser signal."""

    @patch('apps.channels.signals.parse_programs_for_tvg_id')
    def test_sd_source_skips_xmltv_parse_on_channel_create(self, mock_parse):
        """Creating a channel linked to an SD EPG source must not trigger
        the XMLTV program parser — SD data is handled by fetch_schedules_direct."""
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

        mock_parse.delay.assert_not_called()


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
