"""Tests for the recording file streaming endpoint.

Covers:
  - Fallback from missing/empty main file to _temp_file_path (.ts)
  - Content-type detection for .mp4, .mkv, .ts, and unknown extensions
  - 404 when neither main file nor temp file exists
  - Full file response headers
  - Range request (HTTP 206) response
"""
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.channels.models import Channel, Recording
from apps.channels.api_views import RecordingViewSet


def _make_admin():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    u, _ = User.objects.get_or_create(
        username="file_test_admin",
        defaults={"user_level": User.UserLevel.ADMIN},
    )
    u.set_password("pass")
    u.save()
    return u


class RecordingFileEndpointTests(TestCase):
    """Tests for GET /api/channels/recordings/{id}/file/"""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=77, name="File Test Channel"
        )
        self.user = _make_admin()
        self.factory = APIRequestFactory()
        # Create real temp files for testing
        self._temp_files = []

    def tearDown(self):
        for f in self._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass

    def _create_temp_file(self, suffix=".mkv", content=b"fake video data"):
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.write(fd, content)
        os.close(fd)
        self._temp_files.append(path)
        return path

    def _make_rec(self, custom_properties=None):
        now = timezone.now()
        return Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties=custom_properties or {},
        )

    def _get_file(self, rec, **extra):
        request = self.factory.get(
            f"/api/channels/recordings/{rec.id}/file/", **extra
        )
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"get": "file"})
        return view(request, pk=rec.id)

    # ── 404 cases ──────────────────────────────────────────────

    def test_404_when_no_file_path(self):
        rec = self._make_rec({"status": "completed"})
        response = self._get_file(rec)
        self.assertEqual(response.status_code, 404)

    def test_404_when_file_does_not_exist(self):
        rec = self._make_rec({"file_path": "/nonexistent/video.mkv"})
        response = self._get_file(rec)
        self.assertEqual(response.status_code, 404)

    def test_serves_empty_main_file_when_no_temp(self):
        """An empty main file is still served if no temp fallback exists."""
        empty_file = self._create_temp_file(content=b"")
        rec = self._make_rec({"file_path": empty_file})
        response = self._get_file(rec)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Length"], "0")

    # ── Temp file fallback ─────────────────────────────────────

    def test_falls_back_to_temp_ts_when_main_missing(self):
        ts_file = self._create_temp_file(suffix=".ts", content=b"ts stream data")
        rec = self._make_rec({
            "file_path": "/nonexistent/video.mkv",
            "_temp_file_path": ts_file,
        })
        response = self._get_file(rec)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp2t")

    def test_falls_back_to_temp_ts_when_main_empty(self):
        empty_mkv = self._create_temp_file(suffix=".mkv", content=b"")
        ts_file = self._create_temp_file(suffix=".ts", content=b"ts stream data")
        rec = self._make_rec({
            "file_path": empty_mkv,
            "_temp_file_path": ts_file,
        })
        response = self._get_file(rec)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp2t")

    def test_serves_main_file_when_it_exists_and_nonempty(self):
        mkv_file = self._create_temp_file(suffix=".mkv", content=b"real mkv data")
        ts_file = self._create_temp_file(suffix=".ts", content=b"ts stream data")
        rec = self._make_rec({
            "file_path": mkv_file,
            "_temp_file_path": ts_file,
            "file_name": "show.mkv",
        })
        response = self._get_file(rec)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/x-matroska")

    # ── Content-type detection ─────────────────────────────────

    def test_content_type_mp4(self):
        mp4_file = self._create_temp_file(suffix=".mp4", content=b"mp4 data")
        rec = self._make_rec({"file_path": mp4_file})
        response = self._get_file(rec)
        self.assertEqual(response["Content-Type"], "video/mp4")

    def test_content_type_mkv(self):
        mkv_file = self._create_temp_file(suffix=".mkv", content=b"mkv data")
        rec = self._make_rec({"file_path": mkv_file})
        response = self._get_file(rec)
        self.assertEqual(response["Content-Type"], "video/x-matroska")

    def test_content_type_ts(self):
        ts_file = self._create_temp_file(suffix=".ts", content=b"ts data")
        rec = self._make_rec({"file_path": ts_file})
        response = self._get_file(rec)
        self.assertEqual(response["Content-Type"], "video/mp2t")

    # ── Response headers ───────────────────────────────────────

    def test_full_response_headers(self):
        mkv_file = self._create_temp_file(suffix=".mkv", content=b"12345678")
        rec = self._make_rec({"file_path": mkv_file, "file_name": "episode.mkv"})
        response = self._get_file(rec)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Length"], "8")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertIn("episode.mkv", response["Content-Disposition"])

    def test_fallback_file_name_uses_temp_basename(self):
        ts_file = self._create_temp_file(suffix=".ts", content=b"data")
        rec = self._make_rec({
            "file_path": "/nonexistent/video.mkv",
            "_temp_file_path": ts_file,
        })
        response = self._get_file(rec)
        expected_name = os.path.basename(ts_file)
        self.assertIn(expected_name, response["Content-Disposition"])

    # ── Range requests ─────────────────────────────────────────

    def test_range_request_returns_206(self):
        content = b"0123456789abcdef"
        mkv_file = self._create_temp_file(suffix=".mkv", content=content)
        rec = self._make_rec({"file_path": mkv_file, "file_name": "video.mkv"})
        response = self._get_file(rec, HTTP_RANGE="bytes=0-7")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Length"], "8")
        self.assertIn("bytes 0-7/16", response["Content-Range"])
        body = b"".join(response.streaming_content)
        self.assertEqual(body, b"01234567")

    def test_range_request_mid_file(self):
        content = b"0123456789abcdef"
        mkv_file = self._create_temp_file(suffix=".mkv", content=content)
        rec = self._make_rec({"file_path": mkv_file})
        response = self._get_file(rec, HTTP_RANGE="bytes=4-11")
        self.assertEqual(response.status_code, 206)
        body = b"".join(response.streaming_content)
        self.assertEqual(body, b"456789ab")
