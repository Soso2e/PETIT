from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UnifiedUiSystemTests(unittest.TestCase):
    def test_universe_bootstrap_loads_unified_assets(self) -> None:
        source = (FRONTEND / "chat_input.js").read_text(encoding="utf-8")
        self.assertIn("petit-ui-system.css", source)
        self.assertIn("petit-ui-system.js", source)

    def test_design_system_supports_light_mode_and_reduced_motion(self) -> None:
        source = (FRONTEND / "petit-ui-system.css").read_text(encoding="utf-8")
        self.assertIn('html[data-theme="light"]', source)
        self.assertIn("@media (prefers-reduced-motion:reduce)", source)
        self.assertIn(".petit-context-bar", source)
        self.assertIn("perspective:", source)

    def test_ui_script_sets_accessibility_and_context_state(self) -> None:
        source = (FRONTEND / "petit-ui-system.js").read_text(encoding="utf-8")
        self.assertIn('setAttribute("role", "tablist")', source)
        self.assertIn('setAttribute("role", "tabpanel")', source)
        self.assertIn("MutationObserver", source)
        self.assertIn("petit_ui_theme", source)

    def test_chat_input_keeps_ime_guard(self) -> None:
        source = (FRONTEND / "chat_input.js").read_text(encoding="utf-8")
        self.assertRegex(source, re.compile(r"event\.isComposing|keyCode\s*===\s*229"))
        self.assertIn("form.requestSubmit()", source)

    def test_version_is_v070(self) -> None:
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn('window.PETIT_VERSION = "v0.7.0"', source)


if __name__ == "__main__":
    unittest.main()
