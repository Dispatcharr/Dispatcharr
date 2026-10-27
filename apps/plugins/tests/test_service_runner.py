import logging
import threading

from django.test import SimpleTestCase

from apps.plugins.context import plugin_has_capability, running_as_plugin
from apps.plugins.service_runner import PluginServiceRunner


class PluginServiceRunnerTests(SimpleTestCase):
    def setUp(self):
        self.runner = PluginServiceRunner(logging.getLogger(__name__), stop_timeout=0.1)

    def test_target_receives_stop_event_and_plugin_context(self):
        started = threading.Event()
        observed = []

        def target(stop_event):
            observed.append(plugin_has_capability("persistent_service"))
            started.set()
            stop_event.wait()

        with running_as_plugin(
            "example",
            capabilities=["persistent_service"],
            manifest_schema_version=2,
        ):
            service = self.runner.start("example", target)

        self.assertTrue(started.wait(1))
        self.assertEqual(observed, [True])
        self.runner.stop("example")
        self.assertFalse(service.thread.is_alive())

    def test_rejects_second_running_service_for_plugin(self):
        started = threading.Event()

        def target(stop_event):
            started.set()
            stop_event.wait()

        self.runner.start("example", target)
        self.assertTrue(started.wait(1))
        with self.assertRaisesRegex(RuntimeError, "already has a running"):
            self.runner.start("example", target)
        self.runner.stop("example")

    def test_stop_is_idempotent(self):
        started = threading.Event()

        def target(stop_event):
            started.set()
            stop_event.wait()

        service = self.runner.start("example", target)
        self.assertTrue(started.wait(1))
        self.runner.stop("example")
        self.runner.stop("example")
        self.assertFalse(service.thread.is_alive())

    def test_unexpected_service_failure_is_isolated(self):
        def target(_stop_event):
            raise RuntimeError("boom")

        with self.assertLogs("apps.plugins.tests.test_service_runner", level="ERROR"):
            service = self.runner.start("example", target)
            service.thread.join(1)
        self.assertFalse(service.thread.is_alive())
