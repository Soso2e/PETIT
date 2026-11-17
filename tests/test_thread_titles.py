from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import (
    brain,
    config,
    conversation_api as api,
    conversation_store as store,
    db,
    main,
    thread_titles,
)


class ThreadTitleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p_db = patch.object(config, "DB_PATH", Path(self.temp.name) / "app.db")
        p_db.start()
        self.addCleanup(p_db.stop)
        p_env = patch.dict(
            "os.environ",
            {
                "PETIT_SETTINGS_DIR": str(Path(self.temp.name) / "settings"),
                "PETIT_DEEPSEEK_API_KEY": "test-deepseek-key",
            },
        )
        p_env.start()
        self.addCleanup(p_env.stop)
        db.init_db()
        store.ensure_schema()
        from backend import setup_store
        setup_store._sessions.clear()

    def test_generate_title_uses_deepseek_and_cleans_output(self):
        with patch.object(
            thread_titles.lmstudio_client,
            "chat_completion",
            return_value={"content": "「Python非同期処理の相談」\n"},
        ) as mock_llm:
            title = thread_titles.generate_title("asyncioでバックグラウンド処理を安全に動かす方法を教えてください")
        self.assertEqual(title, "Python非同期処理の相談")
        messages = mock_llm.call_args.args[0]
        self.assertIn("この文章を一言に言い直してください。", messages[1]["content"])
        self.assertEqual(mock_llm.call_args.kwargs["target_override"]["provider"], "deepseek")

    def test_generate_title_skips_unconfigured_or_internal_or_error(self):
        self.assertIsNone(thread_titles.generate_title("[PETIT_INTERNAL_EVENT] ping"))
        with patch.dict("os.environ", {"PETIT_DEEPSEEK_API_KEY": "", "DEEPSEEK_API_KEY": ""}):
            self.assertIsNone(thread_titles.generate_title("通常の相談"))
        with patch.object(thread_titles.lmstudio_client, "chat_completion", side_effect=RuntimeError("network")):
            self.assertIsNone(thread_titles.generate_title("通常の相談"))

    def test_ensure_thread_title_respects_existing_and_local_only(self):
        store.create_thread("t-std", source="web", title="")
        store.create_thread("t-manual", source="web", title="手動タイトル")
        store.create_thread("t-local", source="web", title="", privacy="local_only")

        with patch.object(thread_titles, "generate_title", return_value="自動タイトル") as gen:
            self.assertEqual(thread_titles.ensure_thread_title("t-std", "最初の質問"), "自動タイトル")
            self.assertIsNone(thread_titles.ensure_thread_title("t-manual", "最初の質問"))
            self.assertIsNone(thread_titles.ensure_thread_title("t-local", "秘密の質問"))

        gen.assert_called_once_with("最初の質問")
        self.assertEqual(store.thread("t-std")["title"], "自動タイトル")
        self.assertEqual(store.thread("t-manual")["title"], "手動タイトル")
        self.assertEqual(store.thread("t-local")["title"], "")

    def test_patch_thread_title_endpoint(self):
        from backend import setup_store

        store.create_thread("t-api", source="web", title="")
        setup_store.set_password("synthetic-passphrase")
        token = setup_store.authenticate("synthetic-passphrase")
        self.assertIsNotNone(token)
        client = TestClient(main.app, headers={"Origin": "http://testserver"})
        self.assertEqual(client.patch("/api/threads/t-api", json={"title": "未認証"}).status_code, 401)
        client.cookies.set("petit_admin", token)

        res = client.patch("/api/threads/t-api", json={"title": "  新しいタイトル  "})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["title"], "新しいタイトル")
        self.assertEqual(store.thread("t-api")["title"], "新しいタイトル")

        res_clear = client.patch("/api/threads/t-api", json={"title": "   "})
        self.assertEqual(res_clear.status_code, 200)
        self.assertEqual(res_clear.json()["title"], "")

        res_missing = client.patch("/api/threads/not-found", json={"title": "x"})
        self.assertEqual(res_missing.status_code, 404)

    def test_submit_schedules_title_only_when_empty(self):
        with (
            patch("backend.chroma_client.add"),
            patch("backend.chat._artifact_executor.submit") as submit_mock,
            patch.object(brain.lmstudio_client, "chat_completion", return_value={"role": "assistant", "content": "はい"}),
        ):
            api.submit("t-new", "req-1", "晩ご飯のレシピを教えて", is_admin=True)
            scheduled_fns = [c.args[0] for c in submit_mock.call_args_list]
            self.assertIn(thread_titles.ensure_thread_title, scheduled_fns)

            submit_mock.reset_mock()
            store.update_thread_title("t-new", "確定タイトル")
            api.submit("t-new", "req-2", "続きの質問", is_admin=True)
            scheduled_fns_2 = [c.args[0] for c in submit_mock.call_args_list]
            self.assertNotIn(thread_titles.ensure_thread_title, scheduled_fns_2)

    def test_develop_job_start_schedules_title_only_when_empty(self):
        from backend import coding_jobs, setup_store

        setup_store.set_password("synthetic-passphrase")
        token = setup_store.authenticate("synthetic-passphrase")
        self.assertIsNotNone(token)
        client = TestClient(main.app, headers={"Origin": "http://testserver"})
        client.cookies.set("petit_admin", token)

        created = client.post("/api/coding/threads", json={"thread_id": "dev-new", "repository": "", "title": ""})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["title"], "")

        with (
            patch.object(coding_jobs.development_models, "select", return_value=("codex", "test-model", {"model_key": "codex_sol"})),
            patch("backend.chat._artifact_executor.submit") as submit_mock,
        ):
            res1 = client.post("/api/coding/jobs/start", json={
                "request_id": "dev-req-1",
                "repository": "",
                "goal": "Developタブからスレッド名を自動生成する",
                "thread_id": "dev-new",
            })
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(store.thread("dev-new")["title"], "")
            scheduled = [(c.args[0], c.args[1], c.args[2]) for c in submit_mock.call_args_list]
            self.assertIn((thread_titles.ensure_thread_title, "dev-new", "Developタブからスレッド名を自動生成する"), scheduled)

            submit_mock.reset_mock()
            store.update_thread_title("dev-new", "スレッド名自動生成")
            res2 = client.post("/api/coding/jobs/start", json={
                "request_id": "dev-req-2",
                "repository": "",
                "goal": "追加の修正依頼",
                "thread_id": "dev-new",
            })
            self.assertEqual(res2.status_code, 200)
            scheduled_2 = [c.args[0] for c in submit_mock.call_args_list]
            self.assertNotIn(thread_titles.ensure_thread_title, scheduled_2)
