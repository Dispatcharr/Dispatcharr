"""Tests for the DVR Stop/Cancel feature set.

Covers:
  - stop() endpoint
  - destroy() was_in_progress field in recording_cancelled WebSocket event
  - signals.py update_fields re-entrancy guard
  - run_recording race guard before status write
  - _stop_dvr_clients() DVR client isolation
"""
from datetime import timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.channels.models import Channel, Recording
from apps.channels.api_views import RecordingViewSet, _stop_dvr_clients


def _make_admin():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u, _ = User.objects.get_or_create(
        username="stop_test_admin",
        defaults={"user_level": User.UserLevel.ADMIN},
    )
    u.set_password("pass")
    u.save()
    return u


def _async_channel_layer_mock():
    layer = MagicMock()
    layer.group_send = AsyncMock()
    return layer


class StopEndpointTests(TestCase):
    """Tests for POST /api/channels/recordings/{id}/stop/"""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=99, name="Stop Test Channel")
        self.user = _make_admin()
        self.factory = APIRequestFactory()

    def _stop(self, rec):
        request = self.factory.post(f"/api/channels/recordings/{rec.id}/stop/")
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "stop"})
        return view(request, pk=rec.id)

    def _make_rec(self, status="recording"):
        now = timezone.now()
        return Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": status},
        )

    @patch("core.utils.send_websocket_update")
    @patch("threading.Thread")
    def test_stop_writes_status_to_db_before_returning(self, mock_thread, mock_ws):
        """DB write is synchronous — run_recording polls for this."""
        mock_thread.return_value.start = MagicMock()
        rec = self._make_rec()
        response = self._stop(rec)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))
        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties.get("status"), "stopped")

    @patch("core.utils.send_websocket_update")
    @patch("threading.Thread")
    def test_stop_writes_stopped_at_timestamp(self, mock_thread, mock_ws):
        mock_thread.return_value.start = MagicMock()
        rec = self._make_rec()
        self._stop(rec)
        rec.refresh_from_db()
        self.assertIn("stopped_at", rec.custom_properties)

    def test_stop_calls_stop_dvr_clients_in_background(self):
        """stop() spawns a background thread whose target calls _stop_dvr_clients."""
        rec = self._make_rec()

        with patch("apps.channels.api_views._stop_dvr_clients", return_value=1) as mock_stop, \
             patch("core.utils.send_websocket_update"), \
             patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            self._stop(rec)

        # Verify a daemon thread was spawned
        mock_thread.assert_called_once()
        thread_kwargs = mock_thread.call_args[1]
        self.assertTrue(thread_kwargs.get("daemon"), "Thread must be daemon")

        # Execute the captured target with DB connection close patched out
        target = thread_kwargs["target"]
        with patch("apps.channels.api_views._stop_dvr_clients", return_value=1) as mock_stop2, \
             patch("apps.channels.signals.revoke_task", side_effect=Exception("skip")), \
             patch("django.db.connection") as mock_conn:
            target()

        self.assertTrue(mock_stop2.called)
        args, kwargs = mock_stop2.call_args
        actual_rec_id = kwargs.get("recording_id") or (args[1] if len(args) > 1 else None)
        self.assertEqual(actual_rec_id, rec.id)

    def test_stop_returns_404_for_nonexistent(self):
        request = self.factory.post("/api/channels/recordings/99999/stop/")
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "stop"})
        self.assertEqual(view(request, pk=99999).status_code, 404)

    @patch("core.utils.send_websocket_update")
    @patch("threading.Thread")
    def test_stop_idempotent_on_already_stopped(self, mock_thread, mock_ws):
        mock_thread.return_value.start = MagicMock()
        rec = self._make_rec(status="stopped")
        self.assertEqual(self._stop(rec).status_code, 200)


