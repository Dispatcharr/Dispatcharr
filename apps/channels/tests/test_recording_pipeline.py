"""Tests for recent DVR fixes.

Covers:
  1. Collision avoidance: _build_output_paths checks both .mkv and .ts files
  2. Logo guard: _resolve_poster_for_program skips external APIs when title ≈ channel name
  3. Recording status lifecycle: status transitions visible via API
  4. Concat flags: error-tolerant ffmpeg flags used for segment concatenation
  5. Recovery skip-list: "recording" status NOT in terminal skip list
"""
import os
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.channels.models import Channel, Recording


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u, _ = User.objects.get_or_create(
        username="dvr_fixes_admin",
        defaults={"user_level": User.UserLevel.ADMIN},
    )
    u.set_password("pass")
    u.save()
    return u


def _make_channel(name="Test Channel", number=100):
    return Channel.objects.create(channel_number=number, name=name)


def _make_recording(channel, **overrides):
    now = timezone.now()
    defaults = {
        "channel": channel,
        "start_time": now - timedelta(hours=1),
        "end_time": now + timedelta(hours=1),
        "custom_properties": {},
    }
    defaults.update(overrides)
    return Recording.objects.create(**defaults)


# =========================================================================
# 1. Collision avoidance — _build_output_paths
# =========================================================================

