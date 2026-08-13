from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from core.xtream_codes import Client, _redact_params


class XtreamCodesCredentialLoggingTests(SimpleTestCase):
    def test_sensitive_request_parameters_are_redacted(self):
        self.assertEqual(
            _redact_params(
                {
                    'username': 'alice',
                    'password': 'secret',
                    'action': 'get_series_info',
                    'series_id': '42',
                }
            ),
            {
                'username': '[REDACTED]',
                'password': '[REDACTED]',
                'action': 'get_series_info',
                'series_id': '42',
            },
        )

    def test_request_failure_does_not_log_or_raise_rendered_credentials(self):
        client = Client('https://provider.example', 'alice', 'secret')
        failure = requests.Timeout(
            'timed out requesting '
            'https://provider.example/player_api.php?username=alice&password=secret'
        )
        with (
            patch.object(client.session, 'get', side_effect=failure),
            self.assertLogs('core.xtream_codes', level='DEBUG') as captured,
        ):
            with self.assertRaisesMessage(ValueError, 'XC API Request failed (Timeout)'):
                client._make_request(
                    'player_api.php',
                    {'username': 'alice', 'password': 'secret'},
                )

        output = '\n'.join(captured.output)
        self.assertNotIn('alice', output)
        self.assertNotIn('secret', output)
        self.assertIn('[REDACTED]', output)
