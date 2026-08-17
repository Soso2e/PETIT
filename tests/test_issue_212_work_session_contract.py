from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, work_sessions


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class Issue212WorkSessionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "petit.db"
        self.db_patch = patch.object(config, "DB_PATH", self.db_path)
        self.db_patch.start()
        work_sessions.ensure_schema()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_univ_chat_start_uses_shared_work_session_api(self) -> None:
        source = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('const classifyWorkCommand = (message) => {', source)
        self.assertIn('kind: "start"', source)
        self.assertIn('const resolveTaskFromWorkTitle = (title) => {', source)
        self.assertIn('await startTask(matchedTask', source)
        self.assertIn('await startFreeformWork(command.title)', source)
        self.assertIn('requestJson(`/api/work-sessions${path}`', source)
        for phrase in ("作業中にして", "作業", "始める"):
            self.assertIn(phrase, source)

    def test_univ_work_session_state_is_server_backed(self) -> None:
        source = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('workSessionRequest("/start", "POST"', source)
        self.assertIn('const pollWorkSession = async () => {', source)
        for action in ("pause", "resume", "end"):
            self.assertIn(action, source)
        self.assertNotIn("petit_universe_active_started_at", source.split(
            "// Remove the old client-only timer.", 1
        )[1].split("const state =", 1)[0])

    def test_today_and_companion_share_work_session_endpoints(self) -> None:
        today = (FRONTEND / "today.js").read_text(encoding="utf-8")
        companion = (FRONTEND / "companion.js").read_text(encoding="utf-8")
        self.assertIn("/api/work-sessions", today)
        self.assertIn("/api/work-sessions", companion)
        self.assertIn("classifySessionCommand", companion)
        self.assertIn("pause", companion)
        self.assertIn("resume", companion)
        self.assertIn("end", companion)

    def test_server_active_session_is_single_source_of_truth(self) -> None:
        first = work_sessions.start_session("issue-212-univ", "Univ作業")
        self.assertEqual(work_sessions.active_session()["session_id"], first["session_id"])

        second = work_sessions.start_session("issue-212-chat", "チャット作業")
        active = work_sessions.active_session()
        self.assertEqual(active["session_id"], second["session_id"])
        self.assertEqual(active["task"], "チャット作業")
        self.assertEqual(work_sessions._row("issue-212-univ")["status"], "ended")

        paused = work_sessions.pause_session(second["session_id"])
        self.assertEqual(paused["status"], "paused")
        resumed = work_sessions.resume_session(second["session_id"])
        self.assertEqual(resumed["status"], "active")
        ended = work_sessions.end_session(second["session_id"])
        self.assertEqual(ended["status"], "ended")
        self.assertIsNone(work_sessions.active_session())

    def test_threejs_hierarchy_contract_is_present(self) -> None:
        scene = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        hierarchy = (FRONTEND / "universe-webgl-hierarchy.js").read_text(encoding="utf-8")
        bridge = (FRONTEND / "universe-webgl-bridge.js").read_text(encoding="utf-8")
        self.assertIn("THREE", scene)
        self.assertIn("parent", hierarchy.lower())
        self.assertIn("child", hierarchy.lower())
        self.assertIn("task", hierarchy.lower())
        self.assertIn("Petit", bridge)


if __name__ == "__main__":
    unittest.main()
