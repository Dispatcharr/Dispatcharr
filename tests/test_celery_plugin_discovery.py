"""
Regression tests for the worker_ready hook in `dispatcharr/celery.py`
that eagerly discovers plugins so their @shared_task definitions
register with the worker before beat starts firing.

Without this hook, plugins shipping module-level @shared_task code
(e.g. cron-scheduled background jobs) silently miss the first beat
tick after every worker restart — the worker logs
`Received unregistered task` and beat advances `last_run_at` anyway,
hiding the failure. See #1244.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


class WorkerReadyPluginDiscoveryTests(SimpleTestCase):
    def test_invokes_discover_plugins_with_sync_db_false(self):
        """The handler must call PluginManager.discover_plugins(sync_db=False).
        sync_db=False is intentional: discovery on every worker boot must
        not touch the DB schema, just import plugin modules so their
        @shared_task decorators run."""
        from dispatcharr.celery import discover_plugins_on_worker_ready

        mock_pm = MagicMock()
        with patch(
            "apps.plugins.loader.PluginManager.get", return_value=mock_pm
        ) as mock_get:
            discover_plugins_on_worker_ready()

        mock_get.assert_called_once()
        mock_pm.discover_plugins.assert_called_once_with(sync_db=False)

    def test_swallows_plugin_loader_errors(self):
        """If the plugin loader explodes, the worker must still come up —
        the handler must not propagate exceptions."""
        from dispatcharr.celery import discover_plugins_on_worker_ready

        with patch(
            "apps.plugins.loader.PluginManager.get",
            side_effect=RuntimeError("plugin loader exploded"),
        ):
            # Must NOT raise.
            discover_plugins_on_worker_ready()

    def test_swallows_discover_plugins_errors(self):
        """Failure inside discover_plugins itself (e.g. one plugin's
        plugin.py has an import error) must also be swallowed — one bad
        plugin shouldn't keep the worker from coming up."""
        from dispatcharr.celery import discover_plugins_on_worker_ready

        mock_pm = MagicMock()
        mock_pm.discover_plugins.side_effect = ImportError("bad plugin")
        with patch(
            "apps.plugins.loader.PluginManager.get", return_value=mock_pm
        ):
            # Must NOT raise.
            discover_plugins_on_worker_ready()

    def test_handler_is_connected_to_worker_ready(self):
        """The connect decorator must have wired the handler into the
        worker_ready signal so Celery actually fires it at startup."""
        from celery.signals import worker_ready
        from dispatcharr.celery import discover_plugins_on_worker_ready

        # signal.receivers is a list of (lookup_key, weakref_or_func) pairs.
        # The handler is registered with weak=False so the function appears
        # directly (not as a dead weakref).
        receivers = [r for _, r in worker_ready.receivers]
        # Handle both weakref-wrapped and direct receiver shapes.
        callables = [r() if hasattr(r, "__call__") and not callable(getattr(r, "__name__", None)) else r for r in receivers]
        assert discover_plugins_on_worker_ready in receivers or \
            any(getattr(c, "__wrapped__", c) is discover_plugins_on_worker_ready for c in callables), (
            "discover_plugins_on_worker_ready was not connected to "
            "Celery's worker_ready signal"
        )
