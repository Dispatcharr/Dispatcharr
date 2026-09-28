"""Tests for server-owned DVR storage paths and API write protections."""
import uuid
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.channels.api_views import RECORDINGS_STORAGE_ROOT
from apps.channels.models import Channel, Recording
from apps.channels.serializers import RecordingSerializer


@override_settings(ALLOWED_HOSTS=["testserver"])
class RecordingStoragePathWriteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin, _ = User.objects.get_or_create(
            username="recording_storage_admin",
            defaults={"user_level": User.UserLevel.ADMIN},
        )
        self.admin.user_level = User.UserLevel.ADMIN
        self.admin.set_password("pass")
        self.admin.save()
        self.channel = Channel.objects.create(
            channel_number=77, name="Storage Path Channel"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        now = timezone.now()
        self.recording = Recording.objects.create(
            channel=self.channel,
            start_time=now + timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
            custom_properties={
                "status": "scheduled",
                "file_path": f"{RECORDINGS_STORAGE_ROOT}/safe.mkv",
                "_hls_dir": f"{RECORDINGS_STORAGE_ROOT}/.dvr_safe_hls",
                "file_name": "safe.mkv",
                "program": {"title": "Keep Me"},
            },
        )

    def test_serializer_strips_server_owned_keys_on_create(self):
        now = timezone.now()
        serializer = RecordingSerializer(
            data={
                "channel": self.channel.id,
                "start_time": now + timedelta(minutes=10),
                "end_time": now + timedelta(hours=1),
                "custom_properties": {
                    "program": {"title": "New"},
                    "file_path": "/etc/passwd",
                    "_hls_dir": "/data/../app",
                    "file_name": "evil.mkv",
                },
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        cleaned = serializer.validated_data["custom_properties"]
        self.assertEqual(cleaned.get("program", {}).get("title"), "New")
        self.assertNotIn("file_path", cleaned)
        self.assertNotIn("_hls_dir", cleaned)
        self.assertNotIn("file_name", cleaned)

    def test_partial_update_preserves_existing_storage_paths(self):
        serializer = RecordingSerializer(
            self.recording,
            data={
                "custom_properties": {
                    "program": {"title": "Updated"},
                    "file_path": "/etc/passwd",
                    "_hls_dir": "/data/../tmp/evil",
                }
            },
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.recording.refresh_from_db()
        props = self.recording.custom_properties or {}
        self.assertEqual(props.get("program", {}).get("title"), "Updated")
        self.assertEqual(props.get("file_path"), f"{RECORDINGS_STORAGE_ROOT}/safe.mkv")
        self.assertEqual(
            props.get("_hls_dir"), f"{RECORDINGS_STORAGE_ROOT}/.dvr_safe_hls"
        )

    def test_resolve_helper_rejects_traversal(self):
        from apps.channels.api_views import _resolve_recording_storage_path

        recordings_root = Path(RECORDINGS_STORAGE_ROOT)
        recordings_root.mkdir(parents=True, exist_ok=True)
        name = f"_resolve_{uuid.uuid4().hex}.mkv"
        target = recordings_root / name
        target.write_bytes(b"x")
        try:
            self.assertEqual(
                _resolve_recording_storage_path(str(target)),
                str(target.resolve()),
            )
            self.assertIsNone(
                _resolve_recording_storage_path("/data/../etc/passwd")
            )
            self.assertIsNone(_resolve_recording_storage_path("/etc/passwd"))
        finally:
            target.unlink(missing_ok=True)
