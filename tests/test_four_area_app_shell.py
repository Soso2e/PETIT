from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class FourAreaAppShellTests(unittest.TestCase):
    def test_app_shell_defines_chat_first_four_primary_areas(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('const HOME_VIEW = "chat"', source)
        for label in ('label: "Chat"', 'label: "Univ"', 'label: "Develop"', 'label: "Dashboard"'):
            self.assertIn(label, source)
        self.assertEqual(source.count('{ view: "'), 4)
        self.assertIn('data-shell-target="tasks"', source)
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

    def test_mobile_navigation_uses_bottom_four_tabs(self):
        source = (FRONTEND / "petit-corner-shell.js").read_text(encoding="utf-8")
        style = (FRONTEND / "petit-corner-shell.css").read_text(encoding="utf-8")
        self.assertIn('planet:', source)
        self.assertIn('code:', source)
        self.assertIn('chat:', source)
        self.assertIn('development: { label: "Develop"', source)
        self.assertIn('stats: { label: "Dashboard"', source)
        self.assertIn('.view-tabs.petit-corner-nav', style)
        self.assertIn('grid-template-columns: repeat(4, minmax(0, 1fr))', style)
        self.assertIn('inset: auto max(8px, env(safe-area-inset-right))', style)
        self.assertIn('.petit-corner-nav__label', style)
        self.assertIn('env(safe-area-inset-bottom)', style)

    def test_desktop_uses_adaptive_workspace_rail(self):
        source = (FRONTEND / "petit-corner-shell.css").read_text(encoding="utf-8")
        self.assertIn('.petit-area-rail', source)
        self.assertIn('display: flex !important', source)
        self.assertIn('@media (max-width: 959px)', source)
        self.assertIn('.petit-corner-status', source)
        self.assertIn('.petit-utility-dock', source)

    def test_workspace_has_command_palette_and_keyboard_shortcuts(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('petit-command-palette', source)
        self.assertIn('event.key.toLowerCase() === "k"', source)
        self.assertIn('event.key === ","', source)
        self.assertIn('data-shell-target="settings"', source)

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

    def test_version_and_asset_version_stay_in_sync(self):
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        version_match = re.search(r'globalThis\.PETIT_VERSION = "v(\d+\.\d+\.\d+)"', source)
        asset_match = re.search(r'globalThis\.PETIT_ASSET_VERSION = "(\d+\.\d+\.\d+)"', source)
        self.assertIsNotNone(version_match)
        self.assertIsNotNone(asset_match)
        self.assertEqual(version_match.group(1), asset_match.group(1))
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

    def test_mobile_chat_panel_clears_bottom_navigation_bar(self):
        polish_style = (FRONTEND / "petit-ui-polish.css").read_text(encoding="utf-8")
        corner_style = (FRONTEND / "petit-corner-shell.css").read_text(encoding="utf-8")
        univ_style = (FRONTEND / "univ-space.css").read_text(encoding="utf-8")

        # Chat panel in mobile view must clear bottom nav
        self.assertIn('body.petit-chat-screen [data-view-panel="chat"]', polish_style)
        self.assertIn('--petit-bottom-nav-height', polish_style)

        # Main view padding-bottom must accommodate bottom nav height
        self.assertIn('padding-bottom: calc(var(--petit-bottom-nav-height', corner_style)
        self.assertIn('padding-bottom: calc(90px + env(safe-area-inset-bottom)) !important;', corner_style)

        # Tab navigation must remain 4 columns even in univ-space
        self.assertNotIn('grid-template-columns: repeat(3, minmax(0, 1fr))', univ_style)
        self.assertIn('grid-template-columns: repeat(4, minmax(0, 1fr))', univ_style)


if __name__ == "__main__":
    unittest.main()