class CancelDestroyWasInProgressTests(TestCase):
    """was_in_progress field in the recording_cancelled WebSocket event."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=98, name="Cancel Test Channel")
        self.user = _make_admin()
        self.factory = APIRequestFactory()

    def _delete(self, rec):
        request = self.factory.delete(f"/api/channels/recordings/{rec.id}/")
        force_authenticate(request, user=self.user)
        return RecordingViewSet.as_view({"delete": "destroy"})(request, pk=rec.id)

    @patch("apps.channels.api_views._stop_dvr_clients", return_value=1)
    @patch("core.utils.send_websocket_update")
    def test_in_progress_sends_was_in_progress_true(self, mock_ws, _):
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": "recording"},
        )
        self._delete(rec)
        payload = mock_ws.call_args[0][2]
        self.assertEqual(payload["type"], "recording_cancelled")
        self.assertTrue(payload["was_in_progress"])

    @patch("core.utils.send_websocket_update")
    def test_completed_sends_was_in_progress_false(self, mock_ws):
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            custom_properties={"status": "completed"},
        )
        self._delete(rec)
        self.assertFalse(mock_ws.call_args[0][2]["was_in_progress"])


class SignalUpdateFieldsReentrancyGuardTests(TestCase):
    """update_fields guard in schedule_task_on_save prevents redundant WS events."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=97, name="Signal Guard Channel")

    def _create_upcoming(self):
        future = timezone.now() + timedelta(hours=2)
        return Recording.objects.create(
            channel=self.channel, start_time=future,
            end_time=future + timedelta(hours=1), custom_properties={},
        )

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_custom_properties_save_skips_artwork(self, mock_artwork):
        rec = self._create_upcoming()
        mock_artwork.reset_mock()
        rec.custom_properties = {"poster_url": "https://example.com/p.jpg"}
        rec.save(update_fields=["custom_properties"])
        mock_artwork.apply_async.assert_not_called()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_task_id_save_skips_artwork(self, mock_artwork):
        rec = self._create_upcoming()
        mock_artwork.reset_mock()
        rec.task_id = "dvr-recording-999"
        rec.save(update_fields=["task_id"])
        mock_artwork.apply_async.assert_not_called()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_combined_metadata_save_skips_artwork(self, mock_artwork):
        rec = self._create_upcoming()
        mock_artwork.reset_mock()
        rec.task_id = "dvr-recording-1000"
        rec.custom_properties = {"poster_url": "x"}
        rec.save(update_fields=["custom_properties", "task_id"])
        mock_artwork.apply_async.assert_not_called()

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_creation_dispatches_artwork(self, mock_artwork):
        mock_artwork.apply_async.return_value = MagicMock()
        self._create_upcoming()
        self.assertTrue(mock_artwork.apply_async.called)

    @patch("apps.channels.signals.prefetch_recording_artwork")
    def test_scheduling_field_update_dispatches_artwork(self, mock_artwork):
        """save(update_fields=['start_time']) is not a metadata save — dispatch runs."""
        mock_artwork.apply_async.return_value = MagicMock()
        rec = self._create_upcoming()
        mock_artwork.reset_mock()
        future = timezone.now() + timedelta(hours=3)
        rec.start_time = future
        rec.end_time = future + timedelta(hours=1)
        rec.save(update_fields=["start_time", "end_time"])
        mock_artwork.apply_async.assert_called()


