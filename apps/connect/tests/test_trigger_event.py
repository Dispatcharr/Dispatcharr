"""
Regression tests for the plugin event dispatch loop in apps.connect.utils.

Previously, trigger_event accessed `plugin.key` / `plugin.name` (attribute
access) on dict items returned by PluginManager.list_plugins(). On the
first disabled plugin encountered, that f-string raised AttributeError —
and because Python evaluates f-string arguments eagerly even when the
logger discards the message at INFO level, the exception bubbled out of
trigger_event with no try/except. Any enabled plugin sorted after a
disabled one then silently received zero events.

These tests guard against regression by:

1. Feeding trigger_event a plugins list with a disabled plugin BEFORE an
   enabled-with-events plugin and asserting the enabled plugin's action
   is still dispatched.
2. Sanity-checking that actions without a matching `events` entry are
   not dispatched.

Event-triggered actions are always dispatched via Celery (queue="plugins"),
fire-and-forget, never run inline.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


def _empty_subscription_chain():
    """Mock the EventSubscription.objects.filter(...).select_related(...)
    chain to yield no subscriptions, so trigger_event proceeds straight to
    the plugin loop."""
    empty_qs = MagicMock()
    empty_qs.count.return_value = 0
    empty_qs.__iter__ = lambda self: iter([])
    chain = MagicMock()
    chain.select_related.return_value = empty_qs
    return chain


class TriggerEventDispatchTests(SimpleTestCase):
    def _run_trigger_event(self, handlers, event_name, payload, enabled_keys=None):
        pm = MagicMock()
        pm.iter_actions_for_event.return_value = handlers
        if enabled_keys is None:
            enabled_keys = [key for key, _ in handlers]

        enabled_qs = MagicMock()
        enabled_qs.values_list.return_value = enabled_keys

        with patch(
            "apps.connect.utils.PluginManager.get", return_value=pm
        ), patch(
            "apps.connect.utils.EventSubscription.objects.filter",
            return_value=_empty_subscription_chain(),
        ), patch(
            "apps.plugins.models.PluginConfig"
        ) as mock_cfg, patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async"
        ) as mock_apply_async:
            mock_cfg.objects.filter.return_value = enabled_qs
            from apps.connect.utils import trigger_event

            trigger_event(event_name, payload)
        return pm, mock_apply_async

    def test_disabled_plugin_does_not_abort_dispatch_for_later_enabled_plugin(self):
        """Enabled handlers still run when other plugins are disabled in DB."""
        handlers = [
            ("enabled-plugin", "on_event"),
        ]

        pm, mock_apply_async = self._run_trigger_event(
            handlers, "channel_start", {"channel_name": "TEST"}
        )

        mock_apply_async.assert_called_once_with(
            args=["enabled-plugin", "on_event", {"event": "channel_start", "payload": {"channel_name": "TEST"}}],
            queue="plugins",
        )

    def test_skips_handlers_for_disabled_plugins(self):
        handlers = [
            ("disabled-plugin", "on_event"),
            ("enabled-plugin", "on_event"),
        ]

        pm, mock_apply_async = self._run_trigger_event(
            handlers,
            "channel_start",
            {"channel_name": "TEST"},
            enabled_keys=["enabled-plugin"],
        )

        mock_apply_async.assert_called_once_with(
            args=["enabled-plugin", "on_event", {"event": "channel_start", "payload": {"channel_name": "TEST"}}],
            queue="plugins",
        )

    def test_action_without_matching_event_is_not_dispatched(self):
        """When no handlers are registered for the event, nothing is dispatched."""
        pm, mock_apply_async = self._run_trigger_event(
            [], "channel_start", {"channel_name": "TEST"}
        )

        mock_apply_async.assert_not_called()

    def test_no_plugin_config_query_when_no_handlers(self):
        pm = MagicMock()
        pm.iter_actions_for_event.return_value = []
        with patch(
            "apps.connect.utils.PluginManager.get", return_value=pm
        ), patch(
            "apps.connect.utils.EventSubscription.objects.filter",
            return_value=_empty_subscription_chain(),
        ), patch(
            "apps.plugins.models.PluginConfig"
        ) as mock_cfg:
            from apps.connect.utils import trigger_event

            trigger_event("channel_start", {"channel_name": "TEST"})

        mock_cfg.objects.filter.assert_not_called()

    def test_plugin_action_failure_does_not_block_sibling_handlers(self):
        handlers = [
            ("failing-plugin", "on_event"),
            ("working-plugin", "on_event"),
        ]

        pm = MagicMock()
        pm.iter_actions_for_event.return_value = handlers

        enabled_qs = MagicMock()
        enabled_qs.values_list.return_value = ["failing-plugin", "working-plugin"]

        with patch(
            "apps.connect.utils.PluginManager.get", return_value=pm
        ), patch(
            "apps.connect.utils.EventSubscription.objects.filter",
            return_value=_empty_subscription_chain(),
        ), patch(
            "apps.plugins.models.PluginConfig"
        ) as mock_cfg, patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async",
            side_effect=[RuntimeError("boom"), MagicMock()],
        ) as mock_apply_async:
            mock_cfg.objects.filter.return_value = enabled_qs
            from apps.connect.utils import trigger_event

            trigger_event("channel_start", {"channel_name": "TEST"})

        self.assertEqual(mock_apply_async.call_count, 2)
        mock_apply_async.assert_any_call(
            args=["failing-plugin", "on_event", {"event": "channel_start", "payload": {"channel_name": "TEST"}}],
            queue="plugins",
        )
        mock_apply_async.assert_any_call(
            args=["working-plugin", "on_event", {"event": "channel_start", "payload": {"channel_name": "TEST"}}],
            queue="plugins",
        )