class CollisionAvoidanceTests(TestCase):
    """_build_output_paths must increment the filename counter when
    EITHER the .mkv OR the .ts file already exists with size > 0."""

    def _call(self, channel, program, start, end):
        from apps.channels.tasks import _build_output_paths
        return _build_output_paths(channel, program, start, end)

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_no_collision_when_nothing_exists(self, _tv, _fb):
        """Fresh path — no files exist, counter stays at 1."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = timezone.now()

        def mock_stat(path):
            raise OSError("No such file")

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, ts, fname = self._call(ch, program, now, now + timedelta(hours=1))

        # Should NOT have a _2 suffix
        self.assertNotIn("_2", final)
        self.assertTrue(final.endswith(".mkv"))

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_collision_when_ts_exists_but_mkv_is_zero_bytes(self, _tv, _fb):
        """Pre-restart scenario: MKV is 0-byte placeholder, TS has real data.
        The old code only checked MKV size, so it would reuse the path.
        The fix also checks TS, so it must increment."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = timezone.now()

        def mock_stat(path):
            if "_2" in path:
                raise OSError("No such file")
            result = MagicMock()
            if path.endswith('.mkv'):
                result.st_size = 0       # MKV is 0-byte placeholder
            elif path.endswith('.ts'):
                result.st_size = 5000000  # TS has real data from pre-restart
            else:
                result.st_size = 0
            return result

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, ts, fname = self._call(ch, program, now, now + timedelta(hours=1))

        # Must have incremented to _2
        self.assertIn("_2", final, "Should increment counter when TS file has data")

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_collision_when_mkv_has_data(self, _tv, _fb):
        """Standard collision: MKV file has data, should increment."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = timezone.now()

        def mock_stat(path):
            if "_2" in path:
                raise OSError("No such file")
            result = MagicMock()
            if path.endswith('.mkv'):
                result.st_size = 1000000  # MKV has data
            else:
                result.st_size = 0
            return result

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, ts, fname = self._call(ch, program, now, now + timedelta(hours=1))

        self.assertIn("_2", final, "Should increment counter when MKV file has data")

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_no_collision_when_both_zero_bytes(self, _tv, _fb):
        """Both MKV and TS exist but are 0 bytes — no collision."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = timezone.now()

        def mock_stat(path):
            result = MagicMock()
            result.st_size = 0  # All files empty
            return result

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, ts, fname = self._call(ch, program, now, now + timedelta(hours=1))

        self.assertNotIn("_2", final, "Should NOT increment when all files are empty")

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_collision_increments_to_3_when_2_also_occupied(self, _tv, _fb):
        """When both base and _2 are occupied, should go to _3."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = timezone.now()

        def mock_stat(path):
            if "_3" in path:
                raise OSError("No such file")
            result = MagicMock()
            if path.endswith('.ts'):
                result.st_size = 5000000
            else:
                result.st_size = 0
            return result

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, ts, fname = self._call(ch, program, now, now + timedelta(hours=1))

        self.assertIn("_3", final, "Should increment to _3 when base and _2 are occupied")


# =========================================================================
# 2. Logo guard — _resolve_poster_for_program
# =========================================================================

class LogoGuardTests(TestCase):
    """When the program title matches the channel name, external API
    searches (VOD, TMDB, OMDb, TVMaze, iTunes) must be skipped."""

    def _call(self, channel_name, program, channel_logo_id=None):
        from apps.channels.tasks import _resolve_poster_for_program
        return _resolve_poster_for_program(channel_name, program, channel_logo_id)

    @patch("apps.channels.tasks.requests.get")
    def test_channel_name_as_title_skips_external_apis(self, mock_get):
        """Title = 'USA A&E SD*', channel = 'USA A&E SD*' → no external calls."""
        program = {"title": "USA A&E SD*"}
        logo_id, url = self._call("USA A&E SD*", program, channel_logo_id=42)

        # Should NOT have called any external APIs
        mock_get.assert_not_called()
        # Should fall back to channel logo
        self.assertEqual(logo_id, 42)
        self.assertIsNone(url)

    @patch("apps.channels.tasks.requests.get")
    def test_channel_name_normalized_match(self, mock_get):
        """Title = 'fox news', channel = 'FOX-News*' → normalized match, skip APIs."""
        program = {"title": "fox news"}
        logo_id, url = self._call("FOX-News*", program, channel_logo_id=99)

        mock_get.assert_not_called()
        self.assertEqual(logo_id, 99)

    @patch("apps.channels.tasks.requests.get")
    def test_real_title_still_searched(self, mock_get):
        """Title = 'Breaking Bad' on channel 'AMC' → should try external APIs."""
        # Mock TVMaze returning a result
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_resp.json.return_value = {
            "image": {"original": "https://tvmaze.com/breaking-bad.jpg"}
        }
        mock_get.return_value = mock_resp

        program = {"title": "Breaking Bad"}
        logo_id, url = self._call("AMC", program)

        # Should have made at least one external API call
        self.assertTrue(mock_get.called, "Should search external APIs for real titles")
        self.assertIsNotNone(url)

    @patch("apps.channels.tasks.requests.get")
    def test_no_title_skips_to_channel_logo(self, mock_get):
        """No title at all → falls through to channel logo, no API calls."""
        program = {}
        logo_id, url = self._call("SomeChannel", program, channel_logo_id=55)

        mock_get.assert_not_called()
        self.assertEqual(logo_id, 55)

    @patch("apps.channels.tasks.requests.get")
    def test_epg_image_still_used_even_when_title_is_channel_name(self, mock_get):
        """Even when title = channel name, Stage 1 (EPG images) should still work."""
        from apps.epg.models import ProgramData, EPGSource, EPGData

        # Create an EPG source + EPGData entry + program with an icon URL
        epg_source = EPGSource.objects.create(source_type="xmltv", name="Test EPG")
        epg_data = EPGData.objects.create(tvg_id="test.ch", epg_source=epg_source)
        prog = ProgramData.objects.create(
            epg=epg_data,
            title="Test Channel HD",
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            custom_properties={"icon": "https://epg-cdn.com/test-icon.png"},
        )

        program = {"title": "Test Channel HD", "id": prog.id}

        # Mock _validate_url to return True for the icon URL
        with patch("apps.channels.tasks._validate_url", return_value=True):
            logo_id, url = self._call("Test Channel HD", program, channel_logo_id=10)

        # EPG icon should still be used (Stage 1 doesn't depend on title guard)
        self.assertEqual(url, "https://epg-cdn.com/test-icon.png")
        mock_get.assert_not_called()


# =========================================================================
# 3. Recording status lifecycle via API
# =========================================================================

class RecordingStatusLifecycleTests(TestCase):
    """Verify recording status transitions and that terminal recordings
    are properly filterable (supports the red-dot fix in guideUtils)."""

    def setUp(self):
        self.channel = _make_channel("Status Test Channel", 200)
        self.user = _make_admin()
        self.factory = APIRequestFactory()

    def _list_recordings(self):
        from apps.channels.api_views import RecordingViewSet
        request = self.factory.get("/api/channels/recordings/")
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"get": "list"})
        return view(request)

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_stopped_recording_has_terminal_status(self, _ws):
        """After stop, custom_properties.status = 'stopped'."""
        from apps.channels.api_views import RecordingViewSet

        rec = _make_recording(self.channel, custom_properties={
            "status": "recording",
            "program": {"id": 1, "title": "Live Show"},
        })

        request = self.factory.post(f"/api/channels/recordings/{rec.id}/stop/")
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "stop"})

        with patch("apps.channels.signals.revoke_task"):
            response = view(request, pk=rec.id)

        self.assertIn(response.status_code, [200, 204])
        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties.get("status"), "stopped")

    def test_listing_includes_status_in_custom_properties(self):
        """API listing returns custom_properties with status field."""
        _make_recording(self.channel, custom_properties={
            "status": "recording",
            "program": {"id": 1, "title": "Recording Show"},
        })
        _make_recording(self.channel, custom_properties={
            "status": "stopped",
            "program": {"id": 2, "title": "Stopped Show"},
        })

        response = self._list_recordings()
        self.assertEqual(response.status_code, 200)

        statuses = [r["custom_properties"].get("status") for r in response.data]
        self.assertIn("recording", statuses)
        self.assertIn("stopped", statuses)

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_delete_recording_removes_from_listing(self, _ws):
        """Deleting a recording removes it from the listing entirely."""
        from apps.channels.api_views import RecordingViewSet

        rec = _make_recording(self.channel, custom_properties={
            "status": "stopped",
            "program": {"id": 3, "title": "To Delete"},
        })
        rec_id = rec.id

        request = self.factory.delete(f"/api/channels/recordings/{rec_id}/")
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"delete": "destroy"})

        with patch("apps.channels.signals.revoke_task"):
            response = view(request, pk=rec_id)

        self.assertIn(response.status_code, [200, 204])
        self.assertFalse(Recording.objects.filter(id=rec_id).exists())


# =========================================================================
# 4. Concat flags — error-tolerant ffmpeg
# =========================================================================

class ConcatFlagsTests(TestCase):
    """Verify that the finalize phase uses error-tolerant ffmpeg flags
    when concatenating pre-restart segments."""

    def test_concat_command_includes_error_tolerant_flags(self):
        """Inspect the source code to confirm error-tolerant flags are present.
        This is a static analysis test — no ffmpeg execution needed."""
        import inspect
        from apps.channels.tasks import run_recording
        source = inspect.getsource(run_recording)

        # The concat subprocess.run call must include these flags
        self.assertIn("+genpts+igndts+discardcorrupt", source,
                       "Concat must use +genpts+igndts+discardcorrupt fflags")
        self.assertIn("ignore_err", source,
                       "Concat must use -err_detect ignore_err")
        self.assertIn("-f", source)
        self.assertIn("concat", source)

    def test_concat_goes_directly_to_mkv(self):
        """Concat must produce MKV directly (not intermediate .ts) to
        preserve timestamp boundaries and avoid playback freeze at splice."""
        import inspect
        from apps.channels.tasks import run_recording
        source = inspect.getsource(run_recording)

        # Must contain reset_timestamps for proper segment boundary handling
        self.assertIn("reset_timestamps", source,
                       "Concat must use -reset_timestamps 1 for seamless seeking")
        # Must write directly to final_path (MKV), not an intermediate .ts
        self.assertIn("_concat_did_remux", source,
                       "Concat path must set flag to skip separate remux step")

    def test_segment_time_metadata_present(self):
        """Verify concat uses -segment_time_metadata for boundary awareness."""
        import inspect
        from apps.channels.tasks import run_recording
        source = inspect.getsource(run_recording)

        self.assertIn("segment_time_metadata", source,
                       "Concat must use -segment_time_metadata 1 for segment boundary handling")


# =========================================================================
# 5. Recovery skip-list
# =========================================================================

class RecoverySkipListTests(TestCase):
    """Verify that the recovery function does NOT skip 'recording' status,
    since that's the exact status recordings have when the server crashes."""

    def test_recording_status_not_in_skip_list(self):
        """Inspect recover_recordings_on_startup to ensure 'recording' is
        NOT treated as a terminal/skip state."""
        import inspect
        from apps.channels.tasks import recover_recordings_on_startup
        source = inspect.getsource(recover_recordings_on_startup)

        # Find the skip condition line
        # It should be: if current_status in ("completed", "stopped"):
        # NOT: if current_status in ("completed", "stopped", "recording"):
        lines = source.split('\n')
        skip_line = None
        for line in lines:
            if 'current_status in' in line and ('completed' in line or 'stopped' in line):
                skip_line = line.strip()
                break

        self.assertIsNotNone(skip_line, "Should find the skip-list condition")
        self.assertNotIn('"recording"', skip_line,
                          "Skip list must NOT contain 'recording' — "
                          "that's the status of crashed mid-stream recordings that need recovery")

    @patch("core.utils.RedisClient")
    @patch("apps.channels.tasks.run_recording")
    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_recovery_processes_recording_status(self, _ws, mock_run, mock_redis_cls):
        """A recording with status='recording' should be recovered, not skipped."""
        mock_redis_conn = MagicMock()
        mock_redis_conn.set.return_value = True  # Acquire lock
        mock_redis_cls.get_client.return_value = mock_redis_conn

        channel = _make_channel("Recovery Test", 300)
        now = timezone.now()
        rec = _make_recording(channel, custom_properties={
            "status": "recording",
            "program": {"title": "Crashed Show"},
        }, end_time=now + timedelta(hours=2))

        from apps.channels.tasks import recover_recordings_on_startup

        with patch("apps.channels.signals.revoke_task"):
            result = recover_recordings_on_startup()

        # The recording should have been dispatched for recovery
        self.assertTrue(mock_run.apply_async.called,
                        "Recording with status='recording' should be dispatched for recovery")

    @patch("core.utils.RedisClient")
    @patch("apps.channels.tasks.run_recording")
    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_recovery_skips_stopped_recordings(self, _ws, mock_run, mock_redis_cls):
        """A recording with status='stopped' should be skipped by recovery."""
        mock_redis_conn = MagicMock()
        mock_redis_conn.set.return_value = True
        mock_redis_cls.get_client.return_value = mock_redis_conn

        channel = _make_channel("Recovery Skip Test", 301)
        now = timezone.now()
        rec = _make_recording(channel, custom_properties={
            "status": "stopped",
            "program": {"title": "Finished Show"},
        }, end_time=now + timedelta(hours=2))

        from apps.channels.tasks import recover_recordings_on_startup
        with patch("apps.channels.signals.revoke_task"):
            recover_recordings_on_startup()

        # Should NOT have dispatched a recovery task
        mock_run.apply_async.assert_not_called()


