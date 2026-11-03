"""{streamProfile=...} references: invalid saves are rejected and referenced profiles cannot be deleted."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import StreamProfile


def _create_base():
    """Create a non-locked base profile with a unique name to avoid colliding with seeded locked profiles."""
    return StreamProfile.objects.create(
        name="Base",
        command="ffmpeg",
        parameters="-i {streamUrl} -c copy",
    )


class StreamProfileReferenceValidationTests(TestCase):
    """Unknown, malformed, and circular references never reach the database."""

    def test_unknown_reference_is_rejected_on_save(self):
        with self.assertRaises(ValidationError) as ctx:
            StreamProfile.objects.create(
                name="Broken",
                command="ffmpeg",
                parameters="-x {streamProfile=Ghost}",
            )
        self.assertIn("Ghost", str(ctx.exception))
        self.assertFalse(StreamProfile.objects.filter(name="Broken").exists())

    def test_malformed_token_is_rejected_on_save(self):
        with self.assertRaises(ValidationError):
            StreamProfile.objects.create(
                name="Malformed",
                command="ffmpeg",
                parameters="-x {streamProfile=}",
            )
        self.assertFalse(StreamProfile.objects.filter(name="Malformed").exists())

    def test_self_reference_is_rejected_on_save(self):
        profile = StreamProfile.objects.create(
            name="Loop", command="ffmpeg", parameters="-c copy"
        )
        profile.parameters = "-x {streamProfile=Loop}"
        with self.assertRaises(ValidationError):
            profile.save()

    def test_cycle_is_rejected_on_save(self):
        base = _create_base()
        StreamProfile.objects.create(
            name="Child",
            command="ffmpeg",
            parameters="-x {streamProfile=Base}",
        )
        base.refresh_from_db()
        base.parameters = "-y {streamProfile=Child}"
        with self.assertRaises(ValidationError) as ctx:
            base.save()
        self.assertIn("Circular", str(ctx.exception))
        base.refresh_from_db()
        self.assertEqual(base.parameters, "-i {streamUrl} -c copy")

    def test_valid_reference_saves(self):
        _create_base()
        StreamProfile.objects.create(
            name="Custom",
            command="ffmpeg",
            parameters="-hide_banner {streamProfile=Base}",
        )

    def test_parameters_without_tokens_are_untouched(self):
        StreamProfile.objects.create(
            name="Plain", command="ffmpeg", parameters="-i {streamUrl} -c copy"
        )
        profile = StreamProfile.objects.get(name="Plain")
        self.assertEqual(profile.parameters, "-i {streamUrl} -c copy")


class StreamProfileReferenceApiTests(TestCase):
    """The API turns reference errors into 400 instead of a server error."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="ref-admin", password="x", user_level=10
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.base = _create_base()

    def test_create_with_unknown_reference_returns_400(self):
        response = self.client.post(
            "/api/core/streamprofiles/",
            {
                "name": "Broken",
                "command": "ffmpeg",
                "parameters": "-x {streamProfile=Ghost}",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Ghost", str(response.data))
        self.assertFalse(StreamProfile.objects.filter(name="Broken").exists())

    def test_cycle_update_returns_400(self):
        StreamProfile.objects.create(
            name="Child",
            command="ffmpeg",
            parameters="-x {streamProfile=Base}",
        )
        response = self.client.patch(
            f"/api/core/streamprofiles/{self.base.id}/",
            {"parameters": "-y {streamProfile=Child}"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.base.refresh_from_db()
        self.assertEqual(self.base.parameters, "-i {streamUrl} -c copy")

    def test_valid_reference_create_returns_201(self):
        response = self.client.post(
            "/api/core/streamprofiles/",
            {
                "name": "Custom",
                "command": "ffmpeg",
                "parameters": "-hide_banner {streamProfile=Base}",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)


class StreamProfileDeletionGuardTests(TestCase):
    """A profile another profile references cannot be deleted."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="del-admin", password="x", user_level=10
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.base = _create_base()
        self.custom = StreamProfile.objects.create(
            name="FFmpeg Custom",
            command="ffmpeg",
            parameters="-hide_banner {streamProfile=Base}",
        )

    def test_model_delete_is_blocked(self):
        with self.assertRaises(ValidationError) as ctx:
            with transaction.atomic():
                self.base.delete()
        self.assertIn("FFmpeg Custom", str(ctx.exception))
        self.assertTrue(StreamProfile.objects.filter(pk=self.base.pk).exists())

    def test_queryset_delete_is_blocked(self):
        with self.assertRaises(ValidationError) as ctx:
            with transaction.atomic():
                StreamProfile.objects.filter(pk=self.base.pk).delete()
        self.assertIn("FFmpeg Custom", str(ctx.exception))
        self.assertTrue(StreamProfile.objects.filter(pk=self.base.pk).exists())

    def test_api_delete_returns_400_and_names_the_referrer(self):
        response = self.client.delete(f"/api/core/streamprofiles/{self.base.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("FFmpeg Custom", str(response.data))
        self.assertTrue(StreamProfile.objects.filter(pk=self.base.pk).exists())

    def test_referencing_profile_deletes_first_then_target(self):
        response = self.client.delete(f"/api/core/streamprofiles/{self.custom.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(StreamProfile.objects.filter(pk=self.custom.pk).exists())

        response = self.client.delete(f"/api/core/streamprofiles/{self.base.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(StreamProfile.objects.filter(pk=self.base.pk).exists())

    def test_case_insensitive_reference_blocks_delete(self):
        StreamProfile.objects.create(
            name="Lower",
            command="ffmpeg",
            parameters="-x {streamProfile=base}",
        )
        response = self.client.delete(f"/api/core/streamprofiles/{self.base.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Lower", str(response.data))

    def test_unreferenced_profile_still_deletes(self):
        other = StreamProfile.objects.create(
            name="Unrelated", command="ffmpeg", parameters="-c copy"
        )
        response = self.client.delete(f"/api/core/streamprofiles/{other.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(StreamProfile.objects.filter(pk=other.pk).exists())
