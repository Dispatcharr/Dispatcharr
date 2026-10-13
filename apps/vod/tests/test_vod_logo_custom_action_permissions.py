"""Custom VOD logo actions must require admin, matching standard destroy."""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.vod.models import VODLogo

User = get_user_model()


class VODLogoCustomActionPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.logo = VODLogo.objects.create(
            name=f"logo-{uuid4().hex[:8]}",
            url=f"http://example.com/{uuid4().hex[:8]}.png",
        )
        self.unused = VODLogo.objects.create(
            name=f"unused-{uuid4().hex[:8]}",
            url=f"http://example.com/unused-{uuid4().hex[:8]}.png",
        )

    def _user(self, level):
        return User.objects.create_user(
            username=f"vod-logo-{level}-{uuid4().hex[:8]}",
            password="pass",
            user_level=level,
        )

    def test_streamer_denied_bulk_delete_and_cleanup(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.STREAMER))
        bulk = self.client.delete(
            "/api/vod/vodlogos/bulk-delete/",
            {"logo_ids": [self.logo.id]},
            format="json",
        )
        cleanup = self.client.post("/api/vod/vodlogos/cleanup/")
        self.assertEqual(bulk.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(cleanup.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(VODLogo.objects.filter(id=self.logo.id).exists())
        self.assertTrue(VODLogo.objects.filter(id=self.unused.id).exists())

    def test_standard_user_denied_bulk_delete_and_cleanup(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.STANDARD))
        bulk = self.client.delete(
            "/api/vod/vodlogos/bulk-delete/",
            {"logo_ids": [self.logo.id]},
            format="json",
        )
        cleanup = self.client.post("/api/vod/vodlogos/cleanup/")
        self.assertEqual(bulk.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(cleanup.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(VODLogo.objects.filter(id=self.logo.id).exists())
        self.assertTrue(VODLogo.objects.filter(id=self.unused.id).exists())

    def test_admin_can_bulk_delete_and_cleanup(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.ADMIN))
        bulk = self.client.delete(
            "/api/vod/vodlogos/bulk-delete/",
            {"logo_ids": [self.logo.id]},
            format="json",
        )
        self.assertEqual(bulk.status_code, status.HTTP_200_OK)
        self.assertFalse(VODLogo.objects.filter(id=self.logo.id).exists())

        cleanup = self.client.post("/api/vod/vodlogos/cleanup/")
        self.assertEqual(cleanup.status_code, status.HTTP_200_OK)
        self.assertFalse(VODLogo.objects.filter(id=self.unused.id).exists())
