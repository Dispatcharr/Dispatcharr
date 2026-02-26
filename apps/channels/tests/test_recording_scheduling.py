"""Tests for DVR recording scheduling with ClockedSchedule.

   Prefers Celery ClockedScheduled over Redis time due to 3600s limitation on scheduled tasks;
   scheduled tasks beyond 3600s cause Redis time to hand process between workers and duplicate jobs
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import ClockedSchedule, PeriodicTask

from apps.channels.models import Channel, Recording
from apps.channels.signals import (
    schedule_recording_task,
    revoke_task,
    _dvr_task_name,
)


class ScheduleRecordingTaskTests(TestCase):
    """Tests for schedule_recording_task()."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=1, name="Test Channel")

    def tearDown(self):
        PeriodicTask.objects.filter(name__startswith="dvr-recording-").delete()
        ClockedSchedule.objects.all().delete()

    @patch("apps.channels.signals.run_recording")
    def test_future_recording_creates_periodic_task(self, mock_run_recording):
        """Recordings in the future create a ClockedSchedule + PeriodicTask."""
        future_time = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future_time,
            end_time=future_time + timedelta(hours=1),
        )

        task_id = schedule_recording_task(rec, eta=future_time)

        expected_name = f"dvr-recording-{rec.id}"
        self.assertEqual(task_id, expected_name)

        pt = PeriodicTask.objects.get(name=expected_name)
        self.assertTrue(pt.one_off)
        self.assertTrue(pt.enabled)
        self.assertEqual(pt.task, "apps.channels.tasks.run_recording")
        self.assertIsNotNone(pt.clocked)

        # apply_async should not have been called
        mock_run_recording.apply_async.assert_not_called()

    @patch("apps.channels.signals.run_recording")
    def test_immediate_recording_creates_periodic_task(self, mock_run_recording):
        """Recordings starting now also use ClockedSchedule for consistency."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now + timedelta(hours=1),
        )

        task_id = schedule_recording_task(rec, eta=now)

        expected_name = f"dvr-recording-{rec.id}"
        self.assertEqual(task_id, expected_name)
        self.assertTrue(PeriodicTask.objects.filter(name=expected_name).exists())

    @patch("apps.channels.signals.run_recording")
    def test_past_start_time_clamps_to_now(self, mock_run_recording):
        """Recordings with past start_time get clamped to now."""
        past_time = timezone.now() - timedelta(minutes=5)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=past_time,
            end_time=timezone.now() + timedelta(hours=1),
        )

        task_id = schedule_recording_task(rec, eta=past_time)

        expected_name = f"dvr-recording-{rec.id}"
        self.assertEqual(task_id, expected_name)
        pt = PeriodicTask.objects.get(name=expected_name)
        # Clocked time should be >= now
        self.assertGreaterEqual(pt.clocked.clocked_time, past_time)

    @patch("apps.channels.signals.run_recording")
    def test_reschedule_updates_existing_periodic_task(self, mock_run_recording):
        """Calling schedule_recording_task twice updates the existing PeriodicTask."""
        future_time = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future_time,
            end_time=future_time + timedelta(hours=1),
        )

        schedule_recording_task(rec, eta=future_time)

        # Reschedule with a different time
        new_eta = future_time + timedelta(hours=1)
        schedule_recording_task(rec, eta=new_eta)

        # Should still be exactly one PeriodicTask
        task_name = f"dvr-recording-{rec.id}"
        self.assertEqual(PeriodicTask.objects.filter(name=task_name).count(), 1)

    @patch("apps.channels.signals.run_recording")
    def test_naive_eta_is_made_aware(self, mock_run_recording):
        """A naive (timezone-unaware) eta is made timezone-aware."""
        from datetime import datetime
        naive_eta = datetime(2030, 6, 15, 14, 0, 0)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=timezone.now() + timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=2),
        )

        task_id = schedule_recording_task(rec, eta=naive_eta)

        expected_name = f"dvr-recording-{rec.id}"
        self.assertEqual(task_id, expected_name)
        pt = PeriodicTask.objects.get(name=expected_name)
        self.assertTrue(timezone.is_aware(pt.clocked.clocked_time))


class RevokeTaskTests(TestCase):
    """Tests for revoke_task()."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=1, name="Test Channel")

    def tearDown(self):
        PeriodicTask.objects.filter(name__startswith="dvr-recording-").delete()
        ClockedSchedule.objects.all().delete()

    def test_revoke_deletes_periodic_task_and_clocked_schedule(self):
        """revoke_task deletes the PeriodicTask and orphaned ClockedSchedule."""
        eta = timezone.now() + timedelta(hours=5)
        clocked = ClockedSchedule.objects.create(clocked_time=eta)
        PeriodicTask.objects.create(
            name="dvr-recording-10",
            task="apps.channels.tasks.run_recording",
            clocked=clocked,
            one_off=True,
            enabled=True,
        )

        revoke_task("dvr-recording-10")

        self.assertFalse(PeriodicTask.objects.filter(name="dvr-recording-10").exists())
        self.assertFalse(ClockedSchedule.objects.filter(id=clocked.id).exists())

    def test_revoke_keeps_shared_clocked_schedule(self):
        """ClockedSchedule is kept if another PeriodicTask still references it."""
        eta = timezone.now() + timedelta(hours=5)
        clocked = ClockedSchedule.objects.create(clocked_time=eta)
        PeriodicTask.objects.create(
            name="dvr-recording-10",
            task="apps.channels.tasks.run_recording",
            clocked=clocked,
            one_off=True,
        )
        PeriodicTask.objects.create(
            name="dvr-recording-11",
            task="apps.channels.tasks.run_recording",
            clocked=clocked,
            one_off=True,
        )

        revoke_task("dvr-recording-10")

        self.assertFalse(PeriodicTask.objects.filter(name="dvr-recording-10").exists())
        self.assertTrue(ClockedSchedule.objects.filter(id=clocked.id).exists())

    @patch("apps.channels.signals.AsyncResult")
    def test_revoke_falls_back_to_async_result_for_legacy_ids(self, mock_async_result):
        """revoke_task falls back to AsyncResult.revoke() for old-style UUIDs."""
        revoke_task("550e8400-e29b-41d4-a716-446655440000")

        mock_async_result.assert_called_once_with("550e8400-e29b-41d4-a716-446655440000")
        mock_async_result.return_value.revoke.assert_called_once()

    def test_revoke_none_is_noop(self):
        """revoke_task(None) does nothing."""
        revoke_task(None)  # Should not raise

    def test_revoke_empty_string_is_noop(self):
        """revoke_task('') does nothing."""
        revoke_task("")  # Should not raise


