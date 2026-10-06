import os
import tempfile

from django.test import SimpleTestCase

from apps.channels.tasks import _dvr_recording_end_payload


class DvrRecordingEndPayloadTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "rec.mkv")
        with open(self.path, "wb") as f:
            f.write(b"\x1a\x45\xdf\xa3" * 8)

    def tearDown(self):
        self.tmp.cleanup()

    def test_completed_recording_succeeds(self):
        cp = {
            "status": "completed",
            "bytes_written": 1234,
            "file_url": "/api/channels/recordings/7/file/",
            "file_name": "rec.mkv",
        }
        payload = _dvr_recording_end_payload(cp, self.path, True)
        self.assertEqual(payload["outcome"], "success")
        self.assertTrue(payload["has_file"])
        self.assertIsNone(payload["failure_reason"])
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["file_path"], self.path)
        self.assertEqual(payload["file_name"], "rec.mkv")
        self.assertEqual(payload["file_size"], 32)
        self.assertTrue(payload["remux_success"])
        self.assertEqual(payload["bytes_written"], 1234)
        self.assertEqual(payload["file_url"], "/api/channels/recordings/7/file/")
        self.assertIsNone(payload["interrupted_reason"])

    def test_interrupted_with_a_file_still_succeeds(self):
        cp = {"status": "interrupted", "interrupted_reason": "stream_lost"}
        payload = _dvr_recording_end_payload(cp, self.path, True)
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["interrupted_reason"], "stream_lost")

    def test_failed_remux_is_a_failure_with_reason(self):
        cp = {"status": "interrupted", "bytes_written": 0}
        payload = _dvr_recording_end_payload(cp, self.path, False)
        self.assertEqual(payload["outcome"], "failed")
        self.assertFalse(payload["has_file"])
        self.assertEqual(payload["failure_reason"], "remux_failed")

    def test_missing_file_is_a_failure_even_if_remux_claimed_success(self):
        missing = os.path.join(self.tmp.name, "gone.mkv")
        payload = _dvr_recording_end_payload({"status": "completed"}, missing, True)
        self.assertEqual(payload["outcome"], "failed")
        self.assertEqual(payload["failure_reason"], "missing_file")
        self.assertIsNone(payload["file_size"])

    def test_empty_file_is_a_failure(self):
        empty = os.path.join(self.tmp.name, "empty.mkv")
        open(empty, "wb").close()
        payload = _dvr_recording_end_payload({"status": "completed"}, empty, True)
        self.assertEqual(payload["outcome"], "failed")
        self.assertEqual(payload["failure_reason"], "empty_file")

    def test_malformed_inputs_never_raise(self):
        for cp in (None, [], "x", 5, {"status": None, "bytes_written": "12"}):
            for path in (None, "", 3, self.path):
                payload = _dvr_recording_end_payload(cp, path, remux_success="yes")
                self.assertIn(payload["status"], ("unknown",))
                self.assertIsNone(payload["bytes_written"])
                self.assertIsNone(payload["interrupted_reason"])
                self.assertIs(payload["remux_success"], True)

    def test_bool_bytes_written_is_rejected(self):
        payload = _dvr_recording_end_payload({"bytes_written": True}, self.path, True)
        self.assertIsNone(payload["bytes_written"])

    def test_file_name_falls_back_to_basename_of_final_path(self):
        payload = _dvr_recording_end_payload({"status": "completed"}, self.path, True)
        self.assertEqual(payload["file_name"], "rec.mkv")

    def test_payload_is_json_serialisable(self):
        import json

        payload = _dvr_recording_end_payload({"status": "completed"}, self.path, True)
        json.dumps(payload)

    def test_start_and_end_time_pass_through_when_given(self):
        payload = _dvr_recording_end_payload(
            {"status": "completed"}, self.path, True,
            start_time="2026-09-15T04:00:00+08:00", end_time="2026-09-15T04:30:00+08:00",
        )
        self.assertEqual(payload["start_time"], "2026-09-15T04:00:00+08:00")
        self.assertEqual(payload["end_time"], "2026-09-15T04:30:00+08:00")

    def test_start_and_end_time_default_to_none(self):
        payload = _dvr_recording_end_payload({"status": "completed"}, self.path, True)
        self.assertIsNone(payload["start_time"])
        self.assertIsNone(payload["end_time"])


class DvrRecordingEndCancelPayloadTests(SimpleTestCase):
    def test_cancel_reports_cancelled_not_failed(self):
        payload = _dvr_recording_end_payload(
            {"status": "recording", "bytes_written": 99}, "/data/recordings/x.mkv", True,
            cancelled=True, cancelled_by="admin", cancelled_by_id=3,
        )
        self.assertEqual(payload["outcome"], "cancelled")
        self.assertEqual(payload["status"], "cancelled")
        self.assertFalse(payload["has_file"])
        self.assertIsNone(payload["failure_reason"])
        self.assertIsNone(payload["file_path"])
        self.assertEqual(payload["cancelled_by"], "admin")
        self.assertEqual(payload["cancelled_by_id"], 3)

    def test_cancel_rejects_malformed_user_fields(self):
        payload = _dvr_recording_end_payload(
            {}, None, False, cancelled=True, cancelled_by=5, cancelled_by_id=True,
        )
        self.assertIsNone(payload["cancelled_by"])
        self.assertIsNone(payload["cancelled_by_id"])

    def test_datetimes_are_serialised_to_iso(self):
        from datetime import datetime, timezone

        start = datetime(2026, 9, 15, 4, 0, tzinfo=timezone.utc)
        payload = _dvr_recording_end_payload({}, None, False, start_time=start, end_time=None)
        self.assertEqual(payload["start_time"], "2026-09-15T04:00:00+00:00")
        self.assertIsNone(payload["end_time"])


