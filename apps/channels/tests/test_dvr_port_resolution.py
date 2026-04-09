import os
from django.test import SimpleTestCase
from unittest.mock import patch

from apps.channels.tasks import build_dvr_candidates


class DVRPortResolutionTests(SimpleTestCase):
    """
    Tests that DVR recording candidate URLs respect the DISPATCHARR_PORT
    environment variable instead of hardcoding port 9191.
    """

    @patch.dict(os.environ, {'REDIS_HOST': 'redis'}, clear=True)
    def test_default_port_uses_9191(self):
        """Without DISPATCHARR_PORT set, candidates default to 9191."""
        candidates = build_dvr_candidates()
        self.assertIn('http://web:9191', candidates)
        self.assertIn('http://localhost:9191', candidates)

    @patch.dict(os.environ, {'DISPATCHARR_PORT': '8080', 'REDIS_HOST': 'redis'}, clear=True)
    def test_custom_port_reflected_in_candidates(self):
        """DISPATCHARR_PORT=8080 replaces all hardcoded 9191 references."""
        candidates = build_dvr_candidates()
        self.assertIn('http://web:8080', candidates)
        self.assertIn('http://localhost:8080', candidates)
        self.assertNotIn('http://web:9191', candidates)
        self.assertNotIn('http://localhost:9191', candidates)

    @patch.dict(os.environ, {
        'DISPATCHARR_PORT': '7777',
        'DISPATCHARR_ENV': 'dev',
        'REDIS_HOST': 'redis',
    }, clear=True)
    def test_dev_mode_includes_5656_and_custom_port(self):
        """Dev mode includes both uwsgi internal port (5656) and custom port."""
        candidates = build_dvr_candidates()
        self.assertIn('http://127.0.0.1:5656', candidates)
        self.assertIn('http://127.0.0.1:7777', candidates)

    @patch.dict(os.environ, {
        'DISPATCHARR_INTERNAL_TS_BASE_URL': 'http://custom:1234',
        'REDIS_HOST': 'redis',
    }, clear=True)
    def test_explicit_override_is_first(self):
        """DISPATCHARR_INTERNAL_TS_BASE_URL should be the first candidate."""
        candidates = build_dvr_candidates()
        self.assertEqual(candidates[0], 'http://custom:1234')

    @patch.dict(os.environ, {
        'DISPATCHARR_PORT': '3000',
        'DISPATCHARR_INTERNAL_API_BASE': 'http://myhost:4000',
        'REDIS_HOST': 'redis',
    }, clear=True)
    def test_internal_api_base_overrides_web_fallback(self):
        """DISPATCHARR_INTERNAL_API_BASE replaces the http://web:{port} default."""
        candidates = build_dvr_candidates()
        self.assertIn('http://myhost:4000', candidates)
        self.assertNotIn('http://web:3000', candidates)
