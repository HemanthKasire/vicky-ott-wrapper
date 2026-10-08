import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = load("privileged", "privileged.py")
ott = load("ott_run", "ott-run.py")


class Boundaries(unittest.TestCase):
    def test_privileged_helper_rejects_arbitrary_action(self):
        with patch.object(p.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                p.run({"action": "cleanup-old"})
            run.assert_not_called()

    def test_privileged_helper_rejects_shell_in_command(self):
        with patch.object(p.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                p.run({"action": "stats", "payload": {"command": "status; touch /tmp/unsafe"}})
            run.assert_not_called()

    def test_manual_media_cannot_escape_incoming_via_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            incoming = root / "incoming"
            incoming.mkdir()
            outside = root / "outside.mkv"
            outside.write_bytes(b"test")
            (incoming / "link.mkv").symlink_to(outside)
            with self.assertRaises(ValueError):
                ott.inside(incoming / "link.mkv", incoming)

    def test_manual_publish_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, destination = root / "source.mkv", root / "destination.mkv"
            source.write_bytes(b"new")
            destination.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                ott.publish(source, destination)
            self.assertEqual(destination.read_bytes(), b"existing")
            self.assertEqual(source.read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