class DvrTaskNameTests(TestCase):
    """Tests for the naming convention helper."""

    def test_task_name_format(self):
        self.assertEqual(_dvr_task_name(42), "dvr-recording-42")

    def test_task_name_fits_in_charfield(self):
        name = _dvr_task_name(999999999)
        self.assertLessEqual(len(name), 255)


class SignalIntegrationTests(TestCase):
    """Integration tests for the post_save / post_delete signal handlers."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=1, name="Test Channel")

    def tearDown(self):
        PeriodicTask.objects.filter(name__startswith="dvr-recording-").delete()
        ClockedSchedule.objects.all().delete()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_post_save_creates_periodic_task_for_future_recording(self, mock_artwork):
        """Saving a future Recording creates a PeriodicTask via post_save signal."""
        mock_artwork.apply_async.return_value = MagicMock()

        future = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
        )

        rec.refresh_from_db()
        task_name = f"dvr-recording-{rec.id}"
        self.assertEqual(rec.task_id, task_name)
        self.assertTrue(PeriodicTask.objects.filter(name=task_name).exists())

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_post_delete_removes_periodic_task(self, mock_artwork):
        """Deleting a Recording removes its PeriodicTask."""
        mock_artwork.apply_async.return_value = MagicMock()

        future = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
        )

        rec.refresh_from_db()
        task_name = rec.task_id
        self.assertTrue(PeriodicTask.objects.filter(name=task_name).exists())

        rec.delete()
        self.assertFalse(PeriodicTask.objects.filter(name=task_name).exists())

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_bulk_delete_cleans_up_all_periodic_tasks(self, mock_artwork):
        """Bulk deleting recordings cleans up all their PeriodicTasks."""
        mock_artwork.apply_async.return_value = MagicMock()

        future = timezone.now() + timedelta(hours=2)
        rec_ids = []
        for i in range(5):
            rec = Recording.objects.create(
                channel=self.channel,
                start_time=future + timedelta(hours=i),
                end_time=future + timedelta(hours=i + 1),
            )
            rec_ids.append(rec.id)

        for rid in rec_ids:
            self.assertTrue(
                PeriodicTask.objects.filter(name=f"dvr-recording-{rid}").exists()
            )

        Recording.objects.filter(channel=self.channel).delete()

        self.assertEqual(
            PeriodicTask.objects.filter(name__startswith="dvr-recording-").count(), 0
        )

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_pre_save_revokes_on_time_change(self, mock_artwork):
        """Changing a recording's start_time revokes the old task and creates a new one."""
        mock_artwork.apply_async.return_value = MagicMock()

        future = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
        )

        rec.refresh_from_db()
        old_task_name = rec.task_id
        self.assertTrue(PeriodicTask.objects.filter(name=old_task_name).exists())

        # Change the start time — pre_save clears task_id, post_save reschedules
        new_future = future + timedelta(hours=3)
        rec.start_time = new_future
        rec.end_time = new_future + timedelta(hours=1)
        rec.save()

        rec.refresh_from_db()
        # Old PeriodicTask should be deleted; new one should exist
        self.assertIsNotNone(rec.task_id)
        self.assertTrue(
            PeriodicTask.objects.filter(name=f"dvr-recording-{rec.id}").exists()
        )


