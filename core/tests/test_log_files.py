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
        names = {f["name"] for f in payload["files"]}
        self.assertEqual(names, {"dispatcharr.log", "dispatcharr.log.1"})
        for entry in payload["files"]:
            self.assertGreater(entry["size"], 0)
            self.assertIn("T", entry["modified"])  # ISO timestamp

    def test_list_reports_whether_anything_is_writing_these_files(self):
        response = self.client.get("/api/core/logs/")
        self.assertFalse(response.json()["collector_running"])

    def test_console_only_install_has_no_files(self):
        with override_settings(LOG_FILE_DIR=None):
            listing = self.client.get("/api/core/logs/").json()
            self.assertEqual(listing["files"], [])
            self.assertFalse(listing["collector_running"])
            self.assertEqual(
                self.client.get("/api/core/logs/dispatcharr.log/").status_code, 404
            )

    def test_view_returns_the_tail(self):
        response = self.client.get("/api/core/logs/dispatcharr.log/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["content"], "line one\nline two\n")
        self.assertFalse(payload["truncated"])

    def test_view_truncates_large_files_at_line_boundary(self):
        big = os.path.join(self.log_dir, "dispatcharr.log.big")
        line = b"x" * 99 + b"\n"
        with open(big, "wb") as f:
            for _ in range((log_files.MAX_VIEW_BYTES // 100) + 100):
                f.write(line)
        response = self.client.get("/api/core/logs/dispatcharr.log.big/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["truncated"])
        self.assertLessEqual(len(payload["content"]), log_files.MAX_VIEW_BYTES)
        # Line-boundary start: content begins with a full line
        self.assertTrue(payload["content"].startswith("x"))
        self.assertEqual(len(payload["content"]) % 100, 0)

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
        self.assertEqual(response.json()["content"], "new\n")
        self.assertFalse(response.json()["truncated"])

    def test_cursor_returns_only_bytes_written_since(self):
        live = os.path.join(self.log_dir, "dispatcharr.log")
        first = self.client.get("/api/core/logs/dispatcharr.log/").json()
        self.assertTrue(first["reset"])
        with open(live, "a") as f:
            f.write("line three\n")

        second = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": first["cursor"]}
        ).json()
        self.assertFalse(second["reset"])
        self.assertEqual(second["content"], "line three\n")

    def test_cursor_withholds_a_line_still_being_written(self):
        live = os.path.join(self.log_dir, "dispatcharr.log")
        with open(live, "a") as f:
            f.write("complete\npartial-so-far")
        first = self.client.get("/api/core/logs/dispatcharr.log/").json()
        # The fragment is held back; the cursor stays in front of it.
        self.assertEqual(first["content"], "line one\nline two\ncomplete\n")

        with open(live, "a") as f:
            f.write("-and-the-rest\n")
        second = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": first["cursor"]}
        ).json()
        self.assertFalse(second["reset"])
        self.assertEqual(second["content"], "partial-so-far-and-the-rest\n")

    def test_cursor_from_a_rotated_file_resets_instead_of_skipping(self):
        """A stale offset must not be resumed against a different inode."""
        live = os.path.join(self.log_dir, "dispatcharr.log")
        first = self.client.get("/api/core/logs/dispatcharr.log/").json()

        # The collector's rotation, then a new file grown past the old offset.
        os.replace(live, live + ".9")
        with open(live, "w") as f:
            f.write("fresh one\nfresh two\nfresh three\n")

        second = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": first["cursor"]}
        ).json()
        self.assertTrue(second["reset"])
        # Every line of the new file, not the slice past a meaningless offset.
        self.assertEqual(second["content"], "fresh one\nfresh two\nfresh three\n")

    def test_cursor_beyond_a_gap_falls_back_to_the_tail(self):
        """A tab that slept must not be handed more than the view cap."""
        live = os.path.join(self.log_dir, "dispatcharr.log")
        first = self.client.get("/api/core/logs/dispatcharr.log/").json()
        with open(live, "ab") as f:
            f.write((b"x" * 99 + b"\n") * 40)

        with mock.patch.object(log_files, "MAX_VIEW_BYTES", 1000):
            payload = self.client.get(
                "/api/core/logs/dispatcharr.log/", {"cursor": first["cursor"]}
            ).json()
        self.assertTrue(payload["truncated"])
        self.assertTrue(payload["reset"])
        self.assertLessEqual(len(payload["content"]), 1000)

    def test_cursor_past_the_end_of_the_same_inode_resets(self):
        """In-place truncation or inode reuse leaves the offset beyond EOF."""
        live = os.path.join(self.log_dir, "dispatcharr.log")
        first = self.client.get("/api/core/logs/dispatcharr.log/").json()
        with open(live, "w") as f:
            f.write("fresh\n")

        second = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": first["cursor"]}
        ).json()
        self.assertTrue(second["reset"])
        self.assertEqual(second["content"], "fresh\n")

    def test_cursor_mid_line_on_the_same_inode_resets(self):
        inode = os.stat(os.path.join(self.log_dir, "dispatcharr.log")).st_ino
        payload = self.client.get(
            "/api/core/logs/dispatcharr.log/", {"cursor": f"{inode}-5"}
        ).json()
        self.assertTrue(payload["reset"])
        self.assertEqual(payload["content"], "line one\nline two\n")

    def test_cursor_is_ignored_when_malformed(self):
        inode = os.stat(os.path.join(self.log_dir, "dispatcharr.log")).st_ino
        bad_cursors = ("", "garbage", "12-", "-5", "abc-def")
        # Characters isdigit() accepts but int() rejects, and int()'s digit limit.
        bad_cursors += (f"{inode}-\u00b2", f"{inode}-" + "9" * 5000)
        for bad in bad_cursors:
            response = self.client.get(
                "/api/core/logs/dispatcharr.log/", {"cursor": bad}
            )
            self.assertEqual(response.status_code, 200, bad)
            self.assertTrue(response.json()["reset"], bad)
            self.assertEqual(response.json()["content"], "line one\nline two\n", bad)

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

    def test_file_pruned_after_resolution_is_404(self):
        with mock.patch(
            "core.log_files.open", side_effect=FileNotFoundError, create=True
        ):
            for name in ("dispatcharr.log/", "dispatcharr.log/download/"):
                url = "/api/core/logs/" + name
                self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_non_admin_is_forbidden(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get("/api/core/logs/").status_code, 403)
        self.assertEqual(
            self.client.get("/api/core/logs/dispatcharr.log/").status_code, 403
        )

    def test_anonymous_is_unauthorized(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/api/core/logs/").status_code, (401, 403))