class DvrEmitRecordingEndTests(SimpleTestCase):
    """The resume path dispatches run_recording with start = now; the event
    must still report the Recording's own scheduled window."""

    def test_uses_recording_times_over_task_arguments(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from unittest import mock

        from apps.channels.tasks import _dvr_emit_recording_end

        scheduled_start = datetime(2026, 9, 15, 4, 0, tzinfo=timezone.utc)
        scheduled_end = datetime(2026, 9, 15, 4, 30, tzinfo=timezone.utc)
        resumed_now = datetime(2026, 9, 15, 4, 17, tzinfo=timezone.utc)
        rec = SimpleNamespace(id=7, start_time=scheduled_start, end_time=scheduled_end)
        channel = SimpleNamespace(uuid="c-uuid", name="Ten")

        with mock.patch("core.utils.log_system_event") as emit:
            _dvr_emit_recording_end(
                rec, channel, {"status": "completed"}, None, False,
                fallback_start=resumed_now, fallback_end=scheduled_end,
            )

        emit.assert_called_once()
        args, kwargs = emit.call_args
        self.assertEqual(args[0], "recording_end")
        self.assertEqual(kwargs["recording_id"], 7)
        self.assertEqual(kwargs["start_time"], scheduled_start.isoformat())
        self.assertEqual(kwargs["end_time"], scheduled_end.isoformat())

    def test_never_raises_when_the_emit_fails(self):
        from types import SimpleNamespace
        from unittest import mock

        from apps.channels.tasks import _dvr_emit_recording_end

        with mock.patch("core.utils.log_system_event", side_effect=RuntimeError("boom")):
            _dvr_emit_recording_end(SimpleNamespace(id=1), None, {}, None, False)


class DvrCancelEmitsRecordingEndTests(SimpleTestCase):
    """Deleting an in-progress recording closes the recording_start pair."""

    def _destroy(self, status, **extra_cp):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from unittest import mock

        from apps.channels.api_views import RecordingViewSet

        cp = {"status": status, "file_path": None, "_hls_dir": None}
        cp.update(extra_cp)
        instance = SimpleNamespace(
            pk=11,
            start_time=datetime(2026, 9, 15, 4, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 15, 4, 30, tzinfo=timezone.utc),
            channel=SimpleNamespace(uuid="c-uuid", name="Ten"),
            custom_properties=cp,
        )
        view = RecordingViewSet()
        request = SimpleNamespace(user=SimpleNamespace(username="admin", pk=3))
        with mock.patch.object(RecordingViewSet, "get_object", return_value=instance), \
                mock.patch("rest_framework.viewsets.ModelViewSet.destroy", return_value="deleted"), \
                mock.patch("core.utils.RedisClient.get_client", return_value=None), \
                mock.patch("core.utils.send_websocket_update"), \
                mock.patch("core.utils.log_system_event") as emit, \
                mock.patch("threading.Thread"):
            view.destroy(request)
        return emit

    def test_cancel_emits_cancelled_with_cancelled_by(self):
        emit = self._destroy("recording")
        emit.assert_called_once()
        args, kwargs = emit.call_args
        self.assertEqual(args[0], "recording_end")
        self.assertEqual(kwargs["recording_id"], 11)
        self.assertEqual(kwargs["outcome"], "cancelled")
        self.assertEqual(kwargs["status"], "cancelled")
        self.assertFalse(kwargs["has_file"])
        self.assertIsNone(kwargs["failure_reason"])
        self.assertEqual(kwargs["cancelled_by"], "admin")
        self.assertEqual(kwargs["cancelled_by_id"], 3)
        self.assertEqual(kwargs["start_time"], "2026-09-15T04:00:00+00:00")

    def test_delete_after_stop_before_finalize_emits_cancelled(self):
        """Stop writes status=stopped immediately; remux_success comes later."""
        emit = self._destroy("stopped")
        emit.assert_called_once()
        kwargs = emit.call_args.kwargs
        self.assertEqual(kwargs["outcome"], "cancelled")
        self.assertEqual(kwargs["cancelled_by"], "admin")

    def test_deleting_a_finished_recording_emits_nothing(self):
        emit = self._destroy("completed")
        emit.assert_not_called()

    def test_deleting_a_finalized_stopped_recording_emits_nothing(self):
        emit = self._destroy("stopped", remux_success=True)
        emit.assert_not_called()
