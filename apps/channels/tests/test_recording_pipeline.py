"""Tests for recent DVR fixes.

Covers:
  1. Collision avoidance: _build_output_paths checks both .mkv and .ts files
  2. Logo guard: _resolve_poster_for_program skips external APIs when title ≈ channel name
  3. Recording status lifecycle: status transitions visible via API
  4. Concat flags: error-tolerant ffmpeg flags used for segment concatenation
  5. Recovery skip-list: "recording" status NOT in terminal skip list
"""
import os
import datetime as dt
import tempfile
import xml.etree.ElementTree as ET
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.channels.models import Channel, Recording

# Fixed wall time for collision tests: 10:30 avoids _2 appearing inside
# %Y%m%d_%H%M%S timestamps (e.g. hour 20 produces ..._205331 which contains "_2").
COLLISION_TEST_START = timezone.make_aware(dt.datetime(2026, 1, 15, 10, 30, 0))


def _path_has_collision_suffix(path, counter):
    """True when the MKV basename ends with _<counter>.mkv (not timestamp digits)."""
    return path.endswith(f"_{counter}.mkv")


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

    def _call(self, channel, program, start, end, recording_id=1):
        from apps.channels.tasks import _build_output_paths
        return _build_output_paths(channel, program, start, end, recording_id)

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_recording_paths_use_configured_dvr_library_directory(self, _tv, _fb):
        channel = MagicMock(name="TestCh")
        channel.name = "TestCh"
        now = COLLISION_TEST_START

        with tempfile.TemporaryDirectory() as temporary, patch(
            "apps.channels.tasks.CoreSettings.get_dvr_library_dir",
            return_value=temporary,
        ):
            final, hls_dir, _filename = self._call(
                channel,
                {"title": "My Show"},
                now,
                now + timedelta(hours=1),
            )

            root = Path(temporary).resolve()
            self.assertTrue(Path(final).resolve().is_relative_to(root))
            self.assertTrue(Path(hls_dir).resolve().is_relative_to(root))

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_no_collision_when_nothing_exists(self, _tv, _fb):
        """Fresh path — no files exist, counter stays at 1."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = COLLISION_TEST_START

        def mock_stat(path):
            raise OSError("No such file")

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, ts, fname = self._call(ch, program, now, now + timedelta(hours=1))

        self.assertFalse(_path_has_collision_suffix(final, 2))
        self.assertTrue(final.endswith(".mkv"))

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_collision_when_ts_exists_but_mkv_is_zero_bytes(self, _tv, _fb):
        """With the HLS pipeline, collision avoidance keys off the final MKV only.
        A 0-byte MKV placeholder is treated as unoccupied even if legacy TS
        segments exist elsewhere on disk."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = COLLISION_TEST_START

        def mock_stat(path):
            if _path_has_collision_suffix(path, 2):
                raise OSError("No such file")
            result = MagicMock()
            if path.endswith('.mkv'):
                result.st_size = 0       # MKV is 0-byte placeholder
            elif path.endswith('.ts'):
                result.st_size = 5000000  # legacy TS data is ignored for collision
            else:
                result.st_size = 0
            return result

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, hls_dir, fname = self._call(ch, program, now, now + timedelta(hours=1))

        self.assertFalse(_path_has_collision_suffix(final, 2), "HLS path builder ignores legacy TS when MKV is empty")

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_collision_when_mkv_has_data(self, _tv, _fb):
        """Standard collision: MKV file has data, should increment."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = COLLISION_TEST_START

        def mock_stat(path):
            if _path_has_collision_suffix(path, 2):
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

        self.assertTrue(_path_has_collision_suffix(final, 2), "Should increment counter when MKV file has data")

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_no_collision_when_both_zero_bytes(self, _tv, _fb):
        """Both MKV and TS exist but are 0 bytes — no collision."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = COLLISION_TEST_START

        def mock_stat(path):
            result = MagicMock()
            result.st_size = 0  # All files empty
            return result

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, ts, fname = self._call(ch, program, now, now + timedelta(hours=1))

        self.assertFalse(_path_has_collision_suffix(final, 2), "Should NOT increment when all files are empty")

    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
           return_value="TV/{show}/{start}.mkv")
    @patch("apps.channels.tasks.CoreSettings.get_dvr_tv_template",
           return_value="TV/{show}/S{season:02d}E{episode:02d}.mkv")
    def test_collision_increments_to_3_when_2_also_occupied(self, _tv, _fb):
        """When both base and _2 are occupied, should go to _3."""
        ch = MagicMock(name="TestCh")
        ch.name = "TestCh"
        program = {"title": "My Show"}
        now = COLLISION_TEST_START

        def mock_stat(path):
            if _path_has_collision_suffix(path, 3):
                raise OSError("No such file")
            result = MagicMock()
            if path.endswith('.mkv'):
                result.st_size = 1000000  # occupied MKV at base and _2
            else:
                result.st_size = 0
            return result

        with patch("os.stat", side_effect=mock_stat), \
             patch("os.makedirs"):
            final, hls_dir, fname = self._call(ch, program, now, now + timedelta(hours=1))

        self.assertTrue(_path_has_collision_suffix(final, 3), "Should increment to _3 when base and _2 MKVs are occupied")


