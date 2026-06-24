"""Tests for DVR recording playback authentication (file/hls endpoints)."""
import os
import tempfile

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken

from apps.channels.api_views import RecordingViewSet
from apps.channels.models import Channel, Recording


def _make_admin():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="recording_playback_admin",
        defaults={"user_level": User.UserLevel.ADMIN},
    )
    user.set_password("pass")
    user.save()
    return user


@override_settings(ALLOWED_HOSTS=["testserver"])
class RecordingPlaybackAuthTests(TestCase):
    def setUp(self):
        self.channel = Channel.objects.create(channel_number=42, name="Playback Auth Channel")
        self.user = _make_admin()
        self.factory = APIRequestFactory()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".mkv", delete=False)
        self.tmp.write(b"\x00" * 1024)
        self.tmp.close()
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

    def _file(self, *, token=None):
        url = f"/api/channels/recordings/{self.recording.id}/file/"
        if token:
            url = f"{url}?token={token}"
        request = self.factory.get(url)
        view = RecordingViewSet.as_view({"get": "file"})
        return view(request, pk=self.recording.id)

    @staticmethod
    def _jwt_for(user):
        return str(RefreshToken.for_user(user).access_token)

    def test_file_requires_authentication(self):
        response = self._file()
        self.assertEqual(response.status_code, 403)

    def test_file_accepts_jwt_query_param(self):
        token = self._jwt_for(self.user)
        response = self._file(token=token)
        self.assertEqual(response.status_code, 200)
