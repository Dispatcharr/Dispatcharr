"""Connect must expose every live-proxy runtime event plugins may subscribe to."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.connect.models import SUPPORTED_EVENTS, EventSubscription
from core.models import SystemEvent


class SupportedEventsTests(SimpleTestCase):
    def test_channel_buffering_is_subscribable(self):
        self.assertIn("channel_buffering", SUPPORTED_EVENTS)
        choices = dict(EventSubscription._meta.get_field("event").choices)
        self.assertIn("channel_buffering", choices)

    def test_live_proxy_runtime_events_are_all_subscribable(self):
        system_event_types = dict(SystemEvent.EVENT_TYPES)
        for event in (
            "channel_buffering",
            "channel_failover",
            "channel_reconnect",
            "channel_error",
            "stream_switch",
        ):
            self.assertIn(event, system_event_types)
            self.assertIn(event, SUPPORTED_EVENTS)

    def test_trigger_event_dispatches_channel_buffering_to_plugins(self):
        pm = MagicMock()
        pm.iter_actions_for_event.return_value = [("my_plugin", "on_buffering")]

        empty_qs = MagicMock()
        empty_qs.count.return_value = 0
        empty_qs.__iter__ = lambda self: iter([])
        chain = MagicMock()
        chain.select_related.return_value = empty_qs

        enabled_qs = MagicMock()
        enabled_qs.values_list.return_value = ["my_plugin"]

        payload = {"channel_id": "abc", "stream_id": 5678, "speed": 0.4}
        with patch("apps.connect.utils.PluginManager.get", return_value=pm), patch(
            "apps.connect.utils.EventSubscription.objects.filter", return_value=chain
        ), patch("apps.plugins.models.PluginConfig") as mock_cfg:
            mock_cfg.objects.filter.return_value = enabled_qs
            from apps.connect.utils import trigger_event

            trigger_event("channel_buffering", payload)

        pm.run_action.assert_called_once_with(
            "my_plugin", "on_buffering", {"event": "channel_buffering", "payload": payload}
        )