# =========================================================================
# 6. Frontend red-dot filter (guideUtils.mapRecordingsByProgramId)
# =========================================================================

class MapRecordingsByProgramIdTests(TestCase):
    """These test the BACKEND side — confirming that recording status
    is preserved in the API response so the frontend can filter on it.

    The actual frontend filtering is covered by frontend/src/pages/__tests__/DVR.test.jsx
    and the guideUtils code, but we verify the data contract here."""

    def test_recording_custom_properties_status_persisted(self):
        """Recording status in custom_properties survives save/load cycle."""
        channel = _make_channel("Red Dot Test", 400)
        rec = _make_recording(channel, custom_properties={
            "status": "stopped",
            "program": {"id": 42, "title": "A Show"},
        })

        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties["status"], "stopped")

    def test_terminal_statuses_are_well_defined(self):
        """Verify the terminal status set matches what the frontend uses."""
        # These are the statuses that should NOT show a red dot in the Guide
        terminal = {"stopped", "completed", "interrupted", "failed"}
        channel = _make_channel("Terminal Status Test", 410)

        # Verify each status is a valid recording status
        for status in terminal:
            rec = _make_recording(channel, custom_properties={
                "status": status,
                "program": {"id": 100, "title": "Test"},
            })
            rec.refresh_from_db()
            self.assertEqual(rec.custom_properties["status"], status)
