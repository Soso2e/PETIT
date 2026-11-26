from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UiThemeConsistencyTests(unittest.TestCase):
    def test_unified_ui_uses_current_theme_attribute(self) -> None:
        css = (FRONTEND / "petit-ui-system.css").read_text(encoding="utf-8")
        self.assertIn('data-petit-theme="light"', css)
        self.assertNotIn('data-theme="light"', css)

    def test_shell_uses_theme_tokens_instead_of_dark_fixed_surfaces(self) -> None:
        css = (FRONTEND / "petit-four-area-shell.css").read_text(encoding="utf-8")
        self.assertIn("--petit-shell-bg", css)
        self.assertIn("--petit-shell-border", css)
        self.assertNotIn("rgb(5 7 17 / 88%)", css)
        self.assertNotIn("rgb(5 7 17 / 92%)", css)

    def test_preferences_define_dark_and_light_shell_tokens(self) -> None:
        css = (FRONTEND / "petit-ui-preferences.css").read_text(encoding="utf-8")
        self.assertIn(':root[data-petit-theme="dark"]', css)
        self.assertIn(':root[data-petit-theme="light"]', css)
        self.assertIn("--petit-shell-bg", css)
        self.assertIn("--petit-univ-bg", css)
        self.assertIn(':root[data-petit-theme="light"] .univ-viewport', css)

    def test_theme_preference_syncs_meta_theme_color(self) -> None:
        js = (FRONTEND / "petit-ui-preferences.js").read_text(encoding="utf-8")
        self.assertIn("syncMetaThemeColor", js)
        self.assertIn("root.dataset.petitTheme = state.theme", js)
        self.assertIn('"#f5f2eb"', js)
        self.assertIn('"#11100f"', js)

    def test_human_palette_defines_primary_and_data_tokens(self) -> None:
        css = (FRONTEND / "petit-ui-system.css").read_text(encoding="utf-8")
        self.assertIn("--ui-primary:#b04f3e", css)
        self.assertIn("--ui-primary:#9e4737", css)
        self.assertIn("--ui-data-1:", css)
        self.assertIn("--ui-data-4:", css)
        self.assertNotIn("rgba(190, 102, 255", (FRONTEND / "petit-ui-preferences.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
