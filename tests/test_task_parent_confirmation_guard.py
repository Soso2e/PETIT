from __future__ import annotations

import unittest
from unittest.mock import patch

from backend import agent_runtime, tools
from backend.tools import task_hierarchy as task_hierarchy_tool


class TaskParentConfirmationGuardTests(unittest.TestCase):
    def test_update_task_rejects_parent_argument_before_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown arguments for update_task: parent_task_id"):
            tools.parse_arguments(
                "update_task",
                {
                    "task_id": 136,
                    "title": "ROOMIES/歩くアニメーションを追加",
                    "parent_task_id": 135,
                },
            )

    def test_confirm_write_keeps_digit_string_id_compatibility(self) -> None:
        parsed = tools.parse_arguments(
            "update_task",
            {
                "task_id": "136",
                "title": "ROOMIES/歩くアニメーションを追加",
            },
        )
        self.assertEqual(parsed["task_id"], "136")

    def test_set_task_parent_accepts_compatibility_ids_and_title(self) -> None:
        parsed = tools.parse_arguments(
            "set_task_parent",
            {
                "id": 136,
                "parent_id": 135,
                "title": "ROOMIES/歩くアニメーションを追加",
            },
        )
        self.assertEqual(parsed["id"], 136)
        self.assertEqual(parsed["parent_id"], 135)
        self.assertEqual(parsed["title"], "ROOMIES/歩くアニメーションを追加")

    def test_tool_descriptions_assign_parent_changes_to_set_task_parent(self) -> None:
        schemas = {
            item["function"]["name"]: item["function"]
            for item in tools.openai_tools_schema()
        }
        self.assertIn("親子変更にはset_task_parentを使う", schemas["update_task"]["description"])
        self.assertIn("update_taskではなく必ずこのToolを使う", schemas["set_task_parent"]["description"])
        self.assertIn("確認はRuntimeが一度だけ表示する", schemas["set_task_parent"]["description"])

    def test_runtime_detects_manual_write_confirmation(self) -> None:
        self.assertTrue(agent_runtime._is_manual_write_confirmation("この内容で実行しますか？"))
        self.assertTrue(agent_runtime._is_manual_write_confirmation("この内容で更新してもいいですか？"))
        self.assertFalse(agent_runtime._is_manual_write_confirmation("どのタスクを変更しますか？"))

    def test_set_task_parent_has_readable_runtime_confirmation(self) -> None:
        confirmation = agent_runtime._confirmation_text(
            "set_task_parent",
            {
                "task_id": 136,
                "parent_task_id": 135,
                "title": "ROOMIES/歩くアニメーションを追加",
            },
        )
        self.assertIn("操作: タスクの親子関係を変更", confirmation)
        self.assertEqual(confirmation.count("この内容で実行しますか？"), 1)

    def test_parent_and_title_change_share_one_confirmed_tool(self) -> None:
        child = {"id": 136, "title": "歩くアニメーションを追加", "source": "local"}
        parent = {"id": 135, "title": "ROOMIES", "source": "local"}
        title_result = {
            "updated": True,
            "source": "local",
            "task": {**child, "title": "ROOMIES/歩くアニメーションを追加"},
        }
        parent_result = {
            "updated": True,
            "source": "local",
            "task": {**child, "parent_task_id": 135},
            "parent": {"id": 135, "title": "ROOMIES"},
        }

        with (
            patch.object(task_hierarchy_tool.task_hierarchy, "_find_task", return_value=child),
            patch.object(task_hierarchy_tool.task_hierarchy, "_resolve_parent", return_value=parent),
            patch.object(task_hierarchy_tool.task_hierarchy, "_validate_parent", return_value=None),
            patch.object(task_hierarchy_tool.tasks_phase2, "update_task", return_value=title_result) as update_task,
            patch.object(
                task_hierarchy_tool.task_hierarchy,
                "set_task_parent",
                return_value=parent_result,
            ) as set_parent,
        ):
            result = task_hierarchy_tool.set_task_parent_tool(
                id=136,
                parent_id=135,
                title="ROOMIES/歩くアニメーションを追加",
            )

        self.assertTrue(result["updated"])
        self.assertTrue(result["title_updated"])
        update_task.assert_called_once_with(
            task_id=136,
            title="ROOMIES/歩くアニメーションを追加",
        )
        set_parent.assert_called_once_with(
            task_id=136,
            parent_task_id=135,
            parent_title_query=None,
            move_to_life=False,
        )


if __name__ == "__main__":
    unittest.main()
