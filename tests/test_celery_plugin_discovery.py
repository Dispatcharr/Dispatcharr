"""
Regression tests for the worker_process_init hook in `dispatcharr/celery.py`
that eagerly discovers plugins so their @shared_task definitions
register with the worker before beat starts firing.

Without this hook, plugins shipping module-level @shared_task code
(e.g. cron-scheduled background jobs) silently miss the first beat
tick after every worker restart — the worker logs
`Received unregistered task` and beat advances `last_run_at` anyway,
hiding the failure. See #1244.
"""
import weakref
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


class WorkerProcessInitPluginDiscoveryTests(SimpleTestCase):
    def test_invokes_discover_plugins_with_sync_db_false(self):
        """The handler must call PluginManager.discover_plugins(sync_db=False).
        sync_db=False is intentional: discovery on every worker boot must
        not touch the DB schema, just import plugin modules so their
        @shared_task decorators run."""
        from dispatcharr.celery import init_worker_process

        mock_pm = MagicMock()
        with patch(
            "apps.plugins.loader.PluginManager.get", return_value=mock_pm
        ) as mock_get:
            with patch("django.db.connections.close_all"):
                init_worker_process()

        mock_get.assert_called_once()
        mock_pm.discover_plugins.assert_called_once_with(sync_db=False)

    def test_closes_inherited_db_connections_before_discovery(self):
        from dispatcharr.celery import init_worker_process

        with patch("django.db.connections.close_all") as mock_close_all:
            with patch("apps.plugins.loader.PluginManager.get"):
                init_worker_process()

        mock_close_all.assert_called_once()

    def test_swallows_plugin_loader_errors(self):
        """If the plugin loader explodes, the worker must still come up —
        the handler must not propagate exceptions."""
        from dispatcharr.celery import init_worker_process

        with patch("django.db.connections.close_all"):
            with patch(
                "apps.plugins.loader.PluginManager.get",
                side_effect=RuntimeError("plugin loader exploded"),
            ):
                # Must NOT raise.
                init_worker_process()

    def test_swallows_discover_plugins_errors(self):
        """Failure inside discover_plugins itself (e.g. one plugin's
        plugin.py has an import error) must also be swallowed — one bad
        plugin shouldn't keep the worker from coming up."""
        from dispatcharr.celery import init_worker_process

        mock_pm = MagicMock()
        mock_pm.discover_plugins.side_effect = ImportError("bad plugin")
        with patch("django.db.connections.close_all"):
            with patch(
                "apps.plugins.loader.PluginManager.get", return_value=mock_pm
            ):
                # Must NOT raise.
                init_worker_process()

    def test_handler_is_connected_to_worker_process_init(self):
        """The connect decorator must have wired the handler into the
        worker_process_init signal so Celery actually fires it after fork."""
        from celery.signals import worker_process_init
        from dispatcharr.celery import init_worker_process

        receivers = [r for _, r in worker_process_init.receivers]
        callables = [r() if isinstance(r, weakref.ref) else r for r in receivers]
        assert init_worker_process in receivers or \
            any(getattr(c, "__wrapped__", c) is init_worker_process for c in callables), (
            "init_worker_process was not connected to "
            "Celery's worker_process_init signal"
        )
