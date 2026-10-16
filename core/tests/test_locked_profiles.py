"""Locked stream and output profiles reject API edits and deletes."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import OutputProfile, StreamProfile, UserAgent


class LockedProfileApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="profile-admin", password="x", user_level=10
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.user_agent = UserAgent.objects.create(
            name="Test Agent",
            user_agent="TestAgent/1.0",
        )
        self.other_agent = UserAgent.objects.create(
            name="Other Agent",
            user_agent="OtherAgent/1.0",
        )
        self.stream = StreamProfile.objects.create(
            name="Locked Stream",
            command="ffmpeg",
            parameters="-c copy",
            locked=True,
            user_agent=self.user_agent,
        )
        self.output = OutputProfile.objects.create(
            name="Locked Output",
            command="ffmpeg",
            parameters="-i pipe:0 -c copy -f mpegts pipe:1",
            locked=True,
        )
        self.custom_stream = StreamProfile.objects.create(
            name="Custom Stream",
            command="ffmpeg",
            parameters="-c copy",
            locked=False,
        )
        self.custom_output = OutputProfile.objects.create(
            name="Custom Output",
            command="ffmpeg",
            parameters="-i pipe:0 -c copy -f mpegts pipe:1",
            locked=False,
        )

    def test_locked_stream_profile_rejects_parameter_change(self):
        response = self.client.patch(
            f"/api/core/streamprofiles/{self.stream.id}/",
            {"parameters": "-c copy -map 0"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.stream.refresh_from_db()
        self.assertEqual(self.stream.parameters, "-c copy")

    def test_locked_stream_profile_allows_user_agent_change(self):
        response = self.client.patch(
            f"/api/core/streamprofiles/{self.stream.id}/",
            {"user_agent": self.other_agent.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.stream.refresh_from_db()
        self.assertEqual(self.stream.user_agent_id, self.other_agent.id)
        self.assertEqual(self.stream.parameters, "-c copy")

    def test_locked_stream_profile_cannot_be_unlocked_or_deleted(self):
        response = self.client.patch(
            f"/api/core/streamprofiles/{self.stream.id}/",
            {"locked": False, "name": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.stream.refresh_from_db()
        self.assertTrue(self.stream.locked)
        self.assertEqual(self.stream.name, "Locked Stream")

        response = self.client.delete(f"/api/core/streamprofiles/{self.stream.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(StreamProfile.objects.filter(id=self.stream.id).exists())

    def test_locked_output_profile_rejects_edits_and_delete(self):
        response = self.client.put(
            f"/api/core/outputprofiles/{self.output.id}/",
            {
                "name": "Locked Output",
                "command": "ffmpeg",
                "parameters": "-i pipe:0 -c:v copy -c:a aac -f mpegts pipe:1",
                "is_active": True,
                "locked": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.output.refresh_from_db()
        self.assertEqual(
            self.output.parameters, "-i pipe:0 -c copy -f mpegts pipe:1"
        )

        response = self.client.patch(
            f"/api/core/outputprofiles/{self.output.id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.output.refresh_from_db()
        self.assertTrue(self.output.is_active)

        response = self.client.delete(f"/api/core/outputprofiles/{self.output.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(OutputProfile.objects.filter(id=self.output.id).exists())

    def test_unlocked_profiles_can_still_be_changed_and_deleted(self):
        response = self.client.patch(
            f"/api/core/streamprofiles/{self.custom_stream.id}/",
            {"parameters": "-c copy -map 0"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.delete(
            f"/api/core/streamprofiles/{self.custom_stream.id}/"
        )
        self.assertEqual(response.status_code, 204)

        response = self.client.patch(
            f"/api/core/outputprofiles/{self.custom_output.id}/",
            {"parameters": "-i pipe:0 -c:a aac -f mpegts pipe:1"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.delete(
            f"/api/core/outputprofiles/{self.custom_output.id}/"
        )
        self.assertEqual(response.status_code, 204)

    def test_model_save_rejects_locked_output_profile_changes(self):
        self.output.parameters = "-i pipe:0 -vn -f mpegts pipe:1"
        with self.assertRaises(ValidationError):
            self.output.save()
        self.output.refresh_from_db()
        self.assertEqual(
            self.output.parameters, "-i pipe:0 -c copy -f mpegts pipe:1"
        )
