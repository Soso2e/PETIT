from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UnifiedUiSystemTests(unittest.TestCase):
    def test_universe_bootstrap_loads_unified_assets(self) -> None:
        chat = (FRONTEND / "chat_input.js").read_text(encoding="utf-8")
        shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn("petit-ui-system.css", chat)
        self.assertIn("petit-ui-system.js", chat)
        self.assertIn("petit-motion.css", chat)
        self.assertIn("petit-motion.js", chat)
        self.assertIn("petit-galaxy.css", shell)

    def test_design_system_supports_light_mode_and_reduced_motion(self) -> None:
        source = (FRONTEND / "petit-ui-system.css").read_text(encoding="utf-8")
        galaxy = (FRONTEND / "petit-galaxy.css").read_text(encoding="utf-8")
        self.assertIn('html[data-theme="light"]', source)
        self.assertIn('@media (prefers-reduced-motion: reduce)', galaxy)
        self.assertIn(".petit-context-bar", galaxy)
        self.assertIn("--galaxy-panel", galaxy)

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

    def test_version_is_v090(self) -> None:
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn('window.PETIT_VERSION = "v0.9.0"', source)
        self.assertIn('window.PETIT_ASSET_VERSION = "0.9.0"', source)


if __name__ == "__main__":
    unittest.main()
