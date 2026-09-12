import os
import tempfile

from django.test import SimpleTestCase

from apps.channels.tasks import _dvr_finalized_events
from apps.connect.models import SUPPORTED_EVENTS
from core.models import SystemEvent


def _names(events):
    return [name for name, _ in events]


class DvrFinalizedEventsTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "rec.mkv")
        with open(self.path, "wb") as f:
            f.write(b"\x1a\x45\xdf\xa3" * 8)

    def tearDown(self):
        self.tmp.cleanup()

    def test_completed_recording_is_finalized_only(self):
        cp = {
            "status": "completed",
            "bytes_written": 1234,
            "file_url": "/api/channels/recordings/7/file/",
        }
        events = _dvr_finalized_events(cp, self.path, True)
        self.assertEqual(_names(events), ["recording_finalized"])
        payload = events[0][1]
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["file_path"], self.path)
        self.assertEqual(payload["file_size"], 32)
        self.assertTrue(payload["has_file"])
        self.assertTrue(payload["remux_success"])
        self.assertEqual(payload["bytes_written"], 1234)
        self.assertEqual(payload["file_url"], "/api/channels/recordings/7/file/")
        self.assertIsNone(payload["interrupted_reason"])

    def test_interrupted_with_a_file_is_finalized_not_failed(self):
        cp = {"status": "interrupted", "interrupted_reason": "stream_lost"}
        events = _dvr_finalized_events(cp, self.path, True)
        self.assertEqual(_names(events), ["recording_finalized"])
        self.assertEqual(events[0][1]["interrupted_reason"], "stream_lost")

    def test_failed_remux_adds_recording_failed(self):
        cp = {"status": "interrupted", "bytes_written": 0}
        events = _dvr_finalized_events(cp, self.path, False)
        self.assertEqual(_names(events), ["recording_finalized", "recording_failed"])
        self.assertIs(events[0][1], events[1][1])
        self.assertFalse(events[0][1]["has_file"])

    def test_missing_file_adds_recording_failed_even_if_remux_claimed_success(self):
        missing = os.path.join(self.tmp.name, "gone.mkv")
        events = _dvr_finalized_events({"status": "completed"}, missing, True)
        self.assertEqual(_names(events), ["recording_finalized", "recording_failed"])
        self.assertIsNone(events[0][1]["file_size"])

    def test_empty_file_counts_as_no_file(self):
        empty = os.path.join(self.tmp.name, "empty.mkv")
        open(empty, "wb").close()
        events = _dvr_finalized_events({"status": "completed"}, empty, True)
        self.assertIn("recording_failed", _names(events))

    def test_malformed_inputs_never_raise(self):
        for cp in (None, [], "x", 5, {"status": None, "bytes_written": "12"}):
            for path in (None, "", 3, self.path):
                events = _dvr_finalized_events(cp, path, remux_success="yes")
                self.assertEqual(events[0][0], "recording_finalized")
                payload = events[0][1]
                self.assertIn(payload["status"], ("unknown",))
                self.assertIsNone(payload["bytes_written"])
                self.assertIsNone(payload["interrupted_reason"])
                self.assertIs(payload["remux_success"], True)

    def test_bool_bytes_written_is_rejected(self):
        events = _dvr_finalized_events({"bytes_written": True}, self.path, True)
        self.assertIsNone(events[0][1]["bytes_written"])

    def test_payload_is_json_serialisable(self):
        import json

        events = _dvr_finalized_events({"status": "completed"}, self.path, True)
        json.dumps(events[0][1])

    def test_events_are_registered_for_subscriptions_and_the_event_log(self):
        types = {key for key, _ in SystemEvent.EVENT_TYPES}
        for name in ("recording_finalized", "recording_failed"):
            self.assertIn(name, SUPPORTED_EVENTS)
            self.assertIn(name, types)

