from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"


class UniverseUiTests(unittest.TestCase):
    def test_root_redirects_to_universe(self) -> None:
        index = (FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn("/static/universe.html", index)

    def test_universe_assets_and_legacy_ui_exist(self) -> None:
        for name in (
            "universe.html",
            "universe.css",
            "universe-actions.css",
            "universe-next.css",
            "universe-app.js",
            "universe-next.js",
            "legacy.html",
        ):
            self.assertTrue((FRONTEND / name).is_file(), name)
        self.assertTrue((BACKEND / "task_list_api.py").is_file())
        self.assertTrue((BACKEND / "tools" / "task_projects.py").is_file())

    def test_universe_has_required_views(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        for view in ("focus", "universe", "tasks", "chat"):
            self.assertIn(f'data-view="{view}"', html)
            self.assertIn(f'data-view-panel="{view}"', html)
        self.assertIn('href="/static/legacy.html"', html)
        self.assertIn('id="detail-panel"', html)
        self.assertIn('id="task-nodes"', html)
        self.assertIn('/static/universe-app.js', html)
        self.assertIn('/static/universe-next.js', html)
        self.assertIn('/static/universe-next.css', html)

    def test_life_project_task_hierarchy_and_project_switching_exist(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn("Life → Project → Task", html)
        self.assertIn('data-life-root', html)
        self.assertIn('id="focus-project-select"', html)
        self.assertIn('id="focus-project-prev"', html)
        self.assertIn('id="focus-project-next"', html)
        self.assertIn("const selectProject", script)
        self.assertIn("const moveProject", script)
        self.assertIn("const projectGroups", script)
        self.assertIn("const focusTasks", script)
        self.assertIn("localStorage.setItem(STORAGE.selectedProject", script)

    def test_task_views_separate_high_and_low_without_mid_or_all_filter(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('data-filter="high"', html)
        self.assertIn('data-filter="low"', html)
        self.assertNotIn('data-filter="all"', html)
        self.assertNotIn('data-filter="active"', html)
        self.assertIn("const highTasks", script)
        self.assertIn("const lowTasks", script)
        self.assertIn('state.filter === "low" ? lowTasks() : highTasks()', script)

    def test_life_universe_reads_all_open_tasks_but_focus_keeps_high(self) -> None:
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('/api/notifications/tasks?priority=all&limit=500', script)
        self.assertIn("const openTasks", script)
        self.assertIn("projectTasks().filter(isHigh)", script)
        self.assertIn("group.tasks.forEach", script)
        self.assertIn('isLow(task) ? "low"', script)

    def test_universe_uses_existing_backend_contracts(self) -> None:
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('requestJson("/api/briefing"', script)
        self.assertIn('/api/notifications/tasks?priority=high', script)
        self.assertIn('/api/notifications/tasks?priority=low', script)
        self.assertIn('requestJson("/api/chat"', script)
        self.assertIn('requestJson("/api/health"', script)
        self.assertIn("/api/actions/", script)
        self.assertIn("/api/notifications/tasks/", script)
        self.assertIn("/complete", script)
        self.assertIn('method: "PATCH"', script)
        self.assertIn('status: "Yet"', script)
        self.assertNotIn("three.js", script.lower())
        self.assertNotIn("webglrenderer", script.lower())

    def test_selection_and_work_session_are_separate(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('data-action="activate"', html)
        self.assertIn('id="work-session-continue"', html)
        self.assertIn('id="work-session-pause"', html)
        self.assertIn('id="work-session-end"', html)
        self.assertIn("const selectTask", script)
        self.assertIn("const startTask", script)
        self.assertIn('workSessionRequest("/start"', script)
        self.assertIn('/api/work-sessions', script)
        self.assertIn('awaiting_response_since', script)
        self.assertIn('state.workSession?.status === "paused" ? "resume" : "pause"', script)
        self.assertIn('localStorage.removeItem("petit_universe_active_started_at")', script)
        self.assertNotIn('localStorage.setItem("petit_universe_active_started_at"', script)
        self.assertNotIn('button.addEventListener("dblclick"', script)

    def test_task_controls_and_undo_are_present(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('data-action="complete"', html)
        self.assertIn('data-action="bucket"', html)
        self.assertIn('id="task-feedback"', html)
        self.assertIn('"元に戻す"', script)
        self.assertIn('priority: nextPriority', script)
        self.assertIn('resolve_notification: false', script)

    def test_project_assignment_is_available_in_ui_and_chat(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        script = (FRONTEND / "universe-next.js").read_text(encoding="utf-8")
        tool = (BACKEND / "tools" / "task_projects.py").read_text(encoding="utf-8")
        tools_init = (BACKEND / "tools" / "__init__.py").read_text(encoding="utf-8")
        capability = (BACKEND / "capability_router.py").read_text(encoding="utf-8")
        self.assertIn('data-action="project"', html)
        self.assertIn('/api/notifications/projects', script)
        self.assertIn('project_id: projectId', script)
        self.assertIn('name="classify_task_project"', tool)
        self.assertIn("requires_confirmation=True", tool)
        self.assertIn("task_projects", tools_init)
        self.assertIn('"classify_task_project"', capability)

    def test_all_replaces_unclassified_for_unassigned_tasks(self) -> None:
        api = (BACKEND / "task_list_api.py").read_text(encoding="utf-8")
        next_script = (FRONTEND / "universe-next.js").read_text(encoding="utf-8")
        self.assertIn('_ALL_PROJECT_LABEL = "All"', api)
        self.assertIn("AS project_title", api)
        self.assertIn('const ALL_LABEL = "All"', next_script)

    def test_focus_zoom_and_motion_controls_exist(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        script = (FRONTEND / "universe-next.js").read_text(encoding="utf-8")
        css = (FRONTEND / "universe-next.css").read_text(encoding="utf-8")
        for control in ("focus-zoom-out", "focus-zoom-in", "focus-zoom-reset", "focus-zoom-label"):
            self.assertIn(f'id="{control}"', html)
        self.assertIn('addEventListener("touchmove"', script)
        self.assertIn('data-zoom-level', html)
        self.assertIn('orbit[data-zoom-level="near"]', css)
        self.assertIn("@keyframes nodeArrival", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def test_legacy_settings_can_return_to_new_ui(self) -> None:
        shell = (FRONTEND / "shell.js").read_text(encoding="utf-8")
        self.assertIn("installNewUiReturn", shell)
        self.assertIn('link.href = "/static/universe.html"', shell)
        self.assertIn('link.textContent = "新UIに戻る"', shell)
        self.assertIn("data-new-ui-return", shell)

    def test_external_task_text_is_rendered_with_text_content(self) -> None:
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn("cell.textContent", script)
        self.assertIn("heading.textContent", script)
        self.assertIn("label.textContent", script)
        self.assertIn("title.textContent", script)

    def test_mobile_and_reduced_motion_styles_exist(self) -> None:
        css = (FRONTEND / "universe.css").read_text(encoding="utf-8")
        actions_css = (FRONTEND / "universe-actions.css").read_text(encoding="utf-8")
        next_css = (FRONTEND / "universe-next.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 640px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("space-node--active", css)
        self.assertIn("activePulse", css)
        self.assertIn(".task-check", actions_css)
        self.assertIn(".task-feedback", actions_css)
        self.assertIn(".focus-project-switcher", actions_css)
        self.assertIn(".universe-task-list", actions_css)
        self.assertIn(".work-session-controls", actions_css)
        self.assertIn("@media (max-width: 640px)", next_css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", next_css)


class _Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> _Rows:
        self.sql = sql
        self.params = params
        return _Rows(self.rows)


class UniverseTaskListApiTests(unittest.TestCase):
    def test_all_mode_returns_every_open_priority_without_priority_bind(self) -> None:
        from backend import task_list_api

        connection = _Connection([
            {"id": 1, "title": "High task", "priority": "High"},
            {"id": 2, "title": "Mid task", "priority": "Mid"},
            {"id": 3, "title": "Low task", "priority": "Low"},
        ])
        with (
            patch.object(task_list_api.db, "get_connection", return_value=connection),
            patch.object(task_list_api, "_ensure_universe_schema"),
        ):
            response = task_list_api.list_ui_tasks(priority="all", limit=500)

        payload = json.loads(response.body)
        self.assertEqual(payload["priority"], "all")
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["unassigned_label"], "All")
        self.assertNotIn("lower(COALESCE(t.priority, ''))=?", connection.sql)
        self.assertIn("LEFT JOIN projects", connection.sql)
        self.assertEqual(connection.params, ("All", 500))

    def test_high_mode_keeps_explicit_priority_filter(self) -> None:
        from backend import task_list_api

        connection = _Connection([{"id": 1, "title": "High task", "priority": "High"}])
        with (
            patch.object(task_list_api.db, "get_connection", return_value=connection),
            patch.object(task_list_api, "_ensure_universe_schema"),
        ):
            response = task_list_api.list_ui_tasks(priority="high", limit=200)

        payload = json.loads(response.body)
        self.assertEqual(payload["priority"], "high")
        self.assertIn("lower(COALESCE(t.priority, ''))=?", connection.sql)
        self.assertEqual(connection.params, ("All", "high", 200))

    def test_projects_endpoint_marks_confirmed_notion_links(self) -> None:
        from backend import task_list_api

        connection = _Connection([
            {"id": "petit", "name": "PETIT", "status": "active", "description": None, "notion_linked": 1},
            {"id": "roomies", "name": "Roomies", "status": "active", "description": None, "notion_linked": 0},
        ])
        with (
            patch.object(task_list_api.db, "get_connection", return_value=connection),
            patch.object(task_list_api, "_ensure_universe_schema"),
        ):
            response = task_list_api.list_ui_projects()

        payload = json.loads(response.body)
        self.assertEqual(payload["count"], 2)
        self.assertTrue(payload["projects"][0]["notion_linked"])
        self.assertFalse(payload["projects"][1]["notion_linked"])
        self.assertIn("project_source_links", connection.sql)
        self.assertEqual(connection.params, ())

    def test_invalid_priority_is_rejected(self) -> None:
        from backend import task_list_api

        response = task_list_api.list_ui_tasks(priority="mid")
        self.assertEqual(response.status_code, 400)
        self.assertIn("high、low、all", json.loads(response.body)["error"])


if __name__ == "__main__":
    unittest.main()
