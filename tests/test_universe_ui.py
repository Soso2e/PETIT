from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UniverseUiTests(unittest.TestCase):
    def test_root_redirects_to_universe(self) -> None:
        index = (FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn("/static/universe.html", index)

    def test_universe_assets_and_legacy_ui_exist(self) -> None:
        for name in (
            "universe.html",
            "universe.css",
            "universe-actions.css",
            "universe-app.js",
            "legacy.html",
        ):
            self.assertTrue((FRONTEND / name).is_file(), name)

    def test_universe_has_required_views(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        for view in ("focus", "universe", "tasks", "chat"):
            self.assertIn(f'data-view="{view}"', html)
            self.assertIn(f'data-view-panel="{view}"', html)
        self.assertIn('href="/static/legacy.html"', html)
        self.assertIn('id="detail-panel"', html)
        self.assertIn('id="task-nodes"', html)
        self.assertIn('/static/universe-app.js', html)

    def test_universe_uses_existing_backend_contracts(self) -> None:
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/briefing"', script)
        self.assertIn('fetch("/api/chat"', script)
        self.assertIn('fetch("/api/health"', script)
        self.assertIn("/api/actions/", script)
        self.assertNotIn("three.js", script.lower())
        self.assertNotIn("webglrenderer", script.lower())

    def test_external_task_text_is_rendered_with_text_content(self) -> None:
        script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn("cell.textContent", script)
        self.assertIn("heading.textContent", script)
        self.assertNotIn("task.project_title || task.project_name ||", script)

    def test_mobile_and_reduced_motion_styles_exist(self) -> None:
        css = (FRONTEND / "universe.css").read_text(encoding="utf-8")
        actions_css = (FRONTEND / "universe-actions.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 640px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("space-node--active", css)
        self.assertIn("activePulse", css)
        self.assertIn(".chat-actions", actions_css)


if __name__ == "__main__":
    unittest.main()
