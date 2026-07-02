from django.test import SimpleTestCase

from apps.plugins.loader import LoadedPlugin, PluginManager


class IterActionsForEventTests(SimpleTestCase):
    def test_yields_matching_handlers(self):
        pm = PluginManager()
        pm._registry = {
            "alpha": LoadedPlugin(
                key="alpha",
                name="Alpha",
                actions=[
                    {"id": "on_start", "events": ["channel_start"]},
                    {"id": "manual"},
                ],
            ),
            "beta": LoadedPlugin(
                key="beta",
                name="Beta",
                actions=[
                    {"id": "on_both", "events": ["channel_start", "channel_stop"]},
                ],
            ),
        }

        self.assertEqual(
            list(pm.iter_actions_for_event("channel_start")),
            [("alpha", "on_start"), ("beta", "on_both")],
        )
        self.assertEqual(list(pm.iter_actions_for_event("channel_stop")), [("beta", "on_both")])

    def test_ignores_string_events_value(self):
        pm = PluginManager()
        pm._registry = {
            "bad": LoadedPlugin(
                key="bad",
                name="Bad",
                actions=[{"id": "hook", "events": "client_connect"}],
            ),
            "good": LoadedPlugin(
                key="good",
                name="Good",
                actions=[{"id": "hook", "events": ["client_connect"]}],
            ),
        }

        self.assertEqual(
            list(pm.iter_actions_for_event("client_connect")),
            [("good", "hook")],
        )
