from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class ThreeAreaAppShellTests(unittest.TestCase):
    def test_app_shell_defines_three_primary_areas(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        for label in ('label: "Univ"', 'label: "Tasks"', 'label: "PETIT"'):
            self.assertIn(label, source)
        self.assertNotIn('label: "Home"', source)
        self.assertNotIn('label: "Focus"', source)
        self.assertNotIn('textContent = "More"', source)
        self.assertNotIn('legacy.html?view=', source)

    def test_tab_switching_uses_direct_panel_sync(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn("const switchPanelDirectly", source)
        self.assertIn('panel.hidden = !active', source)
        self.assertIn('panel.setAttribute("aria-hidden", String(!active))', source)
        self.assertNotIn("target.click()", source)
        self.assertNotIn("clickPanelTrigger", source)

    def test_mobile_navigation_uses_top_right_icon_tabs(self):
        source = (FRONTEND / "petit-corner-shell.js").read_text(encoding="utf-8")
        style = (FRONTEND / "petit-corner-shell.css").read_text(encoding="utf-8")
        self.assertIn('planet:', source)
        self.assertIn('check:', source)
        self.assertIn('chat:', source)
        self.assertIn('.view-tabs.petit-corner-nav', style)
        self.assertIn('top: var(--petit-corner-top)', style)
        self.assertIn('.petit-corner-nav__label', style)
        self.assertIn('env(safe-area-inset-top)', style)

    def test_desktop_uses_corner_shell_instead_of_left_rail(self):
        source = (FRONTEND / "petit-corner-shell.css").read_text(encoding="utf-8")
        self.assertIn('.petit-area-rail', source)
        self.assertIn('display: none !important', source)
        self.assertIn('.petit-corner-status', source)
        self.assertIn('.petit-utility-dock', source)

    def test_univ_assets_are_versioned_loaded_and_bootstrapped(self):
        shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        version = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn("window.PETIT_ASSET_VERSION", shell)
        self.assertIn('/static/univ-space.css', shell)
        self.assertIn('/static/univ-space.js', shell)
        self.assertIn('/static/app_shell.js', version)
        self.assertIn('/static/petit-corner-shell.js', version)
        self.assertIn('/static/universe-webgl-hierarchy.js', version)
        self.assertIn('/static/universe-webgl-scene.js', version)
        self.assertIn('/static/universe-webgl-bridge.js', version)
        self.assertIn('script.dataset.petitBootstrap = key', version)
        self.assertIn('loadScript("/static/app_shell.js", "app-shell"', version)
        self.assertIn('loadScript("/static/petit-corner-shell.js", "corner-shell")', version)

    def test_version_is_v0180(self):
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn('globalThis.PETIT_VERSION = "v0.18.1"', source)
        self.assertIn('globalThis.PETIT_ASSET_VERSION = "0.18.1"', source)
        self.assertIn('window.PETIT_VERSION = globalThis.PETIT_VERSION', source)

    def test_universe_assets_use_current_version_without_duplicate_app_shell_loader(self):
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        chat_input = (FRONTEND / "chat_input.js").read_text(encoding="utf-8")
        self.assertNotIn("0.8.0", html)
        self.assertNotIn('loadSharedModule("/static/app_shell.js"', chat_input)
        self.assertIn("Array.from(document.scripts)", chat_input)

    def test_task_flow_reuses_universe_catalog_on_initialization(self):
        source = (FRONTEND / "task-flow.js").read_text(encoding="utf-8")
        initialize = source[source.index("  const initialize = () => {") :]
        self.assertIn("petit:tasks-updated", initialize)
        self.assertNotIn("void loadCatalog();", initialize)


if __name__ == "__main__":
    unittest.main()
