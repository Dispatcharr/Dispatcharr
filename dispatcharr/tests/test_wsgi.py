"""Tests for dispatcharr/wsgi.py gevent monkey-patching."""

import os
import subprocess
import sys
import textwrap
import unittest


class TestWSGIGeventPatching(unittest.TestCase):
    """Verify that wsgi.py applies gevent monkey-patching before Django imports.

    These tests run in subprocesses because monkey.patch_all() must execute
    before any other imports.  By the time Django's test runner loads this
    file, ssl/socket are already imported, so calling patch_all() in-process
    would fail.  A subprocess mirrors how uWSGI actually loads wsgi.py.

    Each test injects a mock ``uwsgi`` module via ``sys.modules`` so the
    gevent_patch shim can check ``uwsgi.opt`` without a real uWSGI process.
    """

    def _run_subprocess(self, code):
        """Run *code* in a subprocess and return the CompletedProcess."""
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(code)],
            capture_output=True,
            text=True,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "dispatcharr.settings"},
            timeout=60,
            cwd="/app",
        )

    def test_socket_is_patched_after_wsgi_import(self):
        """Loading wsgi.py with gevent in uwsgi.opt should patch sockets."""
        result = self._run_subprocess("""\
            import types, sys
            mock_uwsgi = types.ModuleType('uwsgi')
            mock_uwsgi.opt = {b'gevent': b'400'}
            sys.modules['uwsgi'] = mock_uwsgi

            import dispatcharr.wsgi
            from gevent import monkey
            assert monkey.is_module_patched('socket'), \
                'socket module was not patched by wsgi.py'
            print('PASS')
        """)
        self.assertEqual(
            result.returncode,
            0,
            f"monkey-patching check failed:\n{result.stderr}",
        )

    def test_pre_patched_then_wsgi_import(self):
        """Simulates debug_wrapper: patch first, then import wsgi — no crash."""
        result = self._run_subprocess("""\
            import types, sys
            mock_uwsgi = types.ModuleType('uwsgi')
            mock_uwsgi.opt = {b'gevent': b'100'}
            sys.modules['uwsgi'] = mock_uwsgi

            from gevent_patch import patch_if_needed
            patch_if_needed()

            import dispatcharr.wsgi
            from gevent import monkey
            assert monkey.is_module_patched('socket'), \
                'socket module should still be patched'
            print('PASS')
        """)
        self.assertEqual(
            result.returncode,
            0,
            f"pre-patched + wsgi import failed:\n{result.stderr}",
        )

    def test_no_patching_without_gevent_in_uwsgi_opt(self):
        """When uwsgi.opt has no gevent key, patching must NOT happen."""
        result = self._run_subprocess("""\
            import types, sys
            mock_uwsgi = types.ModuleType('uwsgi')
            mock_uwsgi.opt = {}
            sys.modules['uwsgi'] = mock_uwsgi

            import dispatcharr.wsgi
            from gevent import monkey
            assert not monkey.is_module_patched('socket'), \
                'socket module should NOT be patched without gevent config'
            print('PASS')
        """)
        self.assertEqual(
            result.returncode,
            0,
            f"no-gevent check failed:\n{result.stderr}",
        )
