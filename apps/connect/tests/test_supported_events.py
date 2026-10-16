"""Connect must expose every live-proxy runtime event plugins may subscribe to."""

from django.test import SimpleTestCase

from apps.connect.models import SUPPORTED_EVENTS, EventSubscription
from core.models import SystemEvent


class SupportedEventsTests(SimpleTestCase):
    def test_live_proxy_runtime_events_are_all_subscribable(self):
        system_event_types = dict(SystemEvent.EVENT_TYPES)
        subscription_choices = dict(EventSubscription._meta.get_field("event").choices)
        for event in (
            "channel_buffering",
            "channel_failover",
            "channel_reconnect",
            "channel_error",
            "stream_switch",
        ):
            self.assertIn(event, system_event_types)
            self.assertIn(event, SUPPORTED_EVENTS)
            self.assertIn(event, subscription_choices)
