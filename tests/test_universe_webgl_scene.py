from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UniverseWebglSceneTests(unittest.TestCase):
    def test_scene_uses_real_threejs_camera_and_controls(self) -> None:
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        self.assertIn('const THREE_VERSION = "0.185.1"', source)
        self.assertIn("new THREE.WebGLRenderer", source)
        self.assertIn("new THREE.PerspectiveCamera", source)
        self.assertIn("new OrbitControls", source)
        self.assertIn("state.controls.target", source)
        self.assertIn("state.camera.position", source)
        self.assertNotIn("CSS2DRenderer", source)

    def test_planets_and_connections_are_real_scene_objects(self) -> None:
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        self.assertIn("new THREE.SphereGeometry", source)
        self.assertIn("new THREE.MeshStandardMaterial", source)
        self.assertIn("new THREE.Line", source)
        self.assertIn("createConnection", source)
        self.assertIn("parentPosition", source)
        self.assertIn("childPosition", source)
        self.assertIn("TaskSystem:", source)

    def test_hierarchy_is_normalized_from_parent_and_root_ids(self) -> None:
        source = (FRONTEND / "universe-webgl-hierarchy.js").read_text(encoding="utf-8")
        self.assertIn("parent_task_id", source)
        self.assertIn("parent_external_id", source)
        self.assertIn("root_task_id", source)
        self.assertIn("const buildHierarchy", source)
        self.assertIn("rootByAlias", source)
        self.assertIn("childrenByRoot", source)
        self.assertIn("univ-webgl-action-bridge", source)
        self.assertIn("original?.click?.()", source)
        self.assertIn('get("renderer") === "css"', source)

    def test_task_selection_uses_raycast_and_existing_action_bridge(self) -> None:
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        bridge = (FRONTEND / "universe-webgl-bridge.js").read_text(encoding="utf-8")
        self.assertIn("new THREE.Raycaster", source)
        self.assertIn("intersectObjects", source)
        self.assertIn("domNode?.click?.()", source)
        self.assertIn('document.body.classList.add("petit-univ-manage-open")', source)
        self.assertIn("selectEntry", source)
        self.assertIn("focusEntry", source)
        self.assertIn("ensureDetailPortal", bridge)
        self.assertIn("document.body.appendChild(detail)", bridge)
        self.assertIn('detail.classList.add("univ-detail-portal")', bridge)

    def test_webgl_input_is_owned_by_orbit_controls_and_taps_are_not_drags(self) -> None:
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        css = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")

        self.assertIn("state.controls.enableRotate = true", source)
        self.assertIn("state.controls.enableZoom = true", source)
        self.assertIn("state.controls.enableDamping = false", source)
        self.assertIn("state.controls.touches.ONE = THREE.TOUCH.ROTATE", source)
        self.assertIn("state.controls.touches.TWO = THREE.TOUCH.DOLLY_PAN", source)
        self.assertIn("new OrbitControls(state.camera, state.inputSurface)", source)
        self.assertIn('state.renderer.domElement.classList.add("univ-webgl-canvas")', source)
        self.assertIn("state.inputSurface = state.renderer.domElement", source)
        self.assertIn("const activePointers = new Set()", source)
        self.assertIn("suppressSelectionUntilPointersClear", source)
        self.assertIn("start.pointerId !== event.pointerId", source)
        self.assertIn("if (start.moved || distance > threshold", source)
        self.assertIn('input.addEventListener("pointercancel", cancelPointer)', source)
        self.assertIn('input.addEventListener("wheel"', source)
        self.assertNotIn(".univ-webgl-input", css)
        self.assertIn("overscroll-behavior: contain", css)

    def test_labels_remain_dom_text_instead_of_canvas_textures(self) -> None:
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        css = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")
        self.assertIn('document.createElement("button")', source)
        self.assertIn("world.clone().project(state.camera)", source)
        self.assertIn("univ-webgl-label-layer", source)
        self.assertIn(".univ-webgl-label", css)
        self.assertNotIn("CanvasTexture", source)
        self.assertNotIn("SpriteMaterial", source)

    def test_task_name_labels_are_clickable_selection_targets(self) -> None:
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        css = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")
        self.assertIn('element.addEventListener("click"', source)
        self.assertIn("selectEntry(entry)", source)
        self.assertIn("pointer-events: auto", css)
        self.assertIn("cursor: pointer", css)

    def test_css_scene_is_only_hidden_after_webgl_is_ready(self) -> None:
        source = (FRONTEND / "universe-webgl-scene.js").read_text(encoding="utf-8")
        css = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")
        self.assertIn('document.body.classList.add("petit-univ-webgl-ready")', source)
        self.assertIn(".petit-univ-webgl-ready .univ-viewport #constellation-grid.univ-space", css)
        self.assertIn("opacity: 0 !important", css)
        self.assertIn("従来表示を使用しています", source)

    def test_existing_hud_is_delegated_to_webgl_camera(self) -> None:
        source = (FRONTEND / "universe-webgl-bridge.js").read_text(encoding="utf-8")
        self.assertIn("handleHudAction", source)
        self.assertIn('action === "zoom-in"', source)
        self.assertIn('action === "zoom-out"', source)
        self.assertIn('action === "overview"', source)
        self.assertIn("event.stopImmediatePropagation()", source)
        self.assertIn("stopLegacyCameraInput", source)
        self.assertIn("window.PetitUnivSpace?.reset?.()", source)

    def test_webgl_context_loss_falls_back_and_rebuilds(self) -> None:
        source = (FRONTEND / "universe-webgl-bridge.js").read_text(encoding="utf-8")
        self.assertIn('addEventListener("webglcontextlost"', source)
        self.assertIn('addEventListener("webglcontextrestored"', source)
        self.assertIn('classList.remove("petit-univ-webgl-ready", "petit-univ-manage-open")', source)
        self.assertIn("webgl()?.rebuild?.()", source)
        self.assertIn("従来表示へ切り替えました", source)

    def test_bootstrap_loads_hierarchy_before_scene_and_supports_css_fallback(self) -> None:
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn("const loadWebGLScene = () =>", source)
        self.assertIn(
            'loadScript("/static/universe-webgl-hierarchy.js", "universe-webgl-hierarchy", loadWebGLScene)',
            source,
        )
        self.assertIn("/static/universe-webgl-scene.css", source)
        self.assertIn("/static/universe-webgl-bridge.js", source)
        self.assertIn('script.type = "module"', source)
        self.assertIn('get("renderer") === "css"', source)
        self.assertIn("if (forceCssRenderer) return", source)

    def test_service_worker_caches_local_and_remote_webgl_assets(self) -> None:
        source = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('CACHE_NAME = "petit-shell-v0.15.0-webgl1"', source)
        self.assertIn('"/static/universe-webgl-scene.css"', source)
        self.assertIn('"/static/universe-webgl-hierarchy.js"', source)
        self.assertIn('"/static/universe-webgl-scene.js"', source)
        self.assertIn('"/static/universe-webgl-bridge.js"', source)
        self.assertIn('"/static/universe-render-scheduler.js"', source)
        self.assertIn('THREE_CDN_ORIGIN = "https://esm.sh"', source)
        self.assertIn('THREE_CDN_PREFIX = "/three@0.185.1"', source)
        self.assertIn("isThreeModule", source)


if __name__ == "__main__":
    unittest.main()
