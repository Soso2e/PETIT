from __future__ import annotations

import unittest
from unittest.mock import patch

from backend import task_hierarchy


class TaskHierarchyIdempotencyTests(unittest.TestCase):
    def test_same_parent_does_not_enqueue_duplicate_notion_update(self) -> None:
        child = {
            "id": 2,
            "title": "子タスク",
            "source": "notion",
            "external_id": "child-page",
            "sync_status": "pending",
        }
        parent = {
            "id": 1,
            "title": "親タスク",
            "source": "notion",
            "external_id": "parent-page",
        }
        with (
            patch.object(task_hierarchy, "install_parent_sync_support"),
            patch.object(task_hierarchy, "_find_task", return_value=child),
            patch.object(task_hierarchy, "_resolve_parent", return_value=parent),
            patch.object(task_hierarchy, "_current_parent_id", return_value=1),
            patch.object(task_hierarchy, "_validate_parent") as validate,
            patch.object(task_hierarchy.task_sync_queue, "enqueue_update") as enqueue,
        ):
            result = task_hierarchy.set_task_parent(task_id=2, parent_task_id=1)

        self.assertTrue(result["updated"])
        self.assertFalse(result["changed"])
        self.assertFalse(result["queued"])
        validate.assert_not_called()
        enqueue.assert_not_called()

    def test_root_to_life_is_an_idempotent_noop(self) -> None:
        root = {"id": 1, "title": "親タスク", "source": "local", "sync_status": "synced"}
        with (
            patch.object(task_hierarchy, "install_parent_sync_support"),
            patch.object(task_hierarchy, "_find_task", return_value=root),
            patch.object(task_hierarchy, "_current_parent_id", return_value=None),
            patch.object(task_hierarchy.task_sync_queue, "enqueue_update") as enqueue,
        ):
            result = task_hierarchy.set_task_parent(task_id=1, move_to_life=True)

        self.assertTrue(result["updated"])
        self.assertFalse(result["changed"])
        enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
