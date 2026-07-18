from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, project_completion, project_continuity, project_resume, project_router


class ProjectResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()
        project_completion.ensure_completion_schema()
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.add_project_alias("petit", "プチ")
        project_continuity.create_project("Linkraft", project_id="linkraft")

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _episode(self, title: str, summary: str) -> int:
        return db.save_episode(
            {
                "started_at": db.now_iso(),
                "ended_at": db.now_iso(),
                "title": title,
                "summary": summary,
                "decisions": "[]",
                "facts": "[]",
                "work_in_progress": "[]",
                "next_action": "[]",
                "source_ids": "[]",
                "content_hash": f"hash-{title}",
            }
        )

    def test_checkpoint_keeps_verified_unverified_next_and_blocker_separate(self) -> None:
        project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            stage="automated_tests_verified",
            last_summary="朝ブリーフィングのルーティングを実装",
            completed_evidence=["22 tests passed"],
            unverified_items=["実ブラウザ", "本番確認"],
            next_action="ブラウザで再開会話を確認する",
            blockers=["LM Studio停止"],
        )

        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertEqual(context.verified_items, ["22 tests passed"])
        self.assertEqual(context.unverified_items, ["実ブラウザ", "本番確認"])
        self.assertIn("確認済みは22 tests passed", rendered)
        self.assertIn("未確認は実ブラウザ、本番確認", rendered)
        self.assertIn("ブロッカーはLM Studio停止", rendered)
        self.assertIn("ブラウザで再開会話を確認する", rendered)

    def test_no_saved_context_does_not_invent_previous_work(self) -> None:
        context = project_resume.build_resume_context("soso", "linkraft")
        rendered = project_resume.render_resume_message(context)

        self.assertIsNone(context.checkpoint)
        self.assertEqual(context.recent_events, [])
        self.assertEqual(context.recent_episodes, [])
        self.assertIn("前回メモはまだない", rendered)
        self.assertNotIn("完了", rendered)

    def test_only_confirmed_episodes_for_selected_project_are_loaded(self) -> None:
        petit_episode = self._episode("PETIT", "PETITの設計を決めた")
        linkraft_episode = self._episode("Linkraft", "Linkraftの管理画面を作った")
        unconfirmed_episode = self._episode("候補", "未確認の関連候補")
        project_continuity.link_episode_to_project(
            petit_episode,
            "petit",
            relation="primary",
            confirmed=True,
        )
        project_continuity.link_episode_to_project(
            linkraft_episode,
            "linkraft",
            relation="primary",
            confirmed=True,
        )
        project_continuity.link_episode_to_project(
            unconfirmed_episode,
            "petit",
            relation="referenced",
            confirmed=False,
        )

        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertEqual([item["episode_id"] for item in context.recent_episodes], [petit_episode])
        self.assertIn("PETITの設計を決めた", rendered)
        self.assertNotIn("Linkraftの管理画面", rendered)
        self.assertNotIn("未確認の関連候補", rendered)

    def test_updates_after_checkpoint_are_project_scoped(self) -> None:
        project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            last_summary="基盤実装まで完了",
        )
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE project_checkpoints SET updated_at='2026-01-01T00:00:00+00:00' WHERE user_id='soso' AND project_id='petit'"
            )
            conn.execute(
                "INSERT INTO project_events (project_id, provider, event_type, summary, payload_json, idempotency_key, occurred_at, created_at) "
                "VALUES ('petit', 'petit', 'decision', '再開時は確認済み事実だけ使う', '{}', 'event-petit', '2026-07-18T00:00:00+00:00', '2026-07-18T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO project_events (project_id, provider, event_type, summary, payload_json, idempotency_key, occurred_at, created_at) "
                "VALUES ('linkraft', 'petit', 'decision', '他プロジェクトの更新', '{}', 'event-linkraft', '2026-07-18T00:00:00+00:00', '2026-07-18T00:00:00+00:00')"
            )

        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertEqual(len(context.updates_after_checkpoint), 1)
        self.assertIn("再開時は確認済み事実だけ使う", rendered)
        self.assertNotIn("他プロジェクトの更新", rendered)

    def test_legacy_handoff_is_used_as_compatibility_fallback(self) -> None:
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO handoff_notes (created_at, current_project, stopped_at, next_action, blockers, note, source) "
                "VALUES (?, 'プチ', '設計途中', 'Repository層から再開', '[]', '旧引き継ぎメモ', 'manual')",
                (db.now_iso(),),
            )

        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertIsNotNone(context.legacy_handoff)
        self.assertEqual(context.next_action, "Repository層から再開")
        self.assertIn("旧引き継ぎメモ", rendered)
        self.assertIn("Repository層から再開", rendered)

    def test_confirmed_stale_source_is_disclosed(self) -> None:
        project_continuity.link_project_source(
            "petit",
            "notion",
            "notion-petit",
            confirmed=True,
        )
        db.record_sync_success("notion", 3)
        db.record_sync_failure("notion", "network error")

        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertTrue(context.source_freshness["notion"]["stale"])
        self.assertIn("notionは最新同期に失敗", rendered)

    def test_router_exposes_reference_counts_without_llm(self) -> None:
        project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            last_summary="保存基盤まで完了",
        )

        result = project_router.handle_project_turn("PETITやる", user_id="soso")

        self.assertIsNotNone(result)
        refs = result["model_route"]["resume_references"]
        self.assertEqual(refs["checkpoint"], 1)
        self.assertEqual(refs["events"], 0)
        self.assertIn("保存基盤まで完了", result["reply"])


if __name__ == "__main__":
    unittest.main()
