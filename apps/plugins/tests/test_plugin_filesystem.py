import os
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.plugins.filesystem import make_filesystem_context


class PluginFilesystemTests(SimpleTestCase):
    def test_lazy_creation_and_restricted_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            logos = base / "logos"
            calls = []
            api = make_filesystem_context(str(data), calls.append, {"logos": str(logos)})
            self.assertFalse(logos.exists())
            self.assertEqual(api["ensure_directory"]("logos"), str(logos))
            self.assertEqual(api["ensure_directory"]("logos"), str(logos))
            snapshot = logos / "snapshot"
            snapshot.mkdir()
            (snapshot / "file").write_text("data")
            api["remove_directory"](snapshot)
            self.assertFalse(snapshot.exists())
            self.assertEqual(calls, [True, True, True])
            with self.assertRaises(ValueError):
                api["remove_directory"](logos)
            with self.assertRaises(ValueError):
                api["remove_directory"](base / "other")
            with self.assertRaises(ValueError):
                api["remove_directory"]("relative/path")
            with self.assertRaises(FileNotFoundError):
                api["remove_directory"](logos / "missing")
            (logos / "file").write_text("keep")
            with self.assertRaises(OSError):
                api["remove_directory"](logos / "file")

    def test_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            outside = base / "outside"
            data.mkdir()
            outside.mkdir()
            (outside / "keep").mkdir()
            os.symlink(outside, data / "link")
            api = make_filesystem_context(str(data), lambda shared: None, {"logos": str(base / "logos")})
            with self.assertRaises(OSError):
                api["remove_directory"](data / "link" / "keep")
            with self.assertRaises(OSError):
                api["remove_directory"](data / "link")
            self.assertTrue((outside / "keep").exists())

    def test_shared_operations_require_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            def authorize(shared):
                if shared:
                    raise PermissionError("filesystem_write")
            api = make_filesystem_context(tmp, authorize, {"logos": str(Path(tmp).parent / "logos")})
            with self.assertRaises(PermissionError):
                api["ensure_directory"]("logos")
