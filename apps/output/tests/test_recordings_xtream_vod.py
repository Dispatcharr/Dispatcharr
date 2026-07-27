"""Xtream VOD exposure for completed local DVR recordings."""
import os
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone
from django.test.client import RequestFactory
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.channels.models import Channel, Recording
from apps.output.views import xc_get_vod_categories, xc_get_vod_info, xc_get_vod_streams


class XcRecordingVodTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username=f"recording-vod-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={"xc_password": "xcpass"},
        )
        self.channel = Channel.objects.create(
            channel_number=900,
            name="Recording source",
            hidden_from_output=False,
        )
        self.file = tempfile.NamedTemporaryFile(suffix=".mkv", delete=False)
        self.file.write(b"recording data")
        self.file.close()
        now = timezone.now()
        self.recording = Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={
                "status": "completed",
                "file_path": self.file.name,
                "file_name": "race.mkv",
                "title": "Hungarian Grand Prix",
            },
        )

    def tearDown(self):
        if os.path.exists(self.file.name):
            os.unlink(self.file.name)

    def test_completed_nonempty_recording_appears_in_dedicated_vod_category(self):
        categories = xc_get_vod_categories(self.user)
        self.assertIn(
            {"category_id": "dispatcharr-recordings", "category_name": "Recordings", "parent_id": 0},
            categories,
        )

        streams = xc_get_vod_streams(
            self.factory.get("/player_api.php"), self.user, "dispatcharr-recordings"
        )
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["stream_id"], f"recording-{self.recording.id}")
        self.assertEqual(streams[0]["name"], "Hungarian Grand Prix")
        self.assertEqual(streams[0]["container_extension"], "mkv")
        self.assertNotIn(self.file.name, str(streams[0]))

    def test_incomplete_or_missing_recording_is_not_exposed(self):
        now = timezone.now()
        Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={"status": "recording", "file_path": self.file.name},
        )
        Recording.objects.create(
            channel=self.channel,
            start_time=now,
            end_time=now,
            custom_properties={"status": "completed", "file_path": "/missing/file.mkv"},
        )
        streams = xc_get_vod_streams(
            self.factory.get("/player_api.php"), self.user, "dispatcharr-recordings"
        )
        self.assertEqual([row["stream_id"] for row in streams], [f"recording-{self.recording.id}"])

    def test_xc_movie_route_streams_completed_recording_with_range_support(self):
        with patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True), patch(
            "apps.channels.api_views.network_access_allowed", return_value=True
        ):
            response = self.client.get(
                f"/movie/{self.user.username}/xcpass/recording-{self.recording.id}.mkv",
                HTTP_RANGE="bytes=0-3",
            )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 0-3/14")

    def test_recording_info_is_available_only_to_authorized_user(self):
        info = xc_get_vod_info(
            self.factory.get("/player_api.php"), self.user, f"recording-{self.recording.id}"
        )
        self.assertEqual(info["movie_data"]["stream_id"], f"recording-{self.recording.id}")
        self.assertNotIn(self.file.name, str(info))
