import json
import uuid
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

    def test_unstarted_progress_and_completion_do_not_create_records(self):
        client = MagicMock()
        pipe = client.pipeline.return_value.__enter__.return_value
        pipe.hget.return_value = None
        with patch.object(task_history, "_client", return_value=client):
            task_history.record_task_progress("p", "awaited", 20, "working")
            task_history.record_task_complete("p", "awaited", "ok", result={})
        pipe.multi.assert_not_called()
        client.eval.assert_not_called()

    def test_started_task_is_created_and_can_complete(self):
        client = MagicMock()
        pipe = client.pipeline.return_value.__enter__.return_value
        pipe.hget.side_effect = [None, json.dumps({"action_id": "scan", "status": "running"})]
        with patch.object(task_history, "_client", return_value=client):
            task_history.record_task_started("p", "queued", "scan", "Scan")
            task_history.record_task_complete("p", "queued", "ok", result={"done": True})
        self.assertEqual(pipe.hset.call_count, 2)
        self.assertEqual(json.loads(pipe.hset.call_args.args[2])["status"], "ok")

    def test_awaited_updates_do_not_evict_redis_history(self):
        client = task_history._client()
        if client is None:
            self.skipTest("Redis is unavailable")
        try:
            client.ping()
        except Exception:
            self.skipTest("Redis is unavailable")
        key = f"history-test-{uuid.uuid4()}"
        self.addCleanup(client.delete, *task_history._history_keys(key))
        with patch.object(task_history, "HISTORY_MAX_ENTRIES", 50):
            for i in range(50):
                task_history.record_task_started(key, f"queued-{i}", "scan", "Scan")
                task_history.record_task_complete(key, f"queued-{i}", "ok")
            for i in range(50):
                task_history.record_task_progress(key, f"awaited-{i}", 20, "working")
                task_history.record_task_complete(key, f"awaited-{i}", "ok")
            self.assertEqual({r["task_id"] for r in task_history.get_task_history(key)},
                             {f"queued-{i}" for i in range(50)})
            self.assertEqual(client.zcard(task_history._history_keys(key)[0]), 50)
