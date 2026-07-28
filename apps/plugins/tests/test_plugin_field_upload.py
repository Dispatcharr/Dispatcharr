"""PluginFieldUploadAPIView must never let an upload escape its per-field
directory, exceed size/extension limits, or land against an undeclared field.

Writes are scoped to <plugins_dir>/<key>/uploads/<field_id>/ specifically so a
malicious or buggy request can never reach plugin.py/plugin.json/__init__.py.
"""

import os
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.plugins.api_views import PluginFieldUploadAPIView
from apps.plugins.loader import LoadedPlugin, PluginManager


class PluginFieldUploadAPIViewTests(TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="dispatcharr-plugin-uploads-")
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)

        User = get_user_model()
        self.admin = User.objects.create_user(
            username="plugin_upload_admin", password="x", user_level=User.UserLevel.ADMIN
        )
        self.standard = User.objects.create_user(
            username="plugin_upload_user", password="x", user_level=User.UserLevel.STANDARD
        )

        self.factory = APIRequestFactory()
        self.plugin = LoadedPlugin(
            key="my-plugin",
            name="My Plugin",
            fields=[{"id": "logo", "type": "file"}, {"id": "tiny", "type": "file", "max_size": 10}],
        )

        pm = PluginManager()
        pm.plugins_dir = self._tmpdir
        self._pm_patcher = patch.object(PluginManager, "get", return_value=pm)
        self._pm_patcher.start()
        self.addCleanup(self._pm_patcher.stop)
        self.pm = pm
        self._get_plugin_patcher = patch.object(pm, "get_plugin", return_value=self.plugin)
        self._get_plugin_patcher.start()
        self.addCleanup(self._get_plugin_patcher.stop)

    def _post(self, user, field_id, upload):
        request = self.factory.post(
            f"/api/plugins/plugins/{self.plugin.key}/fields/{field_id}/upload/",
            {"file": upload},
            format="multipart",
        )
        force_authenticate(request, user=user)
        return PluginFieldUploadAPIView.as_view()(request, key=self.plugin.key, field_id=field_id)

    def _dest_dir(self, field_id):
        return os.path.join(self._tmpdir, self.plugin.key, "uploads", field_id)

    def test_standard_user_forbidden(self):
        upload = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
        response = self._post(self.standard, "logo", upload)
        self.assertEqual(response.status_code, 403)

    def test_disallowed_extension_is_rejected(self):
        upload = SimpleUploadedFile("payload.exe", b"MZ...", content_type="application/octet-stream")
        response = self._post(self.admin, "logo", upload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertFalse(os.path.isdir(self._dest_dir("logo")))

    def test_oversized_file_is_rejected(self):
        # field "tiny" declares max_size=10, well under any allowed content.
        upload = SimpleUploadedFile("small.txt", b"x" * 11, content_type="text/plain")
        response = self._post(self.admin, "tiny", upload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("too large", response.data["error"])

    def test_undeclared_field_id_is_rejected(self):
        upload = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
        response = self._post(self.admin, "not-a-real-field", upload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])

    def test_traversal_filename_is_contained_to_dest_dir(self):
        upload = SimpleUploadedFile("../../../evil.txt", b"hello", content_type="text/plain")
        response = self._post(self.admin, "logo", upload)
        self.assertEqual(response.status_code, 200)
        dest_dir = self._dest_dir("logo")
        written_path = response.data["path"]
        self.assertTrue(
            os.path.abspath(written_path).startswith(os.path.abspath(dest_dir) + os.sep)
        )
        self.assertEqual(os.listdir(dest_dir), ["evil.txt"])
        self.assertFalse(os.path.exists(os.path.join(self._tmpdir, "evil.txt")))

    def test_valid_upload_replaces_previous_file_for_that_field(self):
        first = SimpleUploadedFile("first.txt", b"one", content_type="text/plain")
        response = self._post(self.admin, "logo", first)
        self.assertEqual(response.status_code, 200)

        second = SimpleUploadedFile("second.txt", b"two", content_type="text/plain")
        response = self._post(self.admin, "logo", second)
        self.assertEqual(response.status_code, 200)

        dest_dir = self._dest_dir("logo")
        self.assertEqual(os.listdir(dest_dir), ["second.txt"])
        with open(response.data["path"], "rb") as f:
            self.assertEqual(f.read(), b"two")
