from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UnivPointerInteractionTests(unittest.TestCase):
    def test_focus_orbit_does_not_follow_pointer_without_drag(self):
        source = (ROOT / "frontend" / "universe-next.js").read_text(encoding="utf-8")

        self.assertNotIn("installParallax", source)
        self.assertNotIn('card.addEventListener("pointermove"', source)
        self.assertNotIn("--orbit-parallax-x", source)
        self.assertNotIn("--orbit-parallax-y", source)

    def test_univ_camera_rotation_remains_drag_only(self):
        source = (ROOT / "frontend" / "univ-space.js").read_text(encoding="utf-8")

        self.assertIn('frame.addEventListener("pointerdown"', source)
        self.assertIn('frame.addEventListener("pointermove"', source)
        self.assertIn("if (!state.dragging || state.pointerId !== event.pointerId) return;", source)


if __name__ == "__main__":
    unittest.main()
