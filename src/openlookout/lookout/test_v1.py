import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lookout.v1 import build_tree


class TestBuildTree(unittest.TestCase):
    def test_windows_permission_error_copies_content(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            source = capture / "document.txt"
            source.write_text("fixture", encoding="utf-8")
            manifest = [{"path": "documents/example.txt", "stored": "document.txt"}]
            (capture / "content_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            error = OSError("symlink privilege unavailable")
            error.winerror = 1314
            with patch.object(Path, "symlink_to", side_effect=error):
                tree, count = build_tree(capture)
            self.assertEqual(count, 1)
            self.assertEqual((tree / "documents/example.txt").read_text(encoding="utf-8"), "fixture")
            self.assertEqual(source.read_text(encoding="utf-8"), "fixture")

    def test_other_errors_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            (capture / "document.txt").write_text("fixture", encoding="utf-8")
            manifest = [{"path": "example.txt", "stored": "document.txt"}]
            (capture / "content_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(Path, "symlink_to", side_effect=OSError("disk failure")):
                with self.assertRaisesRegex(OSError, "disk failure"):
                    build_tree(capture)


if __name__ == "__main__":
    unittest.main()
