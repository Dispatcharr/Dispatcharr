"""Tests for the log file browsing endpoints (System > Logs)."""

import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core import log_files


class LogFilesEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user(
            username="log-admin", password="x", user_level=10
        )
        cls.viewer = User.objects.create_user(
            username="log-viewer", password="x", user_level=0
        )

    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="dispatcharr-logs-")
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)
        with open(os.path.join(self.log_dir, "dispatcharr.log"), "w") as f:
            f.write("line one\nline two\n")
        with open(os.path.join(self.log_dir, "dispatcharr.log.1"), "w") as f:
            f.write("old run\n")
        self.settings_override = override_settings(LOG_FILE_DIR=self.log_dir)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_lists_log_files_with_metadata(self):
        response = self.client.get("/api/core/logs/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["path"], self.log_dir)
        names = {f["name"] for f in payload["files"]}
        self.assertEqual(names, {"dispatcharr.log", "dispatcharr.log.1"})
        for entry in payload["files"]:
            self.assertGreater(entry["size"], 0)
            self.assertIn("T", entry["modified"])  # ISO timestamp

    def test_view_returns_plain_text(self):
        response = self.client.get("/api/core/logs/dispatcharr.log/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        self.assertEqual(response.content, b"line one\nline two\n")
        self.assertEqual(response["X-Log-Truncated"], "0")

    def test_view_truncates_large_files_at_line_boundary(self):
        big = os.path.join(self.log_dir, "big.log")
        line = b"x" * 99 + b"\n"
        with open(big, "wb") as f:
            for _ in range((log_files.MAX_VIEW_BYTES // 100) + 100):
                f.write(line)
        response = self.client.get("/api/core/logs/big.log/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Log-Truncated"], "1")
        self.assertLessEqual(len(response.content), log_files.MAX_VIEW_BYTES)
        # Line-boundary start: content begins with a full line
        self.assertTrue(response.content.startswith(b"x"))
        self.assertEqual(len(response.content) % 100, 0)

    def test_download_sets_attachment_disposition(self):
        # Admin fallback (no token) streams the whole file as an attachment.
        response = self.client.get("/api/core/logs/dispatcharr.log/download/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(
            b"".join(response.streaming_content), b"line one\nline two\n"
        )

    def test_admin_gets_token_then_downloads_with_it(self):
        token_response = self.client.get(
            "/api/core/logs/dispatcharr.log/download-token/"
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]
        self.assertTrue(token)

        # A plain link carries the token but no JWT (anonymous client).
        self.client.force_authenticate(None)
        response = self.client.get(
            f"/api/core/logs/dispatcharr.log/download/?token={token}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(
            b"".join(response.streaming_content), b"line one\nline two\n"
        )

    def test_download_with_bad_token_is_forbidden(self):
        self.client.force_authenticate(None)
        response = self.client.get(
            "/api/core/logs/dispatcharr.log/download/?token=deadbeef"
        )
        self.assertEqual(response.status_code, 403)

    def test_download_without_token_or_auth_is_unauthorized(self):
        self.client.force_authenticate(None)
        response = self.client.get("/api/core/logs/dispatcharr.log/download/")
        self.assertEqual(response.status_code, 401)

    def test_resolver_rejects_traversal_and_dotfiles(self):
        # _resolve rejects anything path-like/hidden; a traversal URL itself never reaches this view -- it percent-decodes to a slashed path served by the SPA catch-all.
        self.assertIsNone(log_files._resolve("../secret.txt"))
        self.assertIsNone(log_files._resolve("..%2f..%2fetc%2fpasswd"))
        self.assertIsNone(log_files._resolve("/etc/passwd"))
        self.assertIsNone(log_files._resolve(".hidden"))
        self.assertIsNone(log_files._resolve("sub/dir.log"))
        self.assertEqual(
            log_files._resolve("dispatcharr.log"),
            os.path.realpath(os.path.join(self.log_dir, "dispatcharr.log")),
        )

    def test_resolver_rejects_symlink_escape(self):
        # A symlink with a valid name but an out-of-dir target must not resolve -- realpath() follows it out, so the containment check rejects it.
        fd, outside = tempfile.mkstemp(prefix="dispatcharr-escape-")
        os.close(fd)
        self.addCleanup(os.remove, outside)
        os.symlink(outside, os.path.join(self.log_dir, "escape.log"))
        self.assertIsNone(log_files._resolve("escape.log"))

    def test_traversal_url_never_serves_out_of_dir_files(self):
        secret = os.path.join(self.log_dir, os.pardir, "secret.txt")
        with open(secret, "w") as f:
            f.write("TOP SECRET")
        self.addCleanup(os.remove, secret)
        for name in ("..", "%2e%2e%2fsecret.txt", ".hidden"):
            response = self.client.get(f"/api/core/logs/{name}/")
            body = getattr(response, "content", b"")
            self.assertNotIn(b"TOP SECRET", body, name)

    def test_missing_file_is_404(self):
        response = self.client.get("/api/core/logs/nope.log/")
        self.assertEqual(response.status_code, 404)

    def test_non_admin_is_forbidden(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get("/api/core/logs/").status_code, 403)
        self.assertEqual(
            self.client.get("/api/core/logs/dispatcharr.log/").status_code, 403
        )

    def test_non_admin_download_token_is_forbidden(self):
        # Minting a download token is admin-only (IsAdmin).
        self.client.force_authenticate(self.viewer)
        response = self.client.get(
            "/api/core/logs/dispatcharr.log/download-token/"
        )
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_unauthorized(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/api/core/logs/").status_code, (401, 403))
