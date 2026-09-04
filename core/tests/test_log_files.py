"""Tests for the log file browsing endpoints (System > Logs)."""

import os
import time
import shutil
import tempfile
from unittest import mock

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
        for extra in ("collector.conf", "collector.pid"):
            with open(os.path.join(self.log_dir, extra), "w") as f:
                f.write("x")
        response = self.client.get("/api/core/logs/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["path"], self.log_dir)
        names = {f["name"] for f in payload["files"]}
        self.assertEqual(names, {"dispatcharr.log", "dispatcharr.log.1"})
        for entry in payload["files"]:
            self.assertGreater(entry["size"], 0)
            self.assertIn("T", entry["modified"])  # ISO timestamp

    def test_list_reports_whether_anything_is_writing_these_files(self):
        response = self.client.get("/api/core/logs/")
        self.assertFalse(response.json()["collector_running"])

    def test_view_returns_plain_text(self):
        response = self.client.get("/api/core/logs/dispatcharr.log/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        self.assertEqual(response.content, b"line one\nline two\n")
        self.assertEqual(response["X-Log-Truncated"], "0")

    def test_view_truncates_large_files_at_line_boundary(self):
        big = os.path.join(self.log_dir, "dispatcharr.log.big")
        line = b"x" * 99 + b"\n"
        with open(big, "wb") as f:
            for _ in range((log_files.MAX_VIEW_BYTES // 100) + 100):
                f.write(line)
        response = self.client.get("/api/core/logs/dispatcharr.log.big/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Log-Truncated"], "1")
        self.assertLessEqual(len(response.content), log_files.MAX_VIEW_BYTES)
        # Line-boundary start: content begins with a full line
        self.assertTrue(response.content.startswith(b"x"))
        self.assertEqual(len(response.content) % 100, 0)

    def test_view_sizes_the_open_handle_not_the_path(self):
        """A rotation between sizing and reading must not empty the view."""
        live = os.path.join(self.log_dir, "dispatcharr.log")
        with open(live, "wb") as f:
            f.write(b"old\n" * 500)

        real_open = open

        def rotating_open(path, *args, **kwargs):
            # Rotate exactly once, the way the collector does, as the view opens.
            if path == live and not getattr(rotating_open, "fired", False):
                rotating_open.fired = True
                os.replace(live, live + ".9")
                with real_open(live, "wb") as fresh:
                    fresh.write(b"new\n")
            return real_open(path, *args, **kwargs)

        with mock.patch.object(log_files, "MAX_VIEW_BYTES", 100), mock.patch(
            "core.log_files.open", rotating_open, create=True
        ):
            response = self.client.get("/api/core/logs/dispatcharr.log/")

        self.assertEqual(response.status_code, 200)
        # Sized from the handle: the fresh file is served whole, not seeked past.
        self.assertEqual(response.content, b"new\n")
        self.assertEqual(response["X-Log-Truncated"], "0")

    def test_cursor_returns_only_bytes_written_since(self):
        live = os.path.join(self.log_dir, "dispatcharr.log")
        first = self.client.get("/api/core/logs/dispatcharr.log/")
        self.assertEqual(first["X-Log-Reset"], "1")
        with open(live, "a") as f:
            f.write("line three\n")

        second = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": first["X-Log-Cursor"]}
        )
        self.assertEqual(second["X-Log-Reset"], "0")
        self.assertEqual(second.content, b"line three\n")

    def test_cursor_withholds_a_line_still_being_written(self):
        live = os.path.join(self.log_dir, "dispatcharr.log")
        first = self.client.get("/api/core/logs/dispatcharr.log/")
        with open(live, "a") as f:
            f.write("complete\npartial-so-far")

        second = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": first["X-Log-Cursor"]}
        )
        # The fragment is held back; the cursor stays in front of it.
        self.assertEqual(second.content, b"complete\n")

        with open(live, "a") as f:
            f.write("-and-the-rest\n")
        third = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": second["X-Log-Cursor"]}
        )
        self.assertEqual(third.content, b"partial-so-far-and-the-rest\n")

    def test_cursor_from_a_rotated_file_resets_instead_of_skipping(self):
        """A stale offset must not be resumed against a different inode."""
        live = os.path.join(self.log_dir, "dispatcharr.log")
        first = self.client.get("/api/core/logs/dispatcharr.log/")

        # The collector's rotation, then a new file grown past the old offset.
        os.replace(live, live + ".9")
        with open(live, "w") as f:
            f.write("fresh one\nfresh two\nfresh three\n")

        second = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": first["X-Log-Cursor"]}
        )
        self.assertEqual(second["X-Log-Reset"], "1")
        # Every line of the new file, not the slice past a meaningless offset.
        self.assertEqual(
            second.content, b"fresh one\nfresh two\nfresh three\n"
        )

    def test_cursor_beyond_a_gap_falls_back_to_the_tail(self):
        """A tab that slept must not be handed more than the view cap."""
        live = os.path.join(self.log_dir, "dispatcharr.log")
        first = self.client.get("/api/core/logs/dispatcharr.log/")
        with open(live, "ab") as f:
            f.write((b"x" * 99 + b"\n") * 40)

        with mock.patch.object(log_files, "MAX_VIEW_BYTES", 1000):
            response = self.client.get(
                "/api/core/logs/dispatcharr.log/",
                {"cursor": first["X-Log-Cursor"]},
            )
        self.assertEqual(response["X-Log-Truncated"], "1")
        self.assertEqual(response["X-Log-Reset"], "1")
        self.assertLessEqual(len(response.content), 1000)

    def test_cursor_is_ignored_when_malformed(self):
        for bad in ("", "garbage", "12-", "-5", "abc-def"):
            response = self.client.get(
                "/api/core/logs/dispatcharr.log/", {"cursor": bad}
            )
            self.assertEqual(response.status_code, 200, bad)
            self.assertEqual(response["X-Log-Reset"], "1", bad)
            self.assertEqual(response.content, b"line one\nline two\n", bad)

    def test_download_sets_attachment_disposition(self):
        response = self.client.get("/api/core/logs/dispatcharr.log/download/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(
            b"".join(response.streaming_content), b"line one\nline two\n"
        )

    def test_endpoints_serve_only_the_log_family(self):
        # DISPATCHARR_LOG_DIR may point at a data root; view and download are not a file server.
        with open(os.path.join(self.log_dir, "secrets.env"), "w") as f:
            f.write("nothing to see")
        self.assertEqual(
            self.client.get("/api/core/logs/secrets.env/").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/core/logs/secrets.env/download/").status_code, 404
        )

    def test_download_requires_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.get("/api/core/logs/dispatcharr.log/download/")
        self.assertEqual(response.status_code, 401)

    def test_resolver_rejects_traversal_and_dotfiles(self):
        # A traversal URL never reaches this view; it decodes to a slashed path the SPA serves.
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
        fd, outside = tempfile.mkstemp(prefix="dispatcharr-escape-")
        os.close(fd)
        self.addCleanup(os.remove, outside)
        os.symlink(outside, os.path.join(self.log_dir, "escape.log"))
        self.assertIsNone(log_files._resolve("escape.log"))

    def test_list_excludes_symlink_escape(self):
        fd, outside = tempfile.mkstemp(prefix="dispatcharr-escape-")
        os.close(fd)
        self.addCleanup(os.remove, outside)
        os.symlink(outside, os.path.join(self.log_dir, "escape.log"))
        response = self.client.get("/api/core/logs/")
        self.assertEqual(response.status_code, 200)
        names = {f["name"] for f in response.json()["files"]}
        self.assertNotIn("escape.log", names)
        self.assertEqual(names, {"dispatcharr.log", "dispatcharr.log.1"})

    def test_traversal_name_that_reaches_the_view_is_404(self):
        # Only slash-free names route here, so this is the closest a URL gets.
        secret = os.path.join(self.log_dir, os.pardir, "secret.txt")
        with open(secret, "w") as f:
            f.write("TOP SECRET")
        self.addCleanup(os.remove, secret)
        response = self.client.get("/api/core/logs/.hidden/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"TOP SECRET", response.content)

    def test_missing_file_is_404(self):
        response = self.client.get("/api/core/logs/nope.log/")
        self.assertEqual(response.status_code, 404)

    def test_non_admin_is_forbidden(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get("/api/core/logs/").status_code, 403)
        self.assertEqual(
            self.client.get("/api/core/logs/dispatcharr.log/").status_code, 403
        )

    def test_anonymous_is_unauthorized(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/api/core/logs/").status_code, (401, 403))
