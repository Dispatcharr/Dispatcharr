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

from apps.epg.models import EPGSource
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

    def test_password_in_serializer_fields(self):
        source = EPGSource.objects.create(
            name='SD API Key Test',
            source_type='schedules_direct',
            password='secret',
        )
        data = EPGSourceSerializer(source).data
        self.assertIn('password', data)


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
