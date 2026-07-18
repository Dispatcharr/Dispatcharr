"""EPG upload path safety and admin-only permission."""
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.epg.api_views import EPGSourceViewSet


class EPGUploadSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="epg_upload_admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
        )
        self.standard = User.objects.create_user(
            username="epg_upload_user",
            password="x",
            user_level=User.UserLevel.STANDARD,
        )
        self.factory = APIRequestFactory()

    def _upload(self, user, filename="guide.xml"):
        content = SimpleUploadedFile(
            filename, b"<?xml version='1.0'?><tv></tv>", content_type="application/xml"
        )
        request = self.factory.post(
            "/api/epg/sources/upload/",
            {"file": content, "name": "Uploaded", "source_type": "xmltv"},
            format="multipart",
        )
        force_authenticate(request, user=user)
        view = EPGSourceViewSet.as_view({"post": "upload"})
        return view(request)

    def test_standard_user_forbidden(self):
        response = self._upload(self.standard)
        self.assertEqual(response.status_code, 403)

    @patch("apps.epg.api_views.safe_upload_path", side_effect=ValueError("bad"))
    def test_traversal_filename_rejected(self, _mock):
        response = self._upload(self.admin, filename="../../evil.xml")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid filename", response.data.get("error", ""))
