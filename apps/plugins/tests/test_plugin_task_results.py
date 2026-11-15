from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.tasks import PluginActionResultError, run_plugin_action_task


class PluginTaskResultTests(SimpleTestCase):
    @patch("apps.plugins.task_history.record_task_complete")
    @patch("core.utils.send_websocket_update")
    @patch("apps.plugins.loader.PluginManager.get")
    def test_refresh_directives(self, get_manager, send, record):
        manager = get_manager.return_value
        for directive, status, reload_expected in [
            ({"refresh": "plugin"}, "ok", True),
            ({"refresh": "plugin"}, "partial", True),
            ({"refresh": "ui"}, "ok", False),
            ({"refresh": "unknown"}, "ok", False),
            ("plugin", "ok", False),
            (None, "ok", False),
            ({"refresh": "plugin"}, "error", False),
        ]:
            with self.subTest(directive=directive, status=status):
                manager.reload_plugin.reset_mock()
                result = {"status": status, "_dispatcharr": directive}
                manager.run_action.return_value = result
                if status == "error":
                    with self.assertRaises(RuntimeError):
                        run_plugin_action_task.run("example", "run")
                else:
                    self.assertEqual(run_plugin_action_task.run("example", "run"), result)
                self.assertEqual(manager.reload_plugin.call_count, int(reload_expected))
                self.assertEqual(send.call_args.args[2]["result"], result)
                self.assertEqual(record.call_args.kwargs["result"], result)

    @patch("apps.plugins.task_history.record_task_complete")
    @patch("core.utils.send_websocket_update")
    @patch("apps.plugins.loader.PluginManager.get")
    def test_reload_failure_reports_error_and_preserves_result(self, get_manager, send, record):
        manager = get_manager.return_value
        result = {"status": "ok", "_dispatcharr": {"refresh": "plugin"}}
        manager.run_action.return_value = result
        for failure in (False, RuntimeError("reload failed")):
            with self.subTest(failure=failure):
                manager.reload_plugin.side_effect = failure if isinstance(failure, Exception) else None
                manager.reload_plugin.return_value = failure
                with self.assertRaises(RuntimeError):
                    run_plugin_action_task.run("example", "run")
                self.assertEqual(send.call_args.args[2]["status"], "error")
                self.assertEqual(record.call_args.kwargs["result"], result)

    @patch("apps.plugins.task_history.record_task_complete")
    @patch("core.utils.send_websocket_update")
    @patch("apps.plugins.loader.PluginManager.get")
    def test_reload_finishes_before_completion(self, get_manager, send, record):
        manager = get_manager.return_value
        manager.run_action.return_value = {"_dispatcharr": {"refresh": "plugin"}}
        def reload_plugin(key):
            self.assertEqual(key, "example")
            send.assert_not_called()
            record.assert_not_called()
            return True
        manager.reload_plugin.side_effect = reload_plugin
        run_plugin_action_task.run("example", "run")
        manager.reload_plugin.assert_called_once_with("example")
        send.assert_called_once()
        record.assert_called_once()

    @patch("apps.plugins.task_history.record_task_complete")
    @patch("core.utils.send_websocket_update")
    @patch("apps.plugins.loader.PluginManager.get")
    def test_returned_results(self, get_manager, send, record):
        for result, status in [({"status": "ok", "items": [1, 2]}, "ok"), ({"status": "partial", "message": "some failed", "items": [3]}, "partial")]:
            with self.subTest(status=status):
                get_manager.return_value.run_action.return_value = result
                send.reset_mock()
                record.reset_mock()
                self.assertEqual(run_plugin_action_task.run("example", "run"), result)
                self.assertEqual(send.call_args.args[2]["status"], status)
                self.assertEqual(send.call_args.args[2]["result"], result)
                self.assertEqual(record.call_args.args[2], status)
                self.assertEqual(record.call_args.kwargs["result"], result)

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

    @patch("apps.plugins.task_history.record_task_complete")
    @patch("core.utils.send_websocket_update")
    @patch("apps.plugins.loader.PluginManager.get")
    def test_exception_has_no_result(self, get_manager, send, record):
        get_manager.return_value.run_action.side_effect = ValueError("failed")
        with self.assertRaisesRegex(ValueError, "failed"):
            run_plugin_action_task.run("example", "run")
        self.assertIsNone(send.call_args.args[2]["result"])
        self.assertIsNone(record.call_args.kwargs["result"])

    @patch("apps.plugins.task_history.record_task_complete")
    @patch("core.utils.send_websocket_update")
    @patch("apps.plugins.loader.PluginManager.get")
    def test_non_json_result_fails_with_safe_terminal_payload(self, get_manager, send, record):
        for result in ({"items": {1, 2}}, {"status": "error", "items": {1}}):
            with self.subTest(result=result):
                get_manager.return_value.run_action.return_value = result
                with self.assertRaisesRegex(TypeError, "not JSON serializable"):
                    run_plugin_action_task.run("example", "run")
                self.assertEqual(send.call_args.args[2]["status"], "error")
                self.assertIsNone(send.call_args.args[2]["result"])
                self.assertEqual(record.call_args.args[2], "error")
                self.assertIsNone(record.call_args.kwargs["result"])

    def test_returned_error_survives_celery_backend_encoding(self):
        from celery import Celery

        backend = Celery("test", backend="cache+memory://").backend
        result = {"status": "error", "failed_items": ["one"]}
        encoded = backend.encode(backend.prepare_exception(PluginActionResultError("failed", result)))
        restored = backend.exception_to_python(backend.decode(encoded))
        self.assertIsInstance(restored, PluginActionResultError)
        self.assertEqual(str(restored), "failed")
        self.assertEqual(restored.result, result)