class RunRecordingRaceGuardTests(TestCase):
    """Race guard: stop() fires between idempotency check and status write."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=96, name="Race Guard Channel")

    def test_race_guard_exits_when_stopped_at_db_read(self):
        """If Recording.objects.get() shows 'stopped', the task must exit
        without writing 'recording' to the DB."""
        from apps.channels.tasks import run_recording as run_rec
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(hours=1),
            custom_properties={},
        )
        mock_layer = _async_channel_layer_mock()
        original_get = Recording.objects.get

        def patched_get(*args, **kwargs):
            obj = original_get(*args, **kwargs)
            if kwargs.get("id") == rec.id or (args and args[0] == rec.id):
                obj.custom_properties = {"status": "stopped"}
            return obj

        with patch("apps.channels.tasks.get_channel_layer", return_value=mock_layer), \
             patch("core.utils.log_system_event", side_effect=Exception("skip")), \
             patch.object(Recording.objects, "get", side_effect=patched_get):
            result = run_rec(
                rec.id, self.channel.id, str(rec.start_time), str(rec.end_time),
            )

        self.assertIsNone(result)
        rec.refresh_from_db()
        self.assertNotEqual(
            rec.custom_properties.get("status"), "recording",
            "Race guard failed: task overwrote 'stopped' with 'recording'",
        )

    def test_idempotency_guard_catches_stopped_before_channel_layer(self):
        """When status='stopped' at the idempotency check, get_channel_layer is never called."""
        from apps.channels.tasks import run_recording as run_rec
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": "stopped"},
        )
        with patch("apps.channels.tasks.get_channel_layer") as mock_get_layer:
            result = run_rec(
                rec.id, self.channel.id, str(rec.start_time), str(rec.end_time),
            )
        self.assertIsNone(result)
        mock_get_layer.assert_not_called()


class StopDvrClientsTests(TestCase):
    """_stop_dvr_clients() DVR client isolation."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=95, name="DVR Clients Channel")
        self._redis = "core.utils.RedisClient"
        self._sc = "apps.proxy.ts_proxy.services.channel_service.ChannelService.stop_client"
        self._sch = "apps.proxy.ts_proxy.services.channel_service.ChannelService.stop_channel"

    def _mock_redis(self, client_ids, ua_map):
        r = MagicMock()
        r.smembers.return_value = {c.encode() for c in client_ids}
        def hget_side(key, field):
            ks = key if isinstance(key, str) else key.decode("utf-8", errors="replace")
            for cid, ua in ua_map.items():
                if cid in ks:
                    return ua.encode() if isinstance(ua, str) else ua
            return b""
        r.hget.side_effect = hget_side
        return r

    def test_returns_zero_when_redis_none(self):
        with patch(self._redis) as rc:
            rc.get_client.return_value = None
            self.assertEqual(_stop_dvr_clients(str(self.channel.uuid)), 0)

    def test_stops_only_matching_client_when_recording_id_given(self):
        r = self._mock_redis(
            ["client-a", "client-b"],
            {"client-a": "Dispatcharr-DVR/recording-42",
             "client-b": "Dispatcharr-DVR/recording-99"},
        )
        with patch(self._redis) as rc, patch(self._sc) as sc:
            rc.get_client.return_value = r
            result = _stop_dvr_clients(str(self.channel.uuid), recording_id=42)
        self.assertEqual(result, 1)
        stopped = [c[0][1] for c in sc.call_args_list]
        self.assertIn("client-a", stopped)
        self.assertNotIn("client-b", stopped)

    def test_stops_all_dvr_clients_without_recording_id(self):
        r = self._mock_redis(
            ["client-a", "client-b"],
            {"client-a": "Dispatcharr-DVR/recording-42",
             "client-b": "Dispatcharr-DVR/recording-99"},
        )
        with patch(self._redis) as rc, patch(self._sc) as sc:
            rc.get_client.return_value = r
            result = _stop_dvr_clients(str(self.channel.uuid))
        self.assertEqual(result, 2)

    def test_skips_non_dvr_clients(self):
        r = self._mock_redis(
            ["viewer", "dvr-client"],
            {"viewer": "Mozilla/5.0", "dvr-client": "Dispatcharr-DVR/recording-1"},
        )
        with patch(self._redis) as rc, patch(self._sc) as sc:
            rc.get_client.return_value = r
            result = _stop_dvr_clients(str(self.channel.uuid))
        self.assertEqual(result, 1)
        stopped = [c[0][1] for c in sc.call_args_list]
        self.assertNotIn("viewer", stopped)

    def test_returns_zero_for_empty_channel(self):
        r = MagicMock()
        r.smembers.return_value = set()
        with patch(self._redis) as rc, patch(self._sc) as sc:
            rc.get_client.return_value = r
            self.assertEqual(_stop_dvr_clients(str(self.channel.uuid)), 0)
        sc.assert_not_called()

    def test_never_calls_stop_channel(self):
        """Must not stop the whole channel proxy — only individual clients."""
        r = self._mock_redis(["dvr-1"], {"dvr-1": "Dispatcharr-DVR/recording-1"})
        with patch(self._redis) as rc, patch(self._sc), patch(self._sch) as sch:
            rc.get_client.return_value = r
            _stop_dvr_clients(str(self.channel.uuid))
        sch.assert_not_called()
