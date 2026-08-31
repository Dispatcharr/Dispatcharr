"""Deleting an OutputProfile clears stale JSON references that pointed at it."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    STREAM_SETTINGS_KEY,
    CoreSettings,
    OutputProfile,
    scrub_output_profile_id,
)

User = get_user_model()


class OutputProfileScrubTests(TestCase):
    def setUp(self):
        self.profile = OutputProfile.objects.create(
            name="Scrub Me",
            command="ffmpeg",
            parameters="-i pipe:0 -c copy -f mpegts pipe:1",
            locked=False,
        )
        self.other_profile = OutputProfile.objects.create(
            name="Keep Me",
            command="ffmpeg",
            parameters="-i pipe:0 -c copy -f mpegts pipe:1",
            locked=False,
        )

    def test_scrub_removes_matching_user_override(self):
        user = User.objects.create_user(
            username="viewer",
            password="password",
            custom_properties={
                "output_profile": self.profile.id,
                "xc_password": "keep",
            },
        )
        other = User.objects.create_user(
            username="other",
            password="password",
            custom_properties={"output_profile": self.other_profile.id},
        )

        scrub_output_profile_id(self.profile.id)

        user.refresh_from_db()
        other.refresh_from_db()
        self.assertNotIn("output_profile", user.custom_properties)
        self.assertEqual(user.custom_properties.get("xc_password"), "keep")
        self.assertEqual(
            other.custom_properties.get("output_profile"), self.other_profile.id
        )

    def test_scrub_matches_string_stored_ids(self):
        user = User.objects.create_user(
            username="viewer",
            password="password",
            custom_properties={"output_profile": str(self.profile.id)},
        )

        scrub_output_profile_id(self.profile.id)

        user.refresh_from_db()
        self.assertNotIn("output_profile", user.custom_properties or {})

    def test_scrub_clears_hdhr_default_when_matching(self):
        CoreSettings.objects.update_or_create(
            key=STREAM_SETTINGS_KEY,
            defaults={
                "name": "Stream Settings",
                "value": {"hdhr_output_profile_id": self.profile.id},
            },
        )

        scrub_output_profile_id(self.profile.id)

        self.assertIsNone(CoreSettings.get_hdhr_output_profile_id())

    def test_scrub_leaves_hdhr_default_when_different(self):
        CoreSettings.objects.update_or_create(
            key=STREAM_SETTINGS_KEY,
            defaults={
                "name": "Stream Settings",
                "value": {"hdhr_output_profile_id": self.other_profile.id},
            },
        )

        scrub_output_profile_id(self.profile.id)

        self.assertEqual(
            CoreSettings.get_hdhr_output_profile_id(), self.other_profile.id
        )

    def test_profile_delete_triggers_scrub(self):
        user = User.objects.create_user(
            username="viewer",
            password="password",
            custom_properties={"output_profile": self.profile.id},
        )
        CoreSettings.objects.update_or_create(
            key=STREAM_SETTINGS_KEY,
            defaults={
                "name": "Stream Settings",
                "value": {"hdhr_output_profile_id": self.profile.id},
            },
        )

        self.profile.delete()

        user.refresh_from_db()
        self.assertNotIn("output_profile", user.custom_properties or {})
        self.assertIsNone(CoreSettings.get_hdhr_output_profile_id())

    def test_users_without_override_are_untouched(self):
        user = User.objects.create_user(
            username="viewer",
            password="password",
            custom_properties={"hide_adult_content": True},
        )

        scrub_output_profile_id(self.profile.id)

        user.refresh_from_db()
        self.assertEqual(user.custom_properties, {"hide_adult_content": True})
