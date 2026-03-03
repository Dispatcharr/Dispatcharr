"""Tests for dispatcharr/wsgi.py gevent monkey-patching."""

import os
import subprocess
import sys
import unittest


class TestWSGIGeventPatching(unittest.TestCase):
    """Verify that wsgi.py applies gevent monkey-patching before Django imports.

    These tests run in subprocesses because monkey.patch_all() must execute
    before any other imports.  By the time Django's test runner loads this
    file, ssl/socket are already imported, so calling patch_all() in-process
    would fail.  A subprocess mirrors how uWSGI actually loads wsgi.py.
    """

    def test_socket_is_patched_after_wsgi_import(self):
        """Loading wsgi.py first (as uWSGI does) should patch sockets."""
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import dispatcharr.wsgi; "
                "from gevent import monkey; "
                "assert monkey.is_module_patched('socket'), "
                "'socket module was not patched by wsgi.py'; "
                "print('PASS')",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "dispatcharr.settings"},
            timeout=60,
            cwd="/app",
        )
        self.assertEqual(
            result.returncode,
            0,
            f"monkey-patching check failed:\n{result.stderr}",
        )
