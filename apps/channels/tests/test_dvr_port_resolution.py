import os
from django.test import SimpleTestCase
from unittest.mock import patch

from apps.channels.tasks import get_dvr_stream_base_url


class DVRStreamBaseURLTests(SimpleTestCase):
    """
    Tests that get_dvr_stream_base_url() returns the correct single URL
    for each deployment mode.
    """

    @patch.dict(os.environ, {}, clear=True)
    def test_aio_default_uses_localhost_5656(self):
        """AIO mode (default) reaches uwsgi directly on loopback port 5656."""
        url = get_dvr_stream_base_url()
        self.assertEqual(url, 'http://127.0.0.1:5656')

    @patch.dict(os.environ, {'DISPATCHARR_ENV': 'aio'}, clear=True)
    def test_aio_explicit_uses_localhost_5656(self):
        """Explicit DISPATCHARR_ENV=aio also uses loopback port 5656."""
        url = get_dvr_stream_base_url()
        self.assertEqual(url, 'http://127.0.0.1:5656')

    @patch.dict(os.environ, {'DISPATCHARR_ENV': 'dev'}, clear=True)
    def test_dev_mode_uses_localhost_5656(self):
        """Dev mode shares the container with uwsgi — uses loopback port 5656."""
        url = get_dvr_stream_base_url()
        self.assertEqual(url, 'http://127.0.0.1:5656')

    @patch.dict(os.environ, {'DISPATCHARR_ENV': 'modular', 'DISPATCHARR_PORT': '9191'}, clear=True)
    def test_modular_uses_web_service_name(self):
        """Modular mode uses the 'web' Docker service name by default."""
        url = get_dvr_stream_base_url()
        self.assertEqual(url, 'http://web:9191')

    @patch.dict(os.environ, {'DISPATCHARR_ENV': 'modular', 'DISPATCHARR_PORT': '8080'}, clear=True)
    def test_modular_custom_port(self):
        """Modular mode respects DISPATCHARR_PORT."""
        url = get_dvr_stream_base_url()
        self.assertEqual(url, 'http://web:8080')

    @patch.dict(os.environ, {
        'DISPATCHARR_ENV': 'modular',
        'DISPATCHARR_PORT': '9191',
        'DISPATCHARR_WEB_HOST': 'dispatcharr_web',
    }, clear=True)
    def test_modular_custom_web_host(self):
        """DISPATCHARR_WEB_HOST overrides the default 'web' service name."""
        url = get_dvr_stream_base_url()
        self.assertEqual(url, 'http://dispatcharr_web:9191')

    @patch.dict(os.environ, {
        'DISPATCHARR_INTERNAL_TS_BASE_URL': 'http://custom:1234',
        'DISPATCHARR_ENV': 'modular',
    }, clear=True)
    def test_explicit_override_always_wins(self):
        """DISPATCHARR_INTERNAL_TS_BASE_URL takes priority over all other settings."""
        url = get_dvr_stream_base_url()
        self.assertEqual(url, 'http://custom:1234')

    @patch.dict(os.environ, {
        'DISPATCHARR_INTERNAL_TS_BASE_URL': 'http://custom:1234/',
    }, clear=True)
    def test_explicit_override_strips_trailing_slash(self):
        """Trailing slash is stripped from DISPATCHARR_INTERNAL_TS_BASE_URL."""
        url = get_dvr_stream_base_url()
        self.assertEqual(url, 'http://custom:1234')
