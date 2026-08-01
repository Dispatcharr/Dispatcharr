"""trigger_event must route plugin action dispatch through the plugins queue
when the dedicated-worker toggle is on, and stay inline (today's behavior)
when it's off. For both, no in-flight result is ever consumed."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


def _empty_subscription_chain():
    empty_qs = MagicMock()
    empty_qs.count.return_value = 0
    empty_qs.__iter__ = lambda self: iter([])
    chain = MagicMock()
    chain.select_related.return_value = empty_qs
    return chain


class PluginDedicatedWorkerToggleRoutingTests(SimpleTestCase):
    def _run(self, toggle_enabled):
        pm = MagicMock()
        pm.iter_actions_for_event.return_value = [("my-plugin", "on_event")]

        enabled_qs = MagicMock()
        enabled_qs.values_list.return_value = ["my-plugin"]

        with patch(
            "apps.connect.utils.PluginManager.get", return_value=pm
        ), patch(
            "apps.connect.utils.EventSubscription.objects.filter",
            return_value=_empty_subscription_chain(),
        ), patch(
            "apps.plugins.models.PluginConfig"
        ) as mock_cfg, patch(
            "core.models.CoreSettings.get_plugin_dedicated_worker_enabled",
            return_value=toggle_enabled,
        ), patch(
            "apps.plugins.tasks.run_plugin_action_task.apply_async"
        ) as mock_apply_async:
            mock_cfg.objects.filter.return_value = enabled_qs
            from apps.connect.utils import trigger_event

            trigger_event("channel_start", {"channel_name": "TEST"})
        return pm, mock_apply_async

    def test_toggle_off_runs_inline(self):
        pm, mock_apply_async = self._run(toggle_enabled=False)

        pm.run_action.assert_called_once_with(
            "my-plugin",
            "on_event",
            {"event": "channel_start", "payload": {"channel_name": "TEST"}},
        )
        mock_apply_async.assert_not_called()

    def test_toggle_on_dispatches_to_plugins_queue_without_waiting(self):
        pm, mock_apply_async = self._run(toggle_enabled=True)

        pm.run_action.assert_not_called()
        mock_apply_async.assert_called_once_with(
            args=["my-plugin", "on_event", {"event": "channel_start", "payload": {"channel_name": "TEST"}}],
            queue="plugins",
        )
