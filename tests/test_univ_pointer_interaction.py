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
        self.assertIn('const yawSensitivity = event.pointerType === "touch" ? 0.14 : 0.11', source)

    def test_mobile_univ_supports_two_finger_pinch_without_overwriting_drag(self):
        source = (ROOT / "frontend" / "univ-space.js").read_text(encoding="utf-8")

        self.assertIn("const touchPoints = new Map();", source)
        self.assertIn("if (touchPoints.size === 2)", source)
        self.assertIn("pinchStartZoom * (distance / pinchStartDistance)", source)
        self.assertIn("stopDrag(frame);", source)
        self.assertIn("for (const pointerId of touchPoints.keys())", source)
        self.assertIn('frame.addEventListener("pointercancel", endPointer)', source)

    def test_planet_tap_is_not_captured_as_background_drag(self):
        source = (ROOT / "frontend" / "univ-space.js").read_text(encoding="utf-8")
        pointerdown = source.index('frame.addEventListener("pointerdown"')
        pointermove = source.index('frame.addEventListener("pointermove"')
        block = source[pointerdown:pointermove]

        interactive_guard = block.index('event.target.closest("button, a, input, select, textarea, .life-map__core, #detail-panel")')
        single_pointer_capture = block.rindex("frame.setPointerCapture?.(event.pointerId)")
        self.assertLess(interactive_guard, single_pointer_capture)
        self.assertIn("frame.hasPointerCapture?.(pointerId)", source)

    def test_mobile_controls_have_touch_sized_targets(self):
        source = (ROOT / "frontend" / "univ-space.js").read_text(encoding="utf-8")

        self.assertIn('@media (pointer: coarse)', source)
        self.assertIn("min-width: 44px", source)
        self.assertIn("min-height: 44px", source)
        self.assertIn("Tap: focus · Drag: orbit · Pinch: zoom", source)


if __name__ == "__main__":
    unittest.main()