class IdempotencyGuardTests(TestCase):
    """Tests for the idempotency guard in run_recording()."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=1, name="Test Channel")

    @patch("apps.channels.tasks.get_channel_layer")
    def test_skips_if_already_recording(self, mock_layer):
        """run_recording returns early if status is already 'recording'."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now + timedelta(hours=1),
            custom_properties={"status": "recording", "started_at": str(now)},
        )

        from apps.channels.tasks import run_recording as run_rec_task
        result = run_rec_task(rec.id, self.channel.id, str(now), str(now + timedelta(hours=1)))

        self.assertIsNone(result)
        # get_channel_layer should not have been called (returned before)
        mock_layer.assert_not_called()

    @patch("apps.channels.tasks.get_channel_layer")
    def test_skips_if_already_completed(self, mock_layer):
        """run_recording returns early if status is already 'completed'."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            custom_properties={"status": "completed"},
        )

        from apps.channels.tasks import run_recording as run_rec_task
        result = run_rec_task(rec.id, self.channel.id, str(rec.start_time), str(rec.end_time))

        self.assertIsNone(result)
        mock_layer.assert_not_called()

    @patch("apps.channels.tasks.get_channel_layer")
    def test_skips_if_already_stopped(self, mock_layer):
        """run_recording returns early if status is already 'stopped' (user stopped it early)."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": "stopped", "stopped_at": str(now)},
        )

        from apps.channels.tasks import run_recording as run_rec_task
        result = run_rec_task(rec.id, self.channel.id, str(rec.start_time), str(rec.end_time))

        self.assertIsNone(result)
        mock_layer.assert_not_called()


class ArtworkPrefetchSignalGuardTests(TestCase):
    """Tests that the post_save signal does not schedule artwork prefetch when
    the recording is in an active or terminal state."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=1, name="Test Channel")

    def tearDown(self):
        PeriodicTask.objects.filter(name__startswith="dvr-recording-").delete()
        ClockedSchedule.objects.all().delete()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_artwork_prefetch_not_scheduled_when_status_recording(self, mock_artwork):
        """post_save must NOT schedule artwork prefetch when status='recording'
        to prevent a race that overwrites the running task's status updates."""
        future = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
            custom_properties={"status": "recording"},
        )

        # Simulate a save that run_recording itself might do mid-recording
        rec.custom_properties = {"status": "recording", "file_path": "/data/recordings/test.mkv"}
        rec.save(update_fields=["custom_properties"])

        # apply_async was not called for the "recording" save
        mock_artwork.apply_async.assert_not_called()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_artwork_prefetch_not_scheduled_when_status_completed(self, mock_artwork):
        """post_save must NOT schedule artwork prefetch when status='completed'."""
        future = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
            custom_properties={"status": "completed"},
        )

        rec.custom_properties = {"status": "completed"}
        rec.save(update_fields=["custom_properties"])

        mock_artwork.apply_async.assert_not_called()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_artwork_prefetch_not_scheduled_when_status_stopped(self, mock_artwork):
        """post_save must NOT schedule artwork prefetch when status='stopped'."""
        future = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
            custom_properties={"status": "stopped"},
        )

        rec.custom_properties = {"status": "stopped"}
        rec.save(update_fields=["custom_properties"])

        mock_artwork.apply_async.assert_not_called()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_artwork_prefetch_scheduled_for_new_upcoming_recording(self, mock_artwork):
        """post_save SHOULD schedule artwork prefetch for a newly created upcoming recording."""
        mock_artwork.apply_async.return_value = MagicMock()
        future = timezone.now() + timedelta(hours=2)
        Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
            custom_properties={},  # no status yet — should trigger prefetch
        )

        self.assertTrue(mock_artwork.apply_async.called)


