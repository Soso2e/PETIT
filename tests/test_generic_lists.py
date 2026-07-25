from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, list_conversation, tools


class GenericListConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_get_lists_surfaces_builtin_task_source_and_custom_lists(self) -> None:
        with patch.object(config, "notion_configured", return_value=True):
            created = json.loads(tools.dispatch("create_list", {"name": "アニメリスト"}))
            result = json.loads(tools.dispatch("get_lists", {}))

        self.assertTrue(created["created"])
        self.assertEqual(created["list"]["name"], "アニメ")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["lists"][0]["display_name"], "タスク")
        self.assertEqual(result["lists"][0]["source_label"], "Notion")
        self.assertEqual(result["lists"][1]["display_name"], "アニメリスト")
        self.assertEqual(result["lists"][1]["source_label"], "ローカル")

    def test_create_list_rejects_task_and_duplicate_names(self) -> None:
        task = json.loads(tools.dispatch("create_list", {"name": "タスクリスト"}))
        first = json.loads(tools.dispatch("create_list", {"name": "映画"}))
        duplicate = json.loads(tools.dispatch("create_list", {"name": "映画リスト"}))

        self.assertFalse(task["created"])
        self.assertIn("組み込み", task["error"])
        self.assertTrue(first["created"])
        self.assertFalse(duplicate["created"])
        self.assertTrue(duplicate["duplicate"])

    def test_custom_list_items_can_be_added_and_read(self) -> None:
        created = json.loads(tools.dispatch("create_list", {"name": "アニメ"}))
        list_id = created["list"]["id"]
        added = json.loads(
            tools.dispatch(
                "add_list_item",
                {
                    "list_id": str(list_id),
                    "title": "葬送のフリーレン",
                    "metadata": {"rating": 5},
                },
            )
        )
        result = json.loads(tools.dispatch("get_list_items", {"list_id": str(list_id)}))

        self.assertTrue(added["added"])
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["items"][0]["title"], "葬送のフリーレン")
        self.assertEqual(result["items"][0]["metadata"], {"rating": 5})

    def test_inventory_request_lists_sources_without_model_call(self) -> None:
        with patch.object(config, "notion_configured", return_value=True):
            result = list_conversation.try_handle_list_turn("新しくリスト作りたい")

        self.assertIsNotNone(result)
        self.assertIn("タスク（Notion）", result["reply"])
        self.assertIn("ほかに作る？", result["reply"])
        self.assertEqual(result["model_route"]["actual_route"], "deterministic")
        self.assertNotIn("pending_actions", result)

    def test_named_list_request_creates_confirmation_proposal(self) -> None:
        with patch.object(config, "notion_configured", return_value=True):
            result = list_conversation.try_handle_list_turn("アニメリスト作って")

        self.assertIsNotNone(result)
        self.assertEqual(result["pending_actions"][0]["name"], "create_list")
        self.assertEqual(result["pending_actions"][0]["arguments"], {"name": "アニメ"})
        self.assertIn("アニメリスト", result["reply"])

    def test_short_followup_after_inventory_creates_confirmation_proposal(self) -> None:
        history = [
            {"role": "user", "content": "新しくリスト作りたい"},
            {"role": "assistant", "content": "今は、タスク（Notion）があるよ。ほかに作る？"},
        ]
        with patch.object(config, "notion_configured", return_value=True):
            result = list_conversation.try_handle_list_turn("アニメリスト", history=history)

        self.assertIsNotNone(result)
        self.assertEqual(result["pending_actions"][0]["arguments"], {"name": "アニメ"})

    def test_topic_followup_is_not_misread_as_a_new_list_name(self) -> None:
        json.loads(tools.dispatch("create_list", {"name": "科学大キャンプ"}))
        history = [
            {"role": "user", "content": "新しくリスト作りたい"},
            {
                "role": "assistant",
                "content": "今は、タスク（Notion）、科学大キャンプリスト（ローカル）があるよ。ほかに作る？",
            },
        ]

        result = list_conversation.try_handle_list_turn("科学大キャンプについて", history=history)

        self.assertIsNone(result)

    def test_target_first_colloquial_item_add_routes_to_custom_list(self) -> None:
        created = json.loads(tools.dispatch("create_list", {"name": "科学大キャンプ"}))
        list_id = created["list"]["id"]

        result = list_conversation.try_handle_list_turn(
            "科学大キャンプリストに、iPhoneコースガイド見るって追加"
        )

        self.assertIsNotNone(result)
        action = result["pending_actions"][0]
        self.assertEqual(action["name"], "add_list_item")
        self.assertEqual(
            action["arguments"],
            {"title": "iPhoneコースガイド見る", "list_id": str(list_id)},
        )
        self.assertNotIn("project_id", action["arguments"])
        self.assertIn("科学大キャンプリストに追加する？", result["reply"])

        added = json.loads(tools.dispatch(action["name"], action["arguments"]))
        items = json.loads(tools.dispatch("get_list_items", {"list_id": str(list_id)}))
        self.assertTrue(added["added"])
        self.assertEqual(items["items"][0]["title"], "iPhoneコースガイド見る")

    def test_item_first_phrase_routes_to_custom_list(self) -> None:
        created = json.loads(tools.dispatch("create_list", {"name": "アニメ"}))

        result = list_conversation.try_handle_list_turn(
            "葬送のフリーレンをアニメリストに追加して"
        )

        self.assertIsNotNone(result)
        action = result["pending_actions"][0]
        self.assertEqual(action["name"], "add_list_item")
        self.assertEqual(action["arguments"]["title"], "葬送のフリーレン")
        self.assertEqual(action["arguments"]["list_id"], str(created["list"]["id"]))

    def test_missing_list_item_target_does_not_fall_back_to_task_creation(self) -> None:
        result = list_conversation.try_handle_list_turn(
            "存在しないリストに、iPhoneコースガイド見るって追加"
        )

        self.assertIsNotNone(result)
        self.assertNotIn("pending_actions", result)
        self.assertIn("見つからない", result["reply"])
        self.assertNotIn("create_task", result["model_route"]["tools"])

    def test_unrelated_task_activity_is_not_intercepted(self) -> None:
        result = list_conversation.try_handle_list_turn("卒研っていうタスクやってるんだ")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
