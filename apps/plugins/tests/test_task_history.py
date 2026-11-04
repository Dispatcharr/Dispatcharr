import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.plugins import task_history


class PluginTaskHistoryTests(SimpleTestCase):
    def test_filter_accepts_legacy_and_triggered_records(self):
        client = MagicMock()
        client.zrevrange.return_value = ["a", "b", "c"]
        client.hmget.return_value = [
            json.dumps({"action_id": "scan", "trigger": "schedule"}),
            json.dumps({"action_label": "Manual"}),
            "null",
        ]
        with patch.object(task_history, "_client", return_value=client):
            self.assertEqual([r["task_id"] for r in task_history.get_task_history("p", "schedule")], ["a"])
            self.assertEqual([r["task_id"] for r in task_history.get_task_history("p", "unknown")], ["b"])

    def test_late_progress_does_not_overwrite_finished_record(self):
        client = MagicMock()
        pipe = client.pipeline.return_value.__enter__.return_value
        pipe.hget.return_value = json.dumps({"status": "error", "error": "failed"})
        with patch.object(task_history, "_client", return_value=client):
            task_history.record_task_progress("p", "task", 20, "late")
        pipe.multi.assert_not_called()
        client.eval.assert_not_called()
