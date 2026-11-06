from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend import config, notion_search
from backend.notion_client import NotionError
from backend import tools
from backend.tools.builtins import register_builtin_tools


class NotionSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        register_builtin_tools()

    def test_normalize_query_extracts_subject_from_natural_request(self) -> None:
        self.assertEqual(
            notion_search.normalize_query("Notionから卒研に関する情報あったら、今どんな感じか教えて"),
            "卒研",
        )
        self.assertEqual(notion_search.normalize_query("NotionでPETITを検索して"), "PETIT")

    def test_search_returns_bounded_page_facts(self) -> None:
        page = {
            "object": "page",
            "id": "page-1",
            "url": "https://www.notion.so/page-1",
            "last_edited_time": "2026-07-21T12:00:00.000Z",
            "properties": {
                "名前": {"type": "title", "title": [{"plain_text": "卒研"}]},
                "ステータス": {"type": "status", "status": {"name": "進行中"}},
                "要約": {"type": "rich_text", "rich_text": [{"plain_text": "支援ツールの効果検証"}]},
            },
        }
        with (
            patch.object(config, "NOTION_API_KEY", "secret"),
            patch.object(notion_search, "_search_pages", return_value=[page]),
            patch.object(notion_search, "_page_text", return_value="次は評価指標を決める。"),
        ):
            result = notion_search.search(
                "Notionから卒研に関する情報あったら、今どんな感じか教えて",
                limit=3,
                max_chars=1200,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["searched"])
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["query"], "卒研")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["title"], "卒研")
        self.assertEqual(result["results"][0]["properties"]["ステータス"], "進行中")
        self.assertIn("支援ツールの効果検証", result["results"][0]["excerpt"])
        self.assertIn("次は評価指標を決める", result["results"][0]["excerpt"])

    def test_search_distinguishes_not_configured_not_found_and_error(self) -> None:
        with patch.object(config, "NOTION_API_KEY", ""):
            not_configured = notion_search.search("卒研")
        self.assertEqual(not_configured["status"], "not_configured")
        self.assertFalse(not_configured["searched"])

        with (
            patch.object(config, "NOTION_API_KEY", "secret"),
            patch.object(notion_search, "_search_pages", return_value=[]),
        ):
            not_found = notion_search.search("卒研")
        self.assertEqual(not_found["status"], "not_found")
        self.assertTrue(not_found["searched"])
        self.assertIsNone(not_found["error"])

        with (
            patch.object(config, "NOTION_API_KEY", "secret"),
            patch.object(notion_search, "_search_pages", side_effect=NotionError("API unavailable")),
        ):
            failed = notion_search.search("卒研")
        self.assertEqual(failed["status"], "error")
        self.assertTrue(failed["searched"])
        self.assertIn("API unavailable", failed["error"])

    def test_tool_is_registered_read_only(self) -> None:
        self.assertIn("search_notion", tools.registered_names())
        self.assertFalse(tools.requires_confirmation("search_notion"))


class NotionSearchRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        register_builtin_tools()

    @staticmethod
    def route() -> dict:
        return {
            "type": "agent",
            "capabilities": ["knowledge"],
            "goal": "Notionから卒研の現状を確認する",
            "source": "llm",
            "confidence": 0.98,
        }

    @staticmethod
    def tool_call(arguments: dict) -> dict:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "notion-1",
                    "type": "function",
                    "function": {
                        "name": "search_notion",
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            ],
        }





if __name__ == "__main__":
    unittest.main()