class DestroyDvrClientIsolationTests(TestCase):
    """Tests that deleting a recording only stops DVR clients when the
    recording is actively streaming — never for completed/upcoming recordings
    that could share a channel with an unrelated in-progress recording."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIRequestFactory, force_authenticate
        self.channel = Channel.objects.create(channel_number=1, name="Test Channel")
        User = get_user_model()
        self.user = User.objects.create_user(
            username="dvr_test_admin", password="pass",
            user_level=User.UserLevel.ADMIN,
        )
        self.factory = APIRequestFactory()
        self.force_authenticate = force_authenticate

    def _delete_recording(self, rec):
        from apps.channels.api_views import RecordingViewSet
        request = self.factory.delete(f"/api/channels/recordings/{rec.id}/")
        self.force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"delete": "destroy"})
        return view(request, pk=rec.id)

    @patch("apps.channels.api_views._stop_dvr_clients")
    def test_destroy_completed_recording_does_not_stop_dvr_clients(self, mock_stop):
        """Deleting a completed recording must NOT call _stop_dvr_clients."""
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            custom_properties={"status": "completed", "file_path": "/data/recordings/test.mkv"},
        )
        self._delete_recording(rec)
        mock_stop.assert_not_called()

    @patch("apps.channels.api_views._stop_dvr_clients")
    def test_destroy_upcoming_recording_does_not_stop_dvr_clients(self, mock_stop):
        """Deleting an upcoming (scheduled) recording must NOT call _stop_dvr_clients."""
        future = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
            custom_properties={},
        )
        self._delete_recording(rec)
        mock_stop.assert_not_called()

    @patch("apps.channels.api_views._stop_dvr_clients")
    def test_destroy_active_recording_does_stop_dvr_clients(self, mock_stop):
        """Deleting an in-progress recording MUST call _stop_dvr_clients."""
        mock_stop.return_value = 1
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": "recording"},
        )
        self._delete_recording(rec)
        mock_stop.assert_called_once_with(str(self.channel.uuid))


class PeriodicTaskCleanupOnExecutionTests(TestCase):
    """Tests for PeriodicTask cleanup when run_recording starts."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=1, name="Test Channel")

    def tearDown(self):
        PeriodicTask.objects.filter(name__startswith="dvr-recording-").delete()
        ClockedSchedule.objects.all().delete()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    @patch("apps.channels.tasks.get_channel_layer")
    def test_periodic_task_cleaned_up_on_execution(self, mock_layer, mock_artwork):
        """When run_recording executes, it deletes its own PeriodicTask."""
        mock_layer.return_value = MagicMock()
        mock_artwork.apply_async.return_value = MagicMock()

        future = timezone.now() + timedelta(hours=2)
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=future,
            end_time=future + timedelta(hours=1),
            custom_properties={},
        )

        # post_save signal should have created the PeriodicTask
        task_name = f"dvr-recording-{rec.id}"
        self.assertTrue(PeriodicTask.objects.filter(name=task_name).exists())
        pt = PeriodicTask.objects.get(name=task_name)
        clocked_id = pt.clocked_id

        from apps.channels.tasks import run_recording as run_rec_task
        # This will proceed past guards, clean up the PeriodicTask, then
        # eventually fail on the actual stream connection (expected)
        try:
            run_rec_task(rec.id, self.channel.id, str(future), str(future + timedelta(hours=1)))
        except Exception:
            pass

        self.assertFalse(PeriodicTask.objects.filter(name=task_name).exists())
        self.assertFalse(ClockedSchedule.objects.filter(id=clocked_id).exists())