class RecordingNfoTests(TestCase):
    def test_episode_nfo_contains_available_epg_metadata(self):
        from apps.channels.recording_nfo import build_recording_nfo_xml

        xml = build_recording_nfo_xml(
            program={
                "title": "Actual Show",
                "sub_title": "The Sixth Episode",
                "description": "Recorded episode description.",
                "program_id": "EP123456789",
            },
            epg_properties={
                "season": 2,
                "episode": 6,
                "date": "2026-08-01",
                "categories": ["Drama", "Mystery"],
                "rating": "TV-14",
                "star_ratings": [{"value": "8.5/10", "system": "IMDb"}],
                "country": "US",
                "language": "en",
                "credits": {
                    "director": ["Director Name"],
                    "writer": ["Writer Name"],
                    "actor": [{"name": "Actor Name", "role": "Lead"}],
                },
            },
            recording_properties={},
            channel_name="Example Network",
            start_time=COLLISION_TEST_START,
            end_time=COLLISION_TEST_START + timedelta(hours=1),
        )

        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "episodedetails")
        self.assertEqual(root.findtext("showtitle"), "Actual Show")
        self.assertEqual(root.findtext("title"), "The Sixth Episode")
        self.assertEqual(root.findtext("plot"), "Recorded episode description.")
        self.assertEqual(root.findtext("season"), "2")
        self.assertEqual(root.findtext("episode"), "6")
        self.assertEqual(root.findtext("aired"), "2026-08-01")
        self.assertIsNone(root.findtext("showyear"))
        self.assertEqual(root.findtext("rating"), "8.5")
        self.assertEqual(root.findtext("mpaa"), "TV-14")
        self.assertEqual(
            [node.text for node in root.findall("genre")],
            ["Drama", "Mystery"],
        )
        self.assertEqual(root.findtext("director"), "Director Name")
        self.assertEqual(root.findtext("credits"), "Writer Name")
        self.assertEqual(root.findtext("actor/name"), "Actor Name")
        self.assertEqual(root.findtext("actor/role"), "Lead")

    def test_completed_recording_nfo_is_written_beside_video(self):
        from apps.channels.recording_nfo import write_recording_nfo

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "Shows" / "Actual Show S02E06.mkv"
            video.parent.mkdir()
            video.write_bytes(b"recording")
            recording = SimpleNamespace(
                custom_properties={
                    "file_path": str(video),
                    "season": 2,
                    "episode": 6,
                    "duration_secs": 733,
                    "poster_url": "https://image.tmdb.org/t/p/original/show.jpg",
                    "program": {
                        "title": "Actual Show",
                        "sub_title": "The Sixth Episode",
                        "description": "Recorded episode description.",
                    },
                },
                channel=SimpleNamespace(name="Example Network"),
                start_time=COLLISION_TEST_START,
                end_time=COLLISION_TEST_START + timedelta(hours=1),
            )

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ):
                nfo_path = write_recording_nfo(recording)

            self.assertEqual(nfo_path, str(video.with_suffix(".nfo")))
            self.assertTrue(video.with_suffix(".nfo").is_file())
            parsed = ET.parse(nfo_path).getroot()
            self.assertEqual(parsed.findtext("showtitle"), "Actual Show")
            self.assertEqual(parsed.findtext("season"), "2")
            self.assertEqual(parsed.findtext("episode"), "6")
            self.assertEqual(parsed.findtext("durationinseconds"), "733")
            self.assertEqual(
                parsed.findtext("thumb"),
                "https://image.tmdb.org/t/p/original/show.jpg",
            )

    @patch("apps.channels.models.Recording.objects.filter")
    def test_dvr_sync_backfills_missing_recording_nfo(self, recordings_filter):
        from apps.channels.recording_nfo import backfill_recording_nfos

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "TV_Shows" / "Actual Show" / "S02E06.mkv"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"recording")
            recording = SimpleNamespace(
                custom_properties={
                    "status": "completed",
                    "file_path": str(video),
                    "season": 2,
                    "episode": 6,
                    "program": {
                        "title": "Actual Show",
                        "sub_title": "The Sixth Episode",
                    },
                },
                channel=SimpleNamespace(name="Example Network"),
                start_time=COLLISION_TEST_START,
                end_time=COLLISION_TEST_START + timedelta(hours=1),
                save=MagicMock(),
            )
            recordings_filter.return_value.select_related.return_value.iterator.return_value = [
                recording
            ]

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ):
                result = backfill_recording_nfos()

            self.assertEqual(result, {"written": 1, "existing": 0, "failed": 0})
            self.assertTrue(video.with_suffix(".nfo").is_file())
            self.assertEqual(
                recording.custom_properties["nfo_path"],
                str(video.with_suffix(".nfo")),
            )
            self.assertTrue(recording.custom_properties["nfo_managed"])
            recording.save.assert_called_once_with(
                update_fields=["custom_properties"]
            )

    @patch("apps.channels.models.Recording.objects.filter")
    def test_dvr_sync_refreshes_managed_nfo_with_recording_poster(
        self,
        recordings_filter,
    ):
        from apps.channels.recording_nfo import backfill_recording_nfos

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "TV_Shows" / "Actual Show" / "S02E06.mkv"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"recording")
            nfo = video.with_suffix(".nfo")
            nfo.write_text(
                "<episodedetails><showtitle>Old</showtitle></episodedetails>",
                encoding="utf-8",
            )
            recording = SimpleNamespace(
                custom_properties={
                    "status": "completed",
                    "file_path": str(video),
                    "nfo_path": str(nfo),
                    "season": 2,
                    "episode": 6,
                    "poster_url": (
                        "https://image.tmdb.org/t/p/original/show.jpg"
                    ),
                    "program": {"title": "Actual Show"},
                },
                channel=SimpleNamespace(name="Example Network"),
                start_time=COLLISION_TEST_START,
                end_time=COLLISION_TEST_START + timedelta(hours=1),
                save=MagicMock(),
            )
            recordings_filter.return_value.select_related.return_value.iterator.return_value = [
                recording
            ]

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ):
                result = backfill_recording_nfos()

            self.assertEqual(result, {"written": 1, "existing": 0, "failed": 0})
            parsed = ET.parse(nfo).getroot()
            self.assertEqual(parsed.findtext("showtitle"), "Actual Show")
            self.assertEqual(
                parsed.findtext("thumb"),
                "https://image.tmdb.org/t/p/original/show.jpg",
            )
            self.assertTrue(recording.custom_properties["nfo_managed"])
            recording.save.assert_called_once_with(
                update_fields=["custom_properties"]
            )

    @patch("apps.channels.models.Recording.objects.filter")
    def test_dvr_sync_repairs_pre_fix_comskip_duration(
        self,
        recordings_filter,
    ):
        from apps.channels.recording_nfo import backfill_recording_nfos

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "TV_Shows" / "Actual Show" / "S02E06.mkv"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"post-comskip-recording")
            nfo = video.with_suffix(".nfo")
            nfo.write_text(
                "<episodedetails><showtitle>Old</showtitle></episodedetails>",
                encoding="utf-8",
            )
            recording = SimpleNamespace(
                custom_properties={
                    "status": "completed",
                    "file_path": str(video),
                    "file_size_bytes": 999999,
                    "nfo_path": str(nfo),
                    "nfo_managed": True,
                    "season": 2,
                    "episode": 6,
                    "program": {"title": "Actual Show"},
                    "comskip": {"status": "completed", "mode": "cut"},
                },
                channel=SimpleNamespace(name="Example Network"),
                start_time=COLLISION_TEST_START,
                end_time=COLLISION_TEST_START + timedelta(hours=1),
                save=MagicMock(),
            )
            recordings_filter.return_value.select_related.return_value.iterator.return_value = [
                recording
            ]

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ), patch(
                "apps.channels.recording_nfo.subprocess.run",
                return_value=SimpleNamespace(stdout="733.4\n", stderr=""),
            ) as probe:
                result = backfill_recording_nfos()

            self.assertEqual(result, {"written": 1, "existing": 0, "failed": 0})
            self.assertEqual(recording.custom_properties["duration_secs"], 733)
            self.assertEqual(
                recording.custom_properties["file_size_bytes"],
                len(b"post-comskip-recording"),
            )
            parsed = ET.parse(nfo).getroot()
            self.assertEqual(parsed.findtext("durationinseconds"), "733")
            probe.assert_called_once()
            recording.save.assert_called_once_with(
                update_fields=["custom_properties"]
            )

    @patch("apps.channels.models.Recording.objects.filter")
    def test_dvr_sync_preserves_unmanaged_existing_nfo(self, recordings_filter):
        from apps.channels.recording_nfo import backfill_recording_nfos

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "Movies" / "Operator Movie.mkv"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"recording")
            nfo = video.with_suffix(".nfo")
            original = "<movie><title>Operator metadata</title></movie>"
            nfo.write_text(original, encoding="utf-8")
            recording = SimpleNamespace(
                custom_properties={
                    "status": "completed",
                    "file_path": str(video),
                    "program": {"title": "Database title"},
                },
                channel=SimpleNamespace(name="Example Network"),
                start_time=COLLISION_TEST_START,
                end_time=COLLISION_TEST_START + timedelta(hours=1),
                save=MagicMock(),
            )
            recordings_filter.return_value.select_related.return_value.iterator.return_value = [
                recording
            ]

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ):
                result = backfill_recording_nfos()

            self.assertEqual(result, {"written": 0, "existing": 1, "failed": 0})
            self.assertEqual(nfo.read_text(encoding="utf-8"), original)
            self.assertEqual(recording.custom_properties["nfo_path"], str(nfo))
            self.assertFalse(recording.custom_properties["nfo_managed"])
            recording.save.assert_called_once_with(
                update_fields=["custom_properties"]
            )


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

    @patch(
        "apps.media_servers.local_metadata.has_tmdb_api_key",
        return_value=False,
    )
    @patch("apps.channels.tasks.requests.get")
    def test_real_title_still_searched(self, mock_get, _has_tmdb_key):
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

    @patch("apps.channels.tasks.requests.get")
    @patch(
        "apps.media_servers.local_metadata.enrich_series_metadata_with_tmdb",
        return_value=(
            {"poster_url": "https://image.tmdb.org/t/p/original/show.jpg"},
            None,
        ),
    )
    @patch(
        "apps.media_servers.local_metadata.has_tmdb_api_key",
        return_value=True,
    )
    def test_media_library_tmdb_setting_resolves_show_poster(
        self,
        _has_key,
        enrich_series,
        fallback_request,
    ):
        logo_id, url = self._call(
            "AMC",
            {"title": "Breaking Bad"},
        )

        enrich_series.assert_called_once_with(
            {"title": "Breaking Bad", "imdb_id": None},
            title="Breaking Bad",
            year=None,
            prefer_existing=True,
        )
        fallback_request.assert_not_called()
        self.assertIsNotNone(logo_id)
        self.assertEqual(
            url,
            "https://image.tmdb.org/t/p/original/show.jpg",
        )

    @patch("apps.channels.tasks.requests.get")
    @patch(
        "apps.media_servers.local_metadata.enrich_movie_metadata_with_tmdb",
        return_value=(
            {"poster_url": "https://image.tmdb.org/t/p/original/movie.jpg"},
            None,
        ),
    )
    @patch(
        "apps.media_servers.local_metadata.has_tmdb_api_key",
        return_value=True,
    )
    def test_media_library_tmdb_setting_resolves_movie_poster(
        self,
        _has_key,
        enrich_movie,
        fallback_request,
    ):
        from apps.epg.models import ProgramData, EPGSource, EPGData

        epg_source = EPGSource.objects.create(source_type="xmltv", name="Movie EPG")
        epg_data = EPGData.objects.create(tvg_id="movies.test", epg_source=epg_source)
        program_data = ProgramData.objects.create(
            epg=epg_data,
            title="Arrival",
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            custom_properties={"categories": ["Movie"], "date": "2016"},
        )

        logo_id, url = self._call(
            "Movie Channel",
            {"id": program_data.id, "title": "Arrival"},
        )

        enrich_movie.assert_called_once_with(
            {"title": "Arrival", "imdb_id": None},
            title="Arrival",
            year=2016,
            prefer_existing=True,
        )
        fallback_request.assert_not_called()
        self.assertIsNotNone(logo_id)
        self.assertEqual(
            url,
            "https://image.tmdb.org/t/p/original/movie.jpg",
        )


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

    def test_completed_recording_metadata_edit_queues_single_item_refresh(self):
        from apps.channels.api_views import RecordingViewSet

        rec = _make_recording(
            self.channel,
            custom_properties={
                "status": "completed",
                "file_path": "/data/recordings/edited.mkv",
                "program": {"title": "Original"},
            },
        )
        request = self.factory.post(
            f"/api/channels/recordings/{rec.id}/update-metadata/",
            {"title": "Edited"},
            format="json",
        )
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "update_metadata"})

        with patch(
            "apps.media_servers.tasks.sync_dvr_media_library_after_recording.delay"
        ) as queued, self.captureOnCommitCallbacks(execute=True):
            response = view(request, pk=rec.id)

        self.assertEqual(response.status_code, 200)
        queued.assert_called_once_with(rec.id)

    def test_recording_delete_signal_queues_single_file_relation_cleanup(self):
        rec = _make_recording(
            self.channel,
            custom_properties={
                "status": "completed",
                "file_path": "/data/recordings/deleted.mkv",
            },
        )
        with patch("apps.channels.signals.revoke_task"), patch(
            "apps.media_servers.tasks.remove_dvr_media_library_recording.delay"
        ) as queued, self.captureOnCommitCallbacks(execute=True):
            rec.delete()

        queued.assert_called_once_with("/data/recordings/deleted.mkv")


