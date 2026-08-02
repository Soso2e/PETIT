from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class FocusOrbitContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.css = (FRONTEND / "universe-next.css").read_text(encoding="utf-8")

    def test_selection_reuses_existing_task_nodes(self) -> None:
        self.assertIn("const existingNodes = new Map", self.script)
        self.assertIn("existingNodes.get(key)", self.script)
        self.assertIn("if (!button)", self.script)
        self.assertIn("button.onclick = () => selectTask", self.script)
        self.assertNotIn("nodesEl.replaceChildren()", self.script)

    def test_orbit_loop_is_not_restarted_for_each_render(self) -> None:
        render_start = self.script.index("const renderOrbit = () =>")
        render_end = self.script.index("const renderOverview", render_start)
        render_body = self.script[render_start:render_end]
        self.assertNotIn("stopOrbitMotion()", render_body)
        self.assertIn("if (orbitFrame != null) return", self.script)
        self.assertNotIn('nodesEl.matches(\":hover\")', self.script)
        self.assertNotIn('nodesEl.matches(\":focus-within\")', self.script)

    def test_entry_animation_runs_once_and_reduced_motion_is_preserved(self) -> None:
        self.assertIn('panel.dataset.motionSeen !== "true"', self.script)
        self.assertIn('panel.classList.add("is-entering")', self.script)
        self.assertIn(".view.is-entering", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        reduced_motion = self.css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        self.assertIn(".view.is-entering", reduced_motion)
        self.assertIn("animation: none !important", reduced_motion)


if __name__ == "__main__":
    unittest.main()
