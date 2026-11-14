import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, memory_review


class MemoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch.object(config, "DB_PATH", self.root / "petit.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        db.init_db()
        self.state, _ = db.save_memory_item("アクティブなタスクは13件ある", "fact", "auto_episode")
        self.durable, _ = db.save_memory_item("ユーザーの猫の名前はもなか", "fact", "auto_episode")
        self.explicit, _ = db.save_memory_item("コーヒーは浅煎りが好き", "preference", "explicit")
        self.new, _ = db.save_memory_item("ユーザーは朝型で作業する", "preference", "auto_knowledge")
        self.sheet = self.root / "review" / "review.csv"

    def rows(self):
        with db.get_connection() as connection:
            return {row["id"]: row["valid_until"] for row in connection.execute("SELECT id,valid_until FROM memory")}

    def edit(self, actions):
        with self.sheet.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["action"] = actions.get(int(row["id"]), row["action"])
        with self.sheet.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=memory_review.FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_export_lists_only_legacy_automatic_rows_and_changes_nothing(self):
        before = self.rows()
        result = memory_review.export(self.sheet)
        self.assertEqual(result["rows"], 2)
        with self.sheet.open("r", encoding="utf-8-sig", newline="") as handle:
            listed = {int(row["id"]): row["action"] for row in csv.DictReader(handle)}
        self.assertEqual(listed, {self.state: "expire", self.durable: "expire"})
        self.assertEqual(self.rows(), before)

    def test_apply_expires_marked_rows_keeps_the_rest_and_backs_up(self):
        memory_review.export(self.sheet)
        self.edit({self.durable: "keep"})
        self.assertEqual(memory_review.plan(self.sheet),
                         {"expire": [self.state], "keep": [self.durable], "skipped": [], "unlisted": []})
        result = memory_review.apply(self.sheet, self.root / "audit")
        rows = self.rows()
        self.assertEqual(result["applied"], 1)
        self.assertIsNotNone(rows[self.state])
        self.assertEqual([rows[self.durable], rows[self.explicit], rows[self.new]], [None, None, None])
        # Nothing is deleted, and the pre-change database is recoverable.
        self.assertEqual(len(rows), 4)
        backup = sqlite3.connect(result["backup"])
        self.addCleanup(backup.close)
        self.assertIsNone(backup.execute("SELECT valid_until FROM memory WHERE id=?", (self.state,)).fetchone()[0])
        self.assertEqual(json.loads(Path(result["audit"]).read_text(encoding="utf-8"))["rows"],
                         [{"id": self.state, "previous_valid_until": None}])

    def test_rows_changed_after_export_are_skipped_not_guessed(self):
        memory_review.export(self.sheet)
        db.save_memory_item("アクティブなタスクは9件ある", "fact", "explicit", replaces_id=self.state)
        planned = memory_review.plan(self.sheet)
        self.assertEqual(planned["skipped"], [self.state])
        self.assertEqual(planned["expire"], [self.durable])

    def test_invalid_action_stops_before_any_change(self):
        memory_review.export(self.sheet)
        self.edit({self.state: "delete"})
        before = self.rows()
        with self.assertRaises(ValueError):
            memory_review.apply(self.sheet, self.root / "audit")
        self.assertEqual(self.rows(), before)
        self.assertEqual(list(self.root.glob("*.bak")), [])

    def test_restore_undoes_one_apply(self):
        memory_review.export(self.sheet)
        result = memory_review.apply(self.sheet, self.root / "audit")
        self.assertEqual(result["applied"], 2)
        self.assertEqual(memory_review.restore(Path(result["audit"])), {"restored": 2, "listed": 2})
        self.assertEqual(set(self.rows().values()), {None})

    def test_expired_rows_remain_reachable_as_history(self):
        from backend.tools import memory
        memory_review.export(self.sheet)
        memory_review.apply(self.sheet, self.root / "audit")
        with patch("backend.chroma_client.query", return_value=None), \
                patch("backend.vault_indexer.keyword_search", return_value=[]):
            active = memory.search_memory("猫の名前", include_vault=False)
            history = memory.search_memory("猫の名前", include_vault=False, include_inactive=True)
        self.assertEqual(active["memories"], [])
        self.assertEqual([row["id"] for row in history["memories"]], [self.durable])


if __name__ == "__main__":
    unittest.main()
