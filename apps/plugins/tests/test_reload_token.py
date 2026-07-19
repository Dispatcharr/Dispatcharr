"""Reload-token handling must converge across workers.

Reacting to a stale .reload_token must reload locally without re-touching the
token. Re-touching turns every consumer into a producer and causes a permanent
force-reload ping-pong under multi-worker uWSGI.
"""

import os
import shutil
import tempfile
import time
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.loader import PluginManager


class PluginReloadTokenTests(SimpleTestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="dispatcharr-plugins-")
        self._env = patch.dict(os.environ, {"DISPATCHARR_PLUGINS_DIR": self._tmpdir})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_worker(self) -> PluginManager:
        return PluginManager()

    def _pin_token_mtime(self, worker: PluginManager, age_seconds: float = 60.0) -> float:
        """Write the token file with an older mtime so a retouch is detectable."""
        worker._touch_reload_token()
        pinned = time.time() - age_seconds
        os.utime(worker._reload_token_path, (pinned, pinned))
        return worker._get_reload_token()

    def test_reacting_to_stale_token_does_not_retouch(self):
        """Consuming a reload signal must not re-broadcast it."""
        worker = self._make_worker()
        seed = self._pin_token_mtime(worker)
        self.assertGreater(seed, 0.0)

        # Process has never observed this token (fresh worker after a reload).
        worker._last_reload_token = 0.0
        worker._discovery_completed = False

        worker.discover_plugins(sync_db=False, use_cache=True)

        self.assertEqual(
            worker._get_reload_token(),
            seed,
            "reacting to a stale reload token must not bump .reload_token",
        )
        self.assertEqual(worker._last_reload_token, seed)

    def test_stale_token_still_force_reloads_locally(self):
        """A stale token must still purge/reload modules in this process."""
        worker = self._make_worker()
        self._pin_token_mtime(worker)
        worker._last_reload_token = 0.0
        worker._discovery_completed = False

        with patch.object(worker, "_touch_reload_token") as mock_touch:
            with patch.object(
                worker, "_discover_plugins_impl", return_value={}
            ) as mock_impl:
                worker.discover_plugins(sync_db=False, use_cache=True)

        mock_touch.assert_not_called()
        mock_impl.assert_called_once()
        self.assertTrue(mock_impl.call_args.kwargs["force_reload"])

    def test_explicit_force_reload_touches_token(self):
        """Caller-requested force_reload must broadcast to other workers."""
        worker = self._make_worker()
        seed = self._pin_token_mtime(worker)
        worker._last_reload_token = seed
        worker._discovery_completed = True

        worker.discover_plugins(sync_db=False, force_reload=True)

        self.assertGreater(worker._get_reload_token(), seed)
        self.assertEqual(worker._last_reload_token, worker._get_reload_token())

    def test_multi_worker_stale_reactions_converge(self):
        """Two workers reacting to one broadcast must not ping-pong forever."""
        worker_a = self._make_worker()
        worker_b = self._make_worker()

        # Legitimate broadcast (install/update/reload API), pinned so any
        # later consumer retouch is visible in mtime comparisons.
        worker_a.discover_plugins(sync_db=False, force_reload=True)
        broadcast = self._pin_token_mtime(worker_a)
        worker_a._last_reload_token = broadcast
        worker_a._discovery_completed = True

        # Worker B has not seen the broadcast yet.
        worker_b._last_reload_token = 0.0
        worker_b._discovery_completed = False

        # Alternate discoveries as connect-event dispatch would across workers.
        for _ in range(5):
            worker_a.discover_plugins(sync_db=False, use_cache=True)
            worker_b.discover_plugins(sync_db=False, use_cache=True)

        self.assertEqual(worker_a._get_reload_token(), broadcast)
        self.assertEqual(worker_b._get_reload_token(), broadcast)
        self.assertEqual(worker_a._last_reload_token, broadcast)
        self.assertEqual(worker_b._last_reload_token, broadcast)

    def test_cache_hit_skips_discovery_after_convergence(self):
        """Steady-state connect events must not re-enter discovery."""
        worker = self._make_worker()
        worker.discover_plugins(sync_db=False, force_reload=True)

        with patch.object(
            worker, "_discover_plugins_impl", return_value={}
        ) as mock_impl:
            worker.discover_plugins(sync_db=False, use_cache=True)
            worker.discover_plugins(sync_db=False, use_cache=True)

        mock_impl.assert_not_called()
