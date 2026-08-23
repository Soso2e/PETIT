from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class Issue215FixedUniverseTests(unittest.TestCase):
    def test_app_shell_locks_only_the_universe_panel(self) -> None:
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('document.body.classList.toggle("petit-univ-screen", panelView === "universe")', source)

    def test_direct_universe_navigation_loads_webgl(self) -> None:
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn('window.addEventListener("petit:panel-change", loadForUniverse)', source)
        self.assertIn('window.addEventListener("petit:area-change", loadForUniverse)', source)
        self.assertIn('panelObserver.observe(universePanel, { attributes: true, attributeFilter: ["hidden"] })', source)

    def test_universe_is_a_fixed_safe_area_viewport(self) -> None:
        source = (FRONTEND / "univ-space.css").read_text(encoding="utf-8")
        self.assertIn("html:has(body.petit-univ-screen)", source)
        self.assertIn("overflow: hidden", source)
        self.assertIn("position: fixed", source)
        self.assertIn("100dvh", source)
        self.assertIn("env(safe-area-inset-bottom)", source)
        self.assertIn("body.petit-univ-screen .petit-context-bar", source)
        self.assertIn(".petit-univ-manage-open .petit-utility-dock", source)

    def test_detail_template_and_runtime_use_the_same_start_action(self) -> None:
        source = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        self.assertIn('data-action="activate"', html)
        self.assertIn("fragment.querySelector('[data-action=\"activate\"]')", source)

    def test_every_star_click_requests_camera_focus(self) -> None:
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        start = source.index("const selectEntry = (entry) =>")
        end = source.index("const zoomBy =", start)
        block = source[start:end]
        self.assertIn("focusEntry(entry);", block)
        self.assertNotIn("if (!isAlreadySelected) focusEntry(entry);", block)
        self.assertIn("window.PetitUniverse?.selectTask?.(entry.taskId)", block)
        self.assertIn("if (!selectedByUniverse)", block)

    def test_webgl_removes_duplicate_css_scene_background(self) -> None:
        css = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        self.assertIn(".petit-univ-webgl-ready .univ-viewport::before", css)
        self.assertIn("display: none", css)
        self.assertIn("alpha: false", source)
        self.assertIn("setClearColor(0x02040d, 1)", source)


if __name__ == "__main__":
    unittest.main()