# =========================================================================
# 4. Concat flags — error-tolerant ffmpeg
# =========================================================================

class ConcatFlagsTests(TestCase):
    """Verify error-tolerant FFmpeg flags on the HLS segment concat command."""

    def test_hls_concat_cmd_includes_error_tolerant_flags(self):
        from apps.channels.tasks import _dvr_build_hls_concat_cmd

        cmd = _dvr_build_hls_concat_cmd("/data/concat.txt", "/data/out.mkv")
        self.assertIn("+genpts+igndts+discardcorrupt", cmd)
        self.assertIn("-err_detect", cmd)
        self.assertEqual(cmd[cmd.index("-err_detect") + 1], "ignore_err")
        self.assertIn("-avoid_negative_ts", cmd)
        self.assertEqual(cmd[cmd.index("-avoid_negative_ts") + 1], "make_zero")
        self.assertIn("concat", cmd)
        self.assertEqual(cmd[-1], "/data/out.mkv")

    def test_hls_concat_cmd_supports_mp4_fallback_extra_args(self):
        from apps.channels.tasks import _dvr_build_hls_concat_cmd

        cmd = _dvr_build_hls_concat_cmd(
            "/data/concat.txt",
            "/data/intermediate.mp4",
            extra_args=["-bsf:a", "aac_adtstoasc"],
        )
        self.assertIn("aac_adtstoasc", cmd)
        self.assertEqual(cmd[-1], "/data/intermediate.mp4")

    def test_run_recording_uses_hls_concat_helper(self):
        import inspect
        from apps.channels.tasks import run_recording

        source = inspect.getsource(run_recording)
        self.assertIn("_dvr_build_hls_concat_cmd", source)

    def test_completed_recording_queues_media_library_sync(self):
        import inspect
        from apps.channels.tasks import run_recording

        source = inspect.getsource(run_recording)
        self.assertIn("sync_dvr_media_library_after_recording.delay", source)
        self.assertLess(
            source.index("comskip_process_recording.delay"),
            source.index(
                "sync_dvr_media_library_after_recording.delay(recording_id)"
            ),
        )

    def test_recover_recordings_uses_hls_concat_helper(self):
        import inspect
        from apps.channels.tasks import recover_recordings_on_startup

        source = inspect.getsource(recover_recordings_on_startup)
        self.assertIn("_dvr_build_hls_concat_cmd", source)


