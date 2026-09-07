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
            "universe-webgl-scene.js",
            "universe-webgl-scene.css",
            "universe-webgl-bridge.js",
            "legacy.html",
        ):
            self.assertTrue((FRONTEND / name).is_file(), name)
        self.assertTrue((BACKEND / "task_list_api.py").is_file())
        self.assertTrue((BACKEND / "task_hierarchy.py").is_file())
        self.assertTrue((BACKEND / "tools" / "task_hierarchy.py").is_file())
        self.assertFalse((BACKEND / "tools" / "task_projects.py").exists())

    def test_universe_has_required_views(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        for view in ("focus", "universe", "tasks", "chat"):
            self.assertIn(f'data-view="{view}"', html)
            self.assertIn(f'data-view-panel="{view}"', html)
        self.assertNotIn('href="/static/legacy.html"', html)
        self.assertIn('data-view="settings"', html)
        self.assertIn('data-view-panel="settings"', html)
        self.assertIn('id="detail-panel"', html)
        self.assertIn('id="task-nodes"', html)
        self.assertIn('/static/universe-app.js', html)
        self.assertIn('/static/universe-next.js', html)
        self.assertIn('/static/universe-next.css', html)

    def test_core_contains_parent_tasks_and_child_tasks_directly(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        hierarchy = (FRONTEND / "universe-next.js").read_text(encoding="utf-8")
        webgl = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        self.assertIn("Core → Task → Child Task", html)
        self.assertIn('<span class="eyebrow">CORE</span>', html)
        self.assertIn("Core直下", html)
        self.assertIn("親Task", html)
        self.assertIn("Child Task", hierarchy)
        self.assertIn("createPlanet", webgl)
        self.assertIn("createConnection", webgl)
        self.assertNotIn("Life → Project → Task", html)

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

    def test_life_reads_all_open_tasks(self) -> None:
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        hierarchy = (FRONTEND / "universe-next.js").read_text(encoding="utf-8")
        self.assertIn('/api/notifications/tasks?priority=all&limit=500', script)
        self.assertIn('/api/notifications/tasks?priority=all&limit=500', hierarchy)
        self.assertIn("const openTasks", script)
        self.assertIn("hierarchy_role", hierarchy)
        self.assertIn("parent_task_id", hierarchy)

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
        self.assertIn('localStorage.removeItem("petit_universe_active_started_at")', script)
        self.assertNotIn('localStorage.setItem("petit_universe_active_started_at"', script)

    def test_overview_selection_focuses_and_opens_detail_in_webgl(self) -> None:
        app = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        webgl = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        self.assertIn("overviewSelectionId", app)
        self.assertIn("const selectOverviewTask", app)
        self.assertIn("state.overviewSelectionId === key", app)
        self.assertIn('setAttribute("aria-pressed"', app)
        self.assertIn("const selectEntry", webgl)
        self.assertIn("domNode?.click?.()", webgl)
        self.assertIn("focusEntry(entry)", webgl)
        self.assertIn("openDetail()", webgl)
        self.assertIn('document.body.classList.add("petit-univ-manage-open")', webgl)

    def test_parent_assignment_requires_explicit_apply(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        flow = (FRONTEND / "task-flow.js").read_text(encoding="utf-8")
        self.assertIn('data-action="parent-apply"', html)
        self.assertIn("const handleParentSelection", flow)
        self.assertIn("const handleParentApply", flow)
        self.assertIn("void changeParent(task, select, applyButton)", flow)
        self.assertIn("まだ保存されていません", flow)

    def test_task_controls_and_undo_are_present(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('data-action="complete"', html)
        self.assertIn('data-action="bucket"', html)
        self.assertIn('id="task-feedback"', html)
        self.assertIn('"元に戻す"', script)
        self.assertIn('priority: nextPriority', script)
        self.assertIn('resolve_notification: false', script)

    def test_parent_assignment_is_available_in_ui_and_chat(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        script = (FRONTEND / "task-flow.js").read_text(encoding="utf-8")
        decorator = (FRONTEND / "universe-next.js").read_text(encoding="utf-8")
        tool = (BACKEND / "tools" / "task_hierarchy.py").read_text(encoding="utf-8")
        service = (BACKEND / "task_hierarchy.py").read_text(encoding="utf-8")
        tools_init = (BACKEND / "tools" / "__init__.py").read_text(encoding="utf-8")
        capability = (BACKEND / "capability_router.py").read_text(encoding="utf-8")
        self.assertIn('data-action="parent"', html)
        self.assertIn('/parent', script)
        self.assertIn('move_to_life: true', script)
        self.assertIn('parent_task_id: Number', script)
        self.assertNotIn('/parent`', decorator)
        self.assertIn('name="set_task_parent"', tool)
        self.assertIn("requires_confirmation=True", tool)
        self.assertIn("parent_external_ids", service)
        self.assertIn("task_hierarchy", tools_init)
        self.assertIn('"set_task_parent"', capability)
        self.assertNotIn("classify_task_project", capability)

    def test_parent_assignment_uses_the_task_shown_in_detail_panel(self) -> None:
        app = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        flow = (FRONTEND / "task-flow.js").read_text(encoding="utf-8")
        decorator = (FRONTEND / "universe-next.js").read_text(encoding="utf-8")
        self.assertIn("detailPanelEl.dataset.taskId = taskKey(task, index)", app)
        self.assertIn("delete detailPanelEl.dataset.taskId", app)
        for script in (flow, decorator):
            displayed = script.index("const displayedId =")
            remembered = script.index("const remembered =", displayed)
            self.assertLess(displayed, remembered)

    def test_focus_orbit_uses_all_child_priorities_and_shared_refresh(self) -> None:
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn("filter((task) => !isRootTask(task))", script)
        self.assertIn("refreshAndFocusTask", script)
        self.assertIn('dataset.orbitIndex', script)

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
        self.assertIn("hierarchy-root-duplicate", css)

    def test_focus_motion_reuses_nodes_and_does_not_restart_on_selection(self) -> None:
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        css = (FRONTEND / "universe-next.css").read_text(encoding="utf-8")
        self.assertIn("const existingNodes = new Map", script)
        self.assertIn("if (!button)", script)
        self.assertNotIn("nodesEl.replaceChildren()", script)
        self.assertIn("if (orbitFrame != null) return", script)
        self.assertNotIn('nodesEl.matches(":hover")', script)
        self.assertNotIn('nodesEl.matches(":focus-within")', script)
        self.assertIn('panel.dataset.motionSeen !== "true"', script)
        self.assertIn('.view.is-entering', css)
        self.assertNotIn('.view.is-active {\n  animation: viewArrival', css)

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
        webgl_css = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")
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
        self.assertIn("@media (max-width: 640px)", webgl_css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", webgl_css)


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
    def _rows(self) -> list[dict[str, object]]:
        return [
            {
                "id": 1,
                "source": "notion",
                "external_id": "root",
                "title": "PETIT開発",
                "status": "Yet",
                "priority": "High",
                "due_date": None,
                "parent_task_id": None,
                "parent_external_id": None,
            },
            {
                "id": 2,
                "source": "notion",
                "external_id": "child",
                "title": "UIを刷新する",
                "status": "Yet",
                "priority": "High",
                "due_date": None,
                "parent_task_id": 1,
                "parent_external_id": "root",
            },
            {
                "id": 3,
                "source": "local",
                "external_id": None,
                "title": "買い物",
                "status": "Yet",
                "priority": "Low",
                "due_date": None,
                "parent_task_id": None,
                "parent_external_id": None,
            },
        ]

    def test_all_mode_returns_life_roots_and_children(self) -> None:
        from backend import task_list_api

        connection = _Connection(self._rows())
        with (
            patch.object(task_list_api.db, "get_connection", return_value=connection),
            patch.object(task_list_api, "_ensure_universe_schema"),
        ):
            response = task_list_api.list_ui_tasks(priority="all", limit=500)

        payload = json.loads(response.body)
        self.assertEqual(payload["hierarchy"], "life-task-child")
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["root_count"], 2)
        child = next(task for task in payload["tasks"] if task["id"] == 2)
        self.assertEqual(child["parent_task_id"], 1)
        self.assertEqual(child["parent_title"], "PETIT開発")
        self.assertEqual(child["root_title"], "PETIT開発")
        self.assertEqual(child["project_title"], "PETIT開発")
        self.assertEqual(child["hierarchy_role"], "child")
        root = next(task for task in payload["tasks"] if task["id"] == 1)
        self.assertTrue(root["has_children"])
        self.assertEqual(root["child_count"], 1)
        self.assertEqual(connection.params, ())

    def test_high_mode_keeps_priority_filter_after_hierarchy_resolution(self) -> None:
        from backend import task_list_api

        connection = _Connection(self._rows())
        with (
            patch.object(task_list_api.db, "get_connection", return_value=connection),
            patch.object(task_list_api, "_ensure_universe_schema"),
        ):
            response = task_list_api.list_ui_tasks(priority="high", limit=200)

        payload = json.loads(response.body)
        self.assertEqual(payload["priority"], "high")
        self.assertEqual(payload["count"], 2)
        self.assertTrue(all(task["priority"] == "High" for task in payload["tasks"]))

    def test_parent_endpoint_routes_to_hierarchy_service(self) -> None:
        from backend import task_list_api

        with patch.object(task_list_api.task_hierarchy, "set_task_parent", return_value={"updated": True}) as setter:
            response = task_list_api.patch_task_parent(
                2,
                task_list_api.TaskParentUpdate(parent_task_id=1),
            )
        self.assertEqual(response.status_code, 200)
        setter.assert_called_once_with(task_id=2, parent_task_id=1, move_to_life=False)

    def test_invalid_priority_is_rejected(self) -> None:
        from backend import task_list_api

        response = task_list_api.list_ui_tasks(priority="mid")
        self.assertEqual(response.status_code, 400)
        self.assertIn("high、low、all", json.loads(response.body)["error"])


if __name__ == "__main__":
    unittest.main()
