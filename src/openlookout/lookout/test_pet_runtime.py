import json
import tempfile
import unittest
from pathlib import Path

from lookout.pet_runtime import Inbox, snapshot_events


class TestInbox(unittest.TestCase):
    def test_feedback_and_snooze_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            inbox = Inbox(home)
            item = {"id": "assist-1", "title": "候选"}
            inbox.merge({"assist_candidates": [item], "branch_candidates": []})

            self.assertEqual(inbox.pending(now=100), [item])
            inbox.feedback("assist-1", "later", now=100)
            self.assertEqual(inbox.pending(now=100), [])
            self.assertEqual(inbox.pending(now=3700), [item])

            inbox.feedback("assist-1", "already_known", now=3700)
            self.assertEqual(inbox.pending(now=3700), [])
            self.assertEqual(inbox.pending(now=3700 + 14400), [item])
            saved = json.loads((home / "inbox.json").read_text(encoding="utf-8"))["assist-1"]
            self.assertEqual(saved["action"], "reviewed")
            self.assertEqual(saved["last_feedback"], "already_known")

    def test_rule_draft_deduplicates_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Inbox(Path(directory))
            inbox.remember("先跑测试", "当前项目")
            inbox.remember("先跑测试", "当前项目")
            path = inbox.export_rules()
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("先跑测试"), 1)
            self.assertIn("## 当前项目", text)


class TestSnapshotEvents(unittest.TestCase):
    def test_snapshot_keeps_latest_valid_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "events.jsonl"
            rows = [{"ts": str(index), "type": "focus", "title": str(index)} for index in range(5)]
            source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            destination = root / "capture"

            result = snapshot_events(source, destination, limit=2)

            self.assertEqual(result["events"], 2)
            self.assertTrue(result["window_limited"])
            saved = [json.loads(line) for line in (destination / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["title"] for row in saved], ["3", "4"])


if __name__ == "__main__":
    unittest.main()