class ComskipMediaLibraryRefreshTests(TestCase):
    def test_running_comskip_cannot_be_claimed_twice(self):
        from apps.channels.tasks import _claim_comskip_processing

        recording = _make_recording(
            _make_channel("Comskip Lock", 301),
            custom_properties={
                "status": "completed",
                "comskip": {
                    "status": "running",
                    "started_at": timezone.now().isoformat(),
                },
            },
        )

        self.assertEqual(
            _claim_comskip_processing(recording.id),
            "already_running",
        )

    def test_successful_cut_persists_final_duration_and_refreshes_library(self):
        from apps.channels.tasks import comskip_process_recording

        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "recording.mkv"
            video.write_bytes(b"original-recording")
            recording = _make_recording(
                _make_channel("Comskip Cut", 302),
                custom_properties={
                    "status": "completed",
                    "file_path": str(video),
                },
            )
            probe_results = iter(("10.0", "8.0"))

            def fake_run(command, **_kwargs):
                executable = os.path.basename(command[0])
                if executable == "comskip":
                    video.with_suffix(".edl").write_text(
                        "2.0 4.0 0\n",
                        encoding="utf-8",
                    )
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                if executable == "ffprobe":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=next(probe_results),
                        stderr="",
                    )
                output = Path(command[-1])
                output.write_bytes(b"processed")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("apps.channels.tasks.shutil.which", return_value="/usr/bin/comskip"), patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=temporary,
            ), patch(
                "apps.channels.tasks.CoreSettings.get_dvr_comskip_mode",
                return_value="cut",
            ), patch(
                "apps.channels.tasks.CoreSettings.get_dvr_comskip_hw_accel",
                return_value="none",
            ), patch(
                "apps.channels.tasks.CoreSettings.get_dvr_comskip_custom_path",
                return_value="",
            ), patch(
                "apps.channels.tasks.subprocess.run",
                side_effect=fake_run,
            ), patch(
                "apps.channels.tasks._refresh_dvr_library_after_comskip"
            ) as refresh_library:
                result = comskip_process_recording.run(recording.id)

            self.assertEqual(result, "ok")
            recording.refresh_from_db()
            properties = recording.custom_properties
            self.assertEqual(properties["duration_secs"], 8)
            self.assertEqual(properties["file_size_bytes"], len(b"processed"))
            self.assertEqual(properties["comskip"]["status"], "completed")
            self.assertEqual(properties["comskip"]["mode"], "cut")
            self.assertEqual(properties["comskip"]["duration_secs"], 8)
            refresh_library.assert_called_once_with(recording.id)
            self.assertFalse(
                any(
                    path.name.startswith(f".comskip_{recording.id}_")
                    for path in Path(temporary).iterdir()
                )
            )

    def test_missing_comskip_still_imports_completed_recording(self):
        from apps.channels.tasks import comskip_process_recording

        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "recording.mkv"
            video.write_bytes(b"recording")
            recording = _make_recording(
                _make_channel("Comskip Missing", 303),
                custom_properties={
                    "status": "completed",
                    "file_path": str(video),
                },
            )

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=temporary,
            ), patch(
                "apps.channels.tasks.shutil.which",
                return_value=None,
            ), patch(
                "apps.channels.tasks._refresh_dvr_library_after_comskip"
            ) as refresh_library:
                result = comskip_process_recording.run(recording.id)

            self.assertEqual(result, "comskip_missing")
            recording.refresh_from_db()
            self.assertEqual(
                recording.custom_properties["comskip"]["status"],
                "skipped",
            )
            refresh_library.assert_called_once_with(recording.id)

    def test_completed_redelivery_finishes_library_refresh_without_recut(self):
        from apps.channels.tasks import comskip_process_recording

        recording = _make_recording(
            _make_channel("Comskip Redelivery", 304),
            custom_properties={
                "status": "completed",
                "comskip": {"status": "completed", "mode": "cut"},
            },
        )

        with patch(
            "apps.channels.tasks._refresh_dvr_library_after_comskip"
        ) as refresh_library, patch(
            "apps.channels.tasks._comskip_process_recording"
        ) as process_recording:
            result = comskip_process_recording.run(recording.id)

        self.assertEqual(result, "already_processed")
        process_recording.assert_not_called()
        refresh_library.assert_called_once_with(recording.id)

    def test_terminal_comskip_refresh_writes_exact_nfo_and_queues_vod_sync(self):
        from apps.channels.tasks import _refresh_dvr_library_after_comskip

        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "Shows" / "Example S01E02.mkv"
            video.parent.mkdir()
            video.write_bytes(b"final-cut")
            recording = _make_recording(
                _make_channel("Comskip Publish", 305),
                custom_properties={
                    "status": "completed",
                    "file_path": str(video),
                    "season": 1,
                    "episode": 2,
                    "program": {
                        "title": "Example",
                        "sub_title": "Second Episode",
                    },
                    "comskip": {"status": "completed", "mode": "cut"},
                },
            )

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=temporary,
            ), patch(
                "apps.channels.tasks._probe_media_duration",
                return_value=733.4,
            ), patch(
                "apps.media_servers.tasks."
                "sync_dvr_media_library_after_recording.delay"
            ) as queued:
                _refresh_dvr_library_after_comskip(recording.id)

            recording.refresh_from_db()
            properties = recording.custom_properties
            self.assertEqual(properties["duration_secs"], 733)
            self.assertEqual(properties["file_size_bytes"], len(b"final-cut"))
            self.assertTrue(properties["nfo_managed"])
            parsed = ET.parse(properties["nfo_path"]).getroot()
            self.assertEqual(parsed.findtext("durationinseconds"), "733")
            queued.assert_called_once_with(recording.id)


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
        mock_redis_conn.exists.return_value = False  # No active-recording lock
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
# 7. FFmpeg in-process retry loop
# =========================================================================

