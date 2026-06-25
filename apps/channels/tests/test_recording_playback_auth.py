"""Tests for DVR recording playback authentication (file/hls endpoints)."""
import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.channels.api_views import _recording_auth_query_suffix
from apps.channels.models import Channel, Recording


def _make_admin():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="recording_playback_admin",
        defaults={"user_level": User.UserLevel.ADMIN},
    )
    user.user_level = User.UserLevel.ADMIN
    user.set_password("pass")
    user.save()
    return user


@override_settings(ALLOWED_HOSTS=["testserver"])
@patch("apps.channels.api_views.network_access_allowed", return_value=True)
class RecordingPlaybackAuthTests(TestCase):
    def setUp(self):
        self.channel = Channel.objects.create(channel_number=42, name="Playback Auth Channel")
        self.user = _make_admin()
        self.client = APIClient()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".mkv", delete=False)
        self.tmp.write(b"\x00" * 1024)
        self.tmp.close()
        self.hls_dir = tempfile.mkdtemp(prefix="dvr_playback_auth_hls_")
        with open(os.path.join(self.hls_dir, "index.m3u8"), "w", encoding="utf-8") as playlist:
            playlist.write("#EXTM3U\n#EXTINF:4.0,\nseg_00001.ts\n")
        with open(os.path.join(self.hls_dir, "seg_00001.ts"), "wb") as segment:
            segment.write(b"\x00" * 188)
        now = timezone.now()
        self.recording = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={
                "status": "completed",
                "file_path": self.tmp.name,
                "file_name": "test.mkv",
            },
        )

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)
        if os.path.isdir(self.hls_dir):
            shutil.rmtree(self.hls_dir, ignore_errors=True)

    @staticmethod
    def _jwt_for(user):
        return str(RefreshToken.for_user(user).access_token)

    def test_file_requires_authentication(self, _mock_network):
        response = self.client.get(
            f"/api/channels/recordings/{self.recording.id}/file/"
        )
        self.assertEqual(response.status_code, 403)

    def test_file_accepts_jwt_query_param(self, _mock_network):
        token = self._jwt_for(self.user)
        response = self.client.get(
            f"/api/channels/recordings/{self.recording.id}/file/",
            {"token": token},
        )
        self.assertEqual(response.status_code, 200)

    def test_file_redirect_to_hls_preserves_token(self, _mock_network):
        pending = os.path.join(self.hls_dir, "pending.mkv")
        now = timezone.now()
        in_progress = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={
                "status": "recording",
                "_hls_dir": self.hls_dir,
                "file_path": pending,
            },
        )
        token = self._jwt_for(self.user)
        response = self.client.get(
            f"/api/channels/recordings/{in_progress.id}/file/",
            {"token": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("token=", response["Location"])
        self.assertIn("/hls/index.m3u8", response["Location"])

    def test_hls_playlist_rewrites_segments_with_token_when_present(self, _mock_network):
        now = timezone.now()
        hls_rec = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={
                "status": "recording",
                "_hls_dir": self.hls_dir,
            },
        )
        token = self._jwt_for(self.user)
        response = self.client.get(
            f"/api/channels/recordings/{hls_rec.id}/hls/index.m3u8",
            {"token": token},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("token=", body)
        self.assertIn("seg_00001.ts", body)

    def test_hls_playlist_omits_token_when_not_in_request(self, _mock_network):
        now = timezone.now()
        hls_rec = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={
                "status": "recording",
                "_hls_dir": self.hls_dir,
            },
        )
        token = self._jwt_for(self.user)
        response = self.client.get(
            f"/api/channels/recordings/{hls_rec.id}/hls/index.m3u8",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("seg_00001.ts", body)
        self.assertNotIn("token=", body)

    def test_hls_segment_accepts_jwt_query_param(self, _mock_network):
        now = timezone.now()
        hls_rec = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={
                "status": "recording",
                "_hls_dir": self.hls_dir,
            },
        )
        token = self._jwt_for(self.user)
        response = self.client.get(
            f"/api/channels/recordings/{hls_rec.id}/hls/seg_00001.ts",
            {"token": token},
        )
        self.assertEqual(response.status_code, 200)

    def test_hls_redirect_to_file_preserves_token(self, _mock_network):
        now = timezone.now()
        hls_rec = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={
                "status": "completed",
                "file_path": self.tmp.name,
                "file_name": "test.mkv",
            },
        )
        token = self._jwt_for(self.user)
        response = self.client.get(
            f"/api/channels/recordings/{hls_rec.id}/hls/index.m3u8",
            {"token": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("token=", response["Location"])
        self.assertIn("/file/", response["Location"])


class RecordingAuthQuerySuffixTests(TestCase):
    def test_empty_when_no_token(self):
        request = SimpleNamespace(GET={})
        self.assertEqual(_recording_auth_query_suffix(request), "")

    def test_includes_token_when_present(self):
        request = SimpleNamespace(GET={"token": "abc123"})
        self.assertEqual(_recording_auth_query_suffix(request), "?token=abc123")
