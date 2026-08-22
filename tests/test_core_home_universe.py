from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UnivSpaceTests(unittest.TestCase):
    def test_app_shell_has_three_primary_areas(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('{ view: "univ", target: "universe", label: "Univ" }', source)
        self.assertIn('{ view: "tasks", target: "tasks", label: "Tasks" }', source)
        self.assertIn('{ view: "chat", target: "chat", label: "PETIT" }', source)
        self.assertNotIn('label: "Home"', source)
        self.assertNotIn('label: "Focus"', source)
        self.assertIn('home: "univ"', source)
        self.assertIn('focus: "univ"', source)
        self.assertIn('new CustomEvent("petit:univ-open"', source)
        self.assertIn("switchPanelDirectly(panelView)", source)

    def test_univ_assets_are_loaded(self):
        shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        version = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn('/static/univ-space.css', shell)
        self.assertIn('/static/univ-space.js', shell)
        self.assertIn('/static/universe-webgl-hierarchy.js', version)
        self.assertIn('/static/universe-webgl-scene.js', version)
        self.assertIn('/static/universe-webgl-bridge.js', version)
        for filename in (
            "univ-space.css",
            "univ-space.js",
            "universe-webgl-hierarchy.js",
            "universe-webgl-scene.js",
            "universe-webgl-scene.css",
            "universe-webgl-bridge.js",
        ):
            self.assertTrue((FRONTEND / filename).exists())

    def test_univ_hud_and_real_camera_focus_exist(self):
        fallback = (FRONTEND / "univ-space.js").read_text(encoding="utf-8")
        webgl = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        bridge = (FRONTEND / "universe-webgl-bridge.js").read_text(encoding="utf-8")
        self.assertIn('className = "univ-viewport"', fallback)
        self.assertIn('className = "univ-hud"', fallback)
        self.assertIn('data-univ-selected-description', fallback)
        self.assertIn('data-univ-action="focus"', fallback)
        self.assertIn('data-univ-action="manage"', fallback)
        self.assertIn("new THREE.PerspectiveCamera", webgl)
        self.assertIn("new OrbitControls", webgl)
        self.assertIn("new THREE.Raycaster", webgl)
        self.assertIn("startCameraTween", webgl)
        self.assertIn("focusEntry", webgl)
        self.assertIn("petit-univ-manage-open", bridge)
        self.assertIn("ensureDetailPortal", bridge)
        self.assertNotIn('switchView("focus")', fallback)

    def test_planet_semantics_are_explicit(self):
        scene = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        hierarchy = (FRONTEND / "universe-webgl-hierarchy.js").read_text(encoding="utf-8")
        css = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")
        self.assertIn('type: "core"', scene)
        self.assertIn('type: "parent"', scene)
        self.assertIn('type: "child"', scene)
        self.assertIn("createPlanet(coreEntry", scene)
        self.assertIn("createPlanet(model", scene)
        self.assertIn("createPlanet(child", scene)
        self.assertIn('button.className = "univ-task-planet"', hierarchy)
        self.assertIn('button.className = "universe-task univ-satellite"', hierarchy)
        self.assertIn("univ-webgl-label--core", css)
        self.assertIn("univ-webgl-label--parent", css)
        self.assertIn("univ-webgl-label--child", css)
        self.assertIn("parent_task_id", hierarchy)
        self.assertIn("root_task_id", hierarchy)

    def test_webgl_uses_real_spheres_and_mobile_dom_labels(self):
        scene = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        css = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")
        fallback = (FRONTEND / "univ-space.css").read_text(encoding="utf-8")
        self.assertIn("new THREE.WebGLRenderer", scene)
        self.assertIn("new THREE.SphereGeometry", scene)
        self.assertIn("new THREE.MeshStandardMaterial", scene)
        self.assertIn("new THREE.Line", scene)
        self.assertIn("labelProjected.copy(labelWorld).project(state.camera)", scene)
        self.assertIn(".univ-webgl-label", css)
        self.assertIn("@media (max-width: 640px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn('grid-template-columns: repeat(3, minmax(0, 1fr))', fallback)
        self.assertIn('.petit-univ-active #detail-panel', fallback)


if __name__ == "__main__":
    unittest.main()