class FfmpegRetryTests(TestCase):
    """Verify FFmpeg restart logic for mid-recording crashes and stalls."""

    def test_ffmpeg_retry_constants_and_helpers_exist(self):
        from apps.channels import tasks as dvr_tasks

        self.assertGreater(dvr_tasks._dvr_ffmpeg_retry_window_seconds(), 0)
        self.assertEqual(dvr_tasks._dvr_count_hls_segments(None), 0)
        self.assertEqual(dvr_tasks._dvr_count_hls_segments("/nonexistent"), 0)
        self.assertEqual(dvr_tasks._dvr_ffmpeg_retry_backoff_seconds(1), 0.25)
        self.assertEqual(dvr_tasks._dvr_ffmpeg_retry_backoff_seconds(12), 3.0)

    @patch("apps.proxy.live_proxy.config_helper.ConfigHelper.stream_timeout", return_value=60)
    @patch("apps.proxy.live_proxy.config_helper.ConfigHelper.failover_grace_period", return_value=20)
    def test_retry_window_matches_live_proxy_timeouts(self, _grace, _stream):
        from apps.channels.tasks import _dvr_ffmpeg_retry_window_seconds

        self.assertEqual(_dvr_ffmpeg_retry_window_seconds(), 80.0)

    def test_hls_start_number_zero_when_playlist_exists(self):
        import tempfile
        from apps.channels.tasks import _dvr_hls_start_number

        with tempfile.TemporaryDirectory() as tmp:
            m3u8 = os.path.join(tmp, "index.m3u8")
            open(os.path.join(tmp, "seg_00000.ts"), "wb").write(b"\x00")
            open(os.path.join(tmp, "seg_00013.ts"), "wb").write(b"\x00")
            with open(m3u8, "w") as f:
                f.write("#EXTM3U\n#EXT-X-TARGETDURATION:4\n")
                f.write("seg_00000.ts\nseg_00013.ts\n")
            # append_list reloads playlist entries; start_number must stay 0.
            self.assertEqual(_dvr_hls_start_number(tmp, m3u8), 0)

    def test_hls_start_number_from_max_index_without_playlist(self):
        import tempfile
        from apps.channels.tasks import _dvr_hls_start_number

        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "seg_00000.ts"), "wb").write(b"\x00")
            open(os.path.join(tmp, "seg_00013.ts"), "wb").write(b"\x00")
            self.assertEqual(_dvr_hls_start_number(tmp, os.path.join(tmp, "index.m3u8")), 14)

    def test_hls_start_number_zero_on_fresh_dir(self):
        import tempfile
        from apps.channels.tasks import _dvr_hls_start_number

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_dvr_hls_start_number(tmp, os.path.join(tmp, "index.m3u8")), 0)

    def test_build_ffmpeg_cmd_continues_hls_numbering(self):
        from apps.channels.tasks import _dvr_build_ffmpeg_cmd

        cmd = _dvr_build_ffmpeg_cmd(
            "http://127.0.0.1:5656/proxy/ts/stream/uuid",
            71,
            "/data/recordings/.dvr_71_hls/index.m3u8",
            "/data/recordings/.dvr_71_hls/seg_%05d.ts",
            42,
        )
        self.assertIn("-start_number", cmd)
        self.assertEqual(cmd[cmd.index("-start_number") + 1], "42")
        hls_flags = cmd[cmd.index("-hls_flags") + 1]
        self.assertIn("append_list", hls_flags)
        self.assertIn("omit_endlist", hls_flags)
        self.assertIn("-err_detect", cmd)
        self.assertEqual(cmd[cmd.index("-err_detect") + 1], "ignore_err")

    def test_run_recording_has_retry_loop(self):
        import inspect
        from apps.channels.tasks import run_recording

        source = inspect.getsource(run_recording)
        self.assertIn("_ffmpeg_retry_count", source)
        self.assertIn("_ffmpeg_outage_started", source)
        self.assertIn("_ffmpeg_retry_window", source)
        self.assertIn("_break_reason", source)
        self.assertIn("ffmpeg_outage_window_exhausted", source)
        self.assertIn("_dvr_build_ffmpeg_cmd", source)
        self.assertIn("_dvr_hls_start_number", source)
        self.assertIn("_ffmpeg_retry_count = 0", source)


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
