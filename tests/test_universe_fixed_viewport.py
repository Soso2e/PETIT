from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UniverseFixedViewportTests(unittest.TestCase):
    def test_univ_is_locked_to_the_dynamic_viewport(self) -> None:
        css = (FRONTEND / "universe-3d-foundation.css").read_text(encoding="utf-8")

        self.assertIn("body.petit-univ-active {", css)
        self.assertIn("height: 100dvh", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn("overscroll-behavior: none", css)
        self.assertIn('body.petit-univ-active [data-view-panel="universe"].univ-panel', css)
        self.assertIn("body.petit-univ-active .univ-viewport", css)
        self.assertIn("min-height: 0", css)
        self.assertNotIn("left: var(--petit-rail-width", css)

    def test_webgl_ready_state_removes_legacy_css_sky(self) -> None:
        css = (FRONTEND / "universe-3d-foundation.css").read_text(encoding="utf-8")
        scene = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")

        self.assertIn("body.petit-univ-active .space", css)
        self.assertIn("display: none", css)
        self.assertIn("body.petit-univ-active.petit-univ-webgl-ready .univ-viewport", css)
        self.assertIn("background: transparent", css)
        self.assertIn(".univ-viewport::before", css)
        self.assertIn(".univ-viewport::after", css)
        self.assertIn('document.body.classList.add("petit-univ-webgl-ready")', scene)
        self.assertIn("createStarField()", scene)

    def test_mobile_hud_respects_safe_area_and_bottom_navigation(self) -> None:
        css = (FRONTEND / "universe-3d-foundation.css").read_text(encoding="utf-8")

        self.assertIn("env(safe-area-inset-top)", css)
        self.assertIn("env(safe-area-inset-right)", css)
        self.assertIn("env(safe-area-inset-left)", css)
        self.assertIn("var(--petit-bottom-nav-height, 70px)", css)

    def test_threejs_still_owns_camera_and_task_scene(self) -> None:
        scene = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")

        self.assertIn("new THREE.WebGLRenderer", scene)
        self.assertIn("new OrbitControls(state.camera, state.inputSurface)", scene)
        self.assertIn("new THREE.SphereGeometry", scene)
        self.assertIn("createConnection", scene)
        self.assertIn("selectEntry", scene)
        self.assertIn("focusEntry", scene)


if __name__ == "__main__":
    unittest.main()
