"""Tests for the Extend In-Progress Recording feature.

Covers:
  - extend() API endpoint (happy path and validation)
  - pre_save signal guard: end_time change must NOT revoke a live recording
  - pre_save signal guard: end_time change MUST still revoke an upcoming recording
  - TOCTOU edge cases (extend on a completed/stopped/nonexistent recording)
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.channels.models import Channel, Recording
from apps.channels.api_views import RecordingViewSet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u, _ = User.objects.get_or_create(
        username="extend_test_admin",
        defaults={"user_level": User.UserLevel.ADMIN},
    )
    u.set_password("pass")
    u.save()
    return u


# ---------------------------------------------------------------------------
# Extend endpoint tests
# ---------------------------------------------------------------------------

class ExtendEndpointTests(TestCase):
    """Tests for POST /api/channels/recordings/{id}/extend/"""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=88, name="Extend Test Channel"
        )
        self.user = _make_admin()
        self.factory = APIRequestFactory()

    def _extend(self, rec, extra_minutes):
        request = self.factory.post(
            f"/api/channels/recordings/{rec.id}/extend/",
            {"extra_minutes": extra_minutes},
            format="json",
        )
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "extend"})
        return view(request, pk=rec.id)

    def _make_rec(self, status="recording"):
        now = timezone.now()
        return Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": status},
        )

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_extend_updates_end_time_in_db(self, _ws):
        rec = self._make_rec()
        original_end = rec.end_time
        response = self._extend(rec, 30)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))
        rec.refresh_from_db()
        expected = original_end + timedelta(minutes=30)
        delta = abs((rec.end_time - expected).total_seconds())
        self.assertLess(delta, 1, "end_time was not extended by the correct amount")

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_extend_stacks_multiple_extensions(self, _ws):
        """Calling extend() twice adds both increments."""
        rec = self._make_rec()
        original_end = rec.end_time
        self._extend(rec, 15)
        self._extend(rec, 30)
        rec.refresh_from_db()
        expected = original_end + timedelta(minutes=45)
        delta = abs((rec.end_time - expected).total_seconds())
        self.assertLess(delta, 1)

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_extend_does_not_clear_task_id(self, _ws):
        """The running Celery task must survive the DB save."""
        rec = self._make_rec()
        rec.task_id = "dvr-recording-999"
        rec.save(update_fields=["task_id"])
        self._extend(rec, 30)
        rec.refresh_from_db()
        self.assertEqual(rec.task_id, "dvr-recording-999")

    def test_extend_returns_400_if_finished(self):
        """Cannot extend a completed, stopped, or interrupted recording."""
        for bad_status in ("completed", "stopped", "interrupted"):
            with self.subTest(status=bad_status):
                rec = self._make_rec(status=bad_status)
                response = self._extend(rec, 30)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.data.get("success"))

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_extend_succeeds_before_task_sets_status(self, _ws):
        """Extend must work when status is empty (task hasn't started yet)."""
        rec = self._make_rec(status="")
        response = self._extend(rec, 15)
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        expected = rec.end_time  # already extended
        self.assertTrue(response.data.get("success"))

    @patch("apps.channels.signals.revoke_task")
    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_extend_bypasses_signals_no_revoke(self, _ws, mock_revoke):
        """Extend uses .update() to bypass pre_save — revoke_task must never fire."""
        rec = self._make_rec(status="")
        rec.task_id = "dvr-recording-500"
        rec.save(update_fields=["task_id"])
        self._extend(rec, 15)
        self._extend(rec, 30)
        mock_revoke.assert_not_called()
        rec.refresh_from_db()
        self.assertEqual(rec.task_id, "dvr-recording-500")

    def test_extend_returns_400_for_zero_minutes(self):
        response = self._extend(self._make_rec(), 0)
        self.assertEqual(response.status_code, 400)

    def test_extend_returns_400_for_negative_minutes(self):
        response = self._extend(self._make_rec(), -15)
        self.assertEqual(response.status_code, 400)

    def test_extend_returns_400_for_non_numeric_minutes(self):
        rec = self._make_rec()
        request = self.factory.post(
            f"/api/channels/recordings/{rec.id}/extend/",
            {"extra_minutes": "lots"},
            format="json",
        )
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "extend"})
        response = view(request, pk=rec.id)
        self.assertEqual(response.status_code, 400)

    def test_extend_returns_404_for_nonexistent_recording(self):
        request = self.factory.post(
            "/api/channels/recordings/999999/extend/",
            {"extra_minutes": 30},
            format="json",
        )
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "extend"})
        response = view(request, pk=999999)
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# pre_save signal guard tests
# ---------------------------------------------------------------------------

class PreSaveExtendGuardTests(TestCase):
    """The pre_save signal must NOT revoke a live recording when end_time changes,
    but MUST still revoke a scheduled (upcoming) recording as before."""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=77, name="Signal Guard Channel"
        )

    def _make_rec(self, status="", task_id="dvr-recording-42"):
        now = timezone.now()
        return Recording.objects.create(
            channel=self.channel,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            task_id=task_id,
            custom_properties={"status": status} if status else {},
        )

    @patch("apps.channels.signals.revoke_task")
    def test_end_time_change_does_not_revoke_live_recording(self, mock_revoke):
        """When status='recording', extending end_time must not call revoke_task."""
        rec = self._make_rec(status="recording", task_id="dvr-recording-42")
        rec.end_time = rec.end_time + timedelta(minutes=30)
        rec.save(update_fields=["end_time"])
        mock_revoke.assert_not_called()

    @patch("apps.channels.signals.revoke_task")
    def test_task_id_preserved_after_extend_on_live_recording(self, mock_revoke):
        """task_id must not be cleared for a live recording's end_time change."""
        rec = self._make_rec(status="recording", task_id="dvr-recording-42")
        original_task_id = rec.task_id
        rec.end_time = rec.end_time + timedelta(minutes=30)
        rec.save(update_fields=["end_time"])
        rec.refresh_from_db()
        self.assertEqual(rec.task_id, original_task_id)

    @patch("apps.channels.signals.revoke_task")
    def test_end_time_change_still_revokes_upcoming_recording(self, mock_revoke):
        """The guard must NOT apply to upcoming recordings — existing behavior preserved."""
        rec = self._make_rec(status="", task_id="dvr-recording-77")
        rec.end_time = rec.end_time + timedelta(minutes=30)
        rec.save(update_fields=["end_time"])
        mock_revoke.assert_called_once_with("dvr-recording-77")

    @patch("apps.channels.signals.revoke_task")
    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_pre_save_guard_reads_db_status_not_memory_status(self, _ws, mock_revoke):
        """pre_save reads status from DB (old object), not from the instance being saved."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            task_id="dvr-recording-66",
            custom_properties={"status": "recording"},
        )
        # Simulate: DB status changes to 'completed' behind the instance's back
        Recording.objects.filter(pk=rec.pk).update(
            custom_properties={"status": "completed"}
        )
        rec.end_time = rec.end_time + timedelta(minutes=30)
        rec.save(update_fields=["end_time"])
        # revoke_task should be called because DB status is "completed", not "recording"
        mock_revoke.assert_called_once_with("dvr-recording-66")
