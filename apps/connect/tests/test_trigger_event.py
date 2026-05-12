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
    def _run_trigger_event(self, plugins, event_name, payload):
        pm = MagicMock()
        pm.list_plugins.return_value = plugins
        with patch(
            "apps.connect.utils.PluginManager.get", return_value=pm
        ), patch(
            "apps.connect.utils.EventSubscription.objects.filter",
            return_value=_empty_subscription_chain(),
        ):
            from apps.connect.utils import trigger_event

            trigger_event(event_name, payload)
        return pm

    def test_disabled_plugin_does_not_abort_dispatch_for_later_enabled_plugin(self):
        """The original bug: AttributeError on a disabled plugin's debug log
        aborted the loop, so any plugin iterated AFTER a disabled one never
        received events."""
        plugins = [
            {
                "key": "disabled-plugin",
                "name": "Disabled Plugin",
                "enabled": False,
                "actions": [],
            },
            {
                "key": "enabled-plugin",
                "name": "Enabled Plugin",
                "enabled": True,
                "actions": [
                    {"id": "on_event", "events": ["channel_start"]},
                ],
            },
        ]

        pm = self._run_trigger_event(
            plugins, "channel_start", {"channel_name": "TEST"}
        )

        pm.run_action.assert_called_once_with(
            "enabled-plugin",
            "on_event",
            {"event": "channel_start", "payload": {"channel_name": "TEST"}},
        )

    def test_action_without_matching_event_is_not_dispatched(self):
        """Sanity check: actions whose `events` list doesn't include the
        fired event, or which have no `events` key at all, are skipped."""
        plugins = [
            {
                "key": "plugin",
                "name": "Plugin",
                "enabled": True,
                "actions": [
                    {"id": "on_event", "events": ["channel_stop"]},
                    {"id": "manual_button"},  # no events key
                ],
            },
        ]

        pm = self._run_trigger_event(
            plugins, "channel_start", {"channel_name": "TEST"}
        )

        pm.run_action.assert_not_called()
