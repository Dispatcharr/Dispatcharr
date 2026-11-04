from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.tasks import run_plugin_action_task


class PluginTaskResultTests(SimpleTestCase):
    @patch("apps.plugins.task_history.record_task_complete")
    @patch("core.utils.send_websocket_update")
    @patch("apps.plugins.loader.PluginManager.get")
    def test_returned_results(self, get_manager, send, record):
        for result, status in [({"status": "ok"}, "ok"), ({"status": "partial", "message": "some failed"}, "partial")]:
            with self.subTest(status=status):
                get_manager.return_value.run_action.return_value = result
                send.reset_mock()
                record.reset_mock()
                self.assertEqual(run_plugin_action_task.run("example", "run"), result)
                self.assertEqual(send.call_args.args[2]["status"], status)
                self.assertEqual(record.call_args.args[2], status)

    @patch("apps.plugins.task_history.record_task_complete")
    @patch("core.utils.send_websocket_update")
    @patch("apps.plugins.loader.PluginManager.get")
    def test_returned_error_fails_task(self, get_manager, send, record):
        result = {"status": "error", "message": "failed", "failed_items": ["one"]}
        get_manager.return_value.run_action.return_value = result
        with self.assertRaisesRegex(RuntimeError, "failed"):
            run_plugin_action_task.run("example", "run")
        self.assertEqual(send.call_args.args[2]["status"], "error")
        self.assertEqual(send.call_args.args[2]["result"], result)
        self.assertEqual(record.call_args.args[2], "error")
        self.assertEqual(record.call_args.kwargs["result"], result)
