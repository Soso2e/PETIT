import json
import unittest
from unittest.mock import patch

from backend import task_list_api


def body(response):
    return json.loads(response.body.decode("utf-8"))


class TaskChildApiTests(unittest.TestCase):
    def test_create_child_adds_and_links_task(self) -> None:
        parent = {
            "id": 1,
            "title": "PETIT開発",
            "source": "local",
            "area": "personal",
            "external_id": None,
            "parent_task_id": None,
            "parent_external_id": None,
        }
        child = {"id": 2, "title": "Today UIを直す", "source": "local"}
        linked = {
            "updated": True,
            "source": "local",
            "sync_status": "synced",
            "task": {**child, "parent_task_id": 1},
        }
        with (
            patch.object(task_list_api.config, "notion_configured", return_value=False),
            patch.object(task_list_api.task_hierarchy, "_find_task", side_effect=[parent, child]),
            patch.object(
                task_list_api,
                "_create_task_record",
                return_value={"created": True, "source": "local", "task": child},
            ) as creator,
            patch.object(task_list_api.task_hierarchy, "set_task_parent", return_value=linked) as setter,
        ):
            response = task_list_api.create_child_task(
                1,
                task_list_api.ChildTaskCreate(title="Today UIを直す", priority="High"),
            )

        payload = body(response)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(payload["created"])
        self.assertTrue(payload["linked"])
        self.assertEqual(payload["parent"]["title"], "PETIT開発")
        creator.assert_called_once_with(
            title="Today UIを直す",
            due_date=None,
            priority="High",
            area="personal",
            reason=None,
        )
        setter.assert_called_once_with(task_id=2, parent_task_id=1)

    def test_child_cannot_be_used_as_parent(self) -> None:
        parent = {
            "id": 2,
            "title": "子タスク",
            "source": "local",
            "parent_task_id": 1,
            "parent_external_id": None,
        }
        with patch.object(task_list_api.task_hierarchy, "_find_task", return_value=parent):
            response = task_list_api.create_child_task(
                2,
                task_list_api.ChildTaskCreate(title="孫タスク"),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Life直下", body(response)["error"])

    def test_priority_is_validated_before_creation(self) -> None:
        parent = {
            "id": 1,
            "title": "親Task",
            "source": "local",
            "external_id": None,
            "parent_task_id": None,
            "parent_external_id": None,
        }
        with (
            patch.object(task_list_api.config, "notion_configured", return_value=False),
            patch.object(task_list_api.task_hierarchy, "_find_task", return_value=parent),
            patch.object(task_list_api, "_create_task_record") as creator,
        ):
            response = task_list_api.create_child_task(
                1,
                task_list_api.ChildTaskCreate(title="小タスク", priority="Urgent"),
            )
        self.assertEqual(response.status_code, 400)
        creator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
