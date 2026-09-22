"""Tests for the optional DVR storage-root override.

Every install that never touches dvr_settings.storage_root must behave
byte-for-byte identically to before this feature existed -- these tests
cover that default-unset case plus the override case, and confirm a file
under EITHER root (the compiled-in default, or whichever custom root is
currently configured) stays resolvable, so changing the setting can never
strand a recording made under a previously-active root.
"""
import uuid
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.channels.api_views import (
    _resolve_recording_storage_path,
    dvr_storage_allowed_roots,
)
from core.models import CoreSettings, DEFAULT_DVR_STORAGE_ROOT


class DvrStorageRootSettingTests(SimpleTestCase):
    @patch.object(CoreSettings, "get_dvr_settings")
    def test_default_when_unset(self, mock_settings):
        mock_settings.return_value = {}
        self.assertEqual(CoreSettings.get_dvr_storage_root(), DEFAULT_DVR_STORAGE_ROOT)

    @patch.object(CoreSettings, "get_dvr_settings")
    def test_default_when_blank(self, mock_settings):
        mock_settings.return_value = {"storage_root": ""}
        self.assertEqual(CoreSettings.get_dvr_storage_root(), DEFAULT_DVR_STORAGE_ROOT)

    @patch.object(CoreSettings, "get_dvr_settings")
    def test_default_when_whitespace_only(self, mock_settings):
        mock_settings.return_value = {"storage_root": "   "}
        self.assertEqual(CoreSettings.get_dvr_storage_root(), DEFAULT_DVR_STORAGE_ROOT)

    @patch.object(CoreSettings, "get_dvr_settings")
    def test_custom_root_honored(self, mock_settings):
        mock_settings.return_value = {"storage_root": "/mnt/dvr"}
        self.assertEqual(CoreSettings.get_dvr_storage_root(), "/mnt/dvr")


class DvrStorageAllowedRootsTests(SimpleTestCase):
    @patch.object(CoreSettings, "get_dvr_storage_root")
    def test_only_default_when_not_overridden(self, mock_root):
        mock_root.return_value = DEFAULT_DVR_STORAGE_ROOT
        self.assertEqual(dvr_storage_allowed_roots(), (DEFAULT_DVR_STORAGE_ROOT,))

    @patch.object(CoreSettings, "get_dvr_storage_root")
    def test_both_roots_when_overridden(self, mock_root):
        mock_root.return_value = "/mnt/dvr"
        roots = dvr_storage_allowed_roots()
        self.assertIn(DEFAULT_DVR_STORAGE_ROOT, roots)
        self.assertIn("/mnt/dvr", roots)


class DvrStorageRootChangeDoesNotStrandOldFilesTests(SimpleTestCase):
    """A recording made under the default root must stay resolvable/servable
    even after an admin later switches to a custom root -- nothing physically
    moves when the setting changes, so the allowlist can't just track
    "whatever is configured right now"."""

    def setUp(self):
        self.default_root = Path(DEFAULT_DVR_STORAGE_ROOT)
        self.default_root.mkdir(parents=True, exist_ok=True)
        self.old_name = f"_pre_override_{uuid.uuid4().hex}.mkv"
        self.old_file = self.default_root / self.old_name
        self.old_file.write_bytes(b"x")

        self.custom_root = Path("/data/_test_custom_dvr_root")
        self.custom_root.mkdir(parents=True, exist_ok=True)
        self.new_name = f"_post_override_{uuid.uuid4().hex}.mkv"
        self.new_file = self.custom_root / self.new_name
        self.new_file.write_bytes(b"x")

    def tearDown(self):
        self.old_file.unlink(missing_ok=True)
        self.new_file.unlink(missing_ok=True)

    @patch.object(CoreSettings, "get_dvr_storage_root")
    def test_old_root_file_still_resolves_after_switching(self, mock_root):
        mock_root.return_value = str(self.custom_root)
        self.assertEqual(
            _resolve_recording_storage_path(str(self.old_file)),
            str(self.old_file.resolve()),
        )

    @patch.object(CoreSettings, "get_dvr_storage_root")
    def test_new_root_file_resolves_once_active(self, mock_root):
        mock_root.return_value = str(self.custom_root)
        self.assertEqual(
            _resolve_recording_storage_path(str(self.new_file)),
            str(self.new_file.resolve()),
        )

    @patch.object(CoreSettings, "get_dvr_storage_root")
    def test_path_outside_either_root_still_rejected(self, mock_root):
        mock_root.return_value = str(self.custom_root)
        self.assertIsNone(_resolve_recording_storage_path("/etc/passwd"))
        self.assertIsNone(
            _resolve_recording_storage_path(f"{self.custom_root}/../../etc/passwd")
        )
