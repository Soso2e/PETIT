from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend import agent, config, notion_search
from backend.notion_client import NotionError
from backend import tools


class NotionSearchTests(unittest.TestCase):
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
    def test_explicit_notion_read_skips_router_and_uses_one_synthesis_call(self) -> None:
        tool_result = {
            "ok": True,
            "searched": True,
            "status": "found",
            "query": "卒研",
            "count": 1,
            "results": [
                {
                    "title": "卒研",
                    "url": "https://www.notion.so/page-1",
                    "last_edited_time": "2026-07-21T12:00:00.000Z",
                    "properties": {"ステータス": "進行中"},
                    "excerpt": "次は評価指標を決める。",
                }
            ],
        }
        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(agent.model_router, "choose") as router,
            patch.object(agent.tools, "dispatch", return_value=json.dumps(tool_result, ensure_ascii=False)) as dispatch,
            patch.object(
                agent,
                "chat_completion",
                return_value={"role": "assistant", "content": "卒研は進行中で、次は評価指標を決める段階です。"},
            ) as completion,
        ):
            result = agent.run("Notionから卒研に関する情報あったら、今どんな感じか教えて")

        router.assert_not_called()
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(completion.call_args.kwargs["route"], "agent")
        called_args = dispatch.call_args.args[1]
        self.assertEqual(called_args["limit"], 3)
        self.assertEqual(called_args["max_chars"], 1200)
        self.assertEqual(result["used_tools"][0]["name"], "search_notion")
        self.assertEqual(result["model_route"]["kind"], "forced_read")
        self.assertEqual(result["reply"], "卒研は進行中で、次は評価指標を決める段階です。")

    def test_not_found_returns_deterministically_without_llm(self) -> None:
        tool_result = {
            "ok": True,
            "searched": True,
            "status": "not_found",
            "query": "卒研",
            "count": 0,
            "results": [],
            "error": None,
        }
        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(agent.model_router, "choose") as router,
            patch.object(agent.tools, "dispatch", return_value=json.dumps(tool_result, ensure_ascii=False)),
            patch.object(agent, "chat_completion") as completion,
        ):
            result = agent.run("Notionから卒研を探して")

        router.assert_not_called()
        completion.assert_not_called()
        self.assertIn("見つかりませんでした", result["reply"])
        self.assertEqual(result["model_route"]["actual_route"], "deterministic")
        self.assertEqual(result["model_route"]["fallback_reason"], "notion_not_found")

    def test_sync_and_casual_mentions_do_not_trigger_search(self) -> None:
        self.assertEqual(agent._related_tool_names("Notionを同期して"), ["sync_notion_tasks"])
        self.assertNotIn("search_notion", agent._related_tool_names("Notionは便利だね"))


if __name__ == "__main__":
    unittest.main()
