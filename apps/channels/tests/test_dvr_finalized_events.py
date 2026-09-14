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
