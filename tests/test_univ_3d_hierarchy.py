from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class Univ3dHierarchyTests(unittest.TestCase):
    def test_renderer_uses_xyz_layout_and_css_3d_connections(self) -> None:
        source = (FRONTEND / "life-map.js").read_text(encoding="utf-8")
        self.assertIn("depthBand", source)
        self.assertIn("--life-z", source)
        self.assertIn("--satellite-z", source)
        self.assertIn("univ-connection-layer", source)
        self.assertIn("univ-connection-3d", source)
        self.assertIn("add3dConnection", source)
        self.assertIn("rotateY", source)
        self.assertIn("translate3d", source)
        self.assertNotIn('createElementNS', source)
        self.assertNotIn('life-map__lines', source)

    def test_core_task_and_child_connections_are_separate(self) -> None:
        source = (FRONTEND / "life-map.js").read_text(encoding="utf-8")
        self.assertIn('child ? "is-child" : "is-core"', source)
        self.assertIn("arrangeSatellites", source)
        self.assertIn("systemPosition.z + 82 + 30 + satelliteZ", source)

    def test_focus_automatically_opens_existing_detail_panel(self) -> None:
        source = (FRONTEND / "univ-space.js").read_text(encoding="utf-8")
        self.assertIn("const openManagement", source)
        self.assertIn('document.body.classList.add("petit-univ-manage-open")', source)
        self.assertIn("openManagement();", source)
        self.assertIn('document.querySelector("#detail-panel")', source)

    def test_renderer_does_not_own_focus_overlay_behavior(self) -> None:
        source = (FRONTEND / "life-map.js").read_text(encoding="utf-8")
        self.assertNotIn("petit-univ-manage-open", source)
        self.assertNotIn("#detail-panel", source)
        self.assertNotIn("openFocusedDetail", source)


if __name__ == "__main__":
    unittest.main()
