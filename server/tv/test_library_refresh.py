import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("refresh", Path(__file__).with_name("library-refresh.py"))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def task(status="Completed", state="Idle", start=100):
    return {"State": state, "LastExecutionResult": {"Status": status,
            "StartTimeUtc": datetime.fromtimestamp(start, timezone.utc).isoformat()}}


class LibraryRefresh(unittest.TestCase):
    def test_initial_and_changed_library_request_scan(self):
        self.assertTrue(r.advance({}, "new", task(), 200)[1])
        self.assertTrue(r.advance({"scanned": "old"}, "new", task(), 200)[1])

    def test_unchanged_library_does_not_scan(self):
        self.assertFalse(r.advance({"scanned": "same"}, "same", task(), 200)[1])

    def test_request_is_not_mistaken_for_finished_scan(self):
        state = {"pending": {"fingerprint": "new", "requestedAt": 200}}
        updated, request = r.advance(state, "new", task(start=100), 220)
        self.assertIn("pending", updated)
        self.assertNotIn("scanned", updated)
        self.assertFalse(request)

    def test_running_scan_is_not_repeated(self):
        state = {"pending": {"fingerprint": "new", "requestedAt": 200}}
        self.assertFalse(r.advance(state, "new", task(state="Running", start=200), 250)[1])

    def test_completion_records_scanned_fingerprint(self):
        state = {"pending": {"fingerprint": "new", "requestedAt": 200}}
        updated, request = r.advance(state, "new", task(start=201), 250)
        self.assertEqual(updated["scanned"], "new")
        self.assertNotIn("pending", updated)
        self.assertFalse(request)

    def test_import_during_scan_requires_second_scan(self):
        state = {"pending": {"fingerprint": "old", "requestedAt": 200}}
        updated, request = r.advance(state, "new", task(start=201), 250)
        self.assertEqual(updated["scanned"], "old")
        self.assertTrue(request)

    def test_failed_or_unstarted_scan_is_retried(self):
        state = {"pending": {"fingerprint": "new", "requestedAt": 200}}
        for current, now in [(task(status="Failed", start=201), 250), (task(start=100), 501)]:
            updated, request = r.advance(state, "new", current, now)
            self.assertTrue(request)
            self.assertNotIn("scanned", updated)

    def test_snapshot_detects_imports_without_reading_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, count = r.snapshot(root)
            (root / "Show S01E01.mkv").write_bytes(b"episode")
            changed, count = r.snapshot(root)
            self.assertNotEqual(original, changed)
            self.assertEqual(count, 1)
            (root / "note.txt").write_text("ignore")
            self.assertEqual(r.snapshot(root)[0], changed)
            (root / "link.mkv").symlink_to(root / "Show S01E01.mkv")
            self.assertEqual(r.snapshot(root)[1], 1)


if __name__ == "__main__":
    unittest.main()
