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
        version = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn("petit-ui-system.css", chat)
        self.assertIn("petit-ui-system.js", chat)
        self.assertIn("petit-motion.css", chat)
        self.assertIn("petit-motion.js", chat)
        self.assertIn("petit-galaxy.css", shell)
        self.assertIn("univ-space.css", shell)
        self.assertIn("petit-corner-shell.js", version)
        self.assertIn("universe-webgl-scene.js", version)
        self.assertIn("universe-webgl-bridge.js", version)

    def test_design_system_supports_light_mode_and_reduced_motion(self) -> None:
        source = (FRONTEND / "petit-ui-system.css").read_text(encoding="utf-8")
        galaxy = (FRONTEND / "petit-galaxy.css").read_text(encoding="utf-8")
        univ = (FRONTEND / "univ-space.css").read_text(encoding="utf-8")
        webgl = (FRONTEND / "universe-webgl-scene.css").read_text(encoding="utf-8")
        corner = (FRONTEND / "petit-corner-shell.css").read_text(encoding="utf-8")
        self.assertIn('html[data-petit-theme="light"]', source)
        self.assertIn('@media (prefers-reduced-motion: reduce)', galaxy)
        self.assertIn('@media (prefers-reduced-motion: reduce)', univ)
        self.assertIn('@media (prefers-reduced-motion: reduce)', webgl)
        self.assertIn('@media (prefers-reduced-motion: reduce)', corner)
        self.assertIn(".petit-context-bar", galaxy)
        self.assertIn("--galaxy-panel", galaxy)

    def test_ui_script_sets_accessibility_and_context_state(self) -> None:
        source = (FRONTEND / "petit-ui-system.js").read_text(encoding="utf-8")
        self.assertIn('setAttribute("role", "tablist")', source)
        self.assertIn('setAttribute("role", "tabpanel")', source)
        self.assertIn("MutationObserver", source)
        self.assertIn("petit_ui_theme", source)

    def test_corner_shell_exposes_three_primary_icons_and_utilities(self) -> None:
        source = (FRONTEND / "petit-corner-shell.js").read_text(encoding="utf-8")
        style = (FRONTEND / "petit-corner-shell.css").read_text(encoding="utf-8")
        self.assertIn('planet:', source)
        self.assertIn('check:', source)
        self.assertIn('chat:', source)
        self.assertIn('data-corner-reminders', source)
        self.assertIn('data-corner-menu-settings', source)
        self.assertIn('dock.querySelector("[data-corner-settings]")?.addEventListener("click", () => activate("settings"))', source)
        self.assertIn('<circle cx="12" cy="12" r="3"></circle>', source)
        self.assertNotIn('transform="translate(2 0)', source)
        self.assertNotIn('/static/legacy.html?view=settings', source)
        self.assertIn('.petit-corner-status', style)
        self.assertIn('.petit-corner-nav', style)
        self.assertIn('.petit-utility-dock', style)
        self.assertIn('env(safe-area-inset-top)', style)
        self.assertIn('env(safe-area-inset-bottom)', style)

    def test_service_worker_uses_asset_version_for_cache_generation(self) -> None:
        source = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('importScripts("/static/petit-version.js")', source)
        self.assertIn('self.PETIT_ASSET_VERSION', source)
        self.assertIn('url.searchParams.set("v", self.PETIT_ASSET_VERSION)', source)
        self.assertNotIn('petit-shell-v0.15.0-webgl1', source)
        self.assertIn('/static/univ-space.js', source)
        self.assertIn('/static/univ-space.css', source)
        self.assertIn('/static/universe-render-scheduler.js', source)
        self.assertIn('/static/universe-webgl-scene.js', source)
        self.assertIn('/static/universe-webgl-scene.css', source)
        self.assertIn('/static/universe-webgl-bridge.js', source)
        self.assertIn('/static/petit-corner-shell.js', source)
        self.assertIn('/static/petit-corner-shell.css', source)

    def test_universe_static_assets_use_shared_asset_version(self) -> None:
        source = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/static/petit-version.js"></script>', source)
        self.assertIn('PetitAssetVersion.writeStylesheets', source)
        self.assertIn('PetitAssetVersion.writeScripts', source)
        self.assertIn('PetitVersionBootstrap.start()', source)
        self.assertNotRegex(source, re.compile(r'/static/[^"\']+\.(?:css|js)\?v=\d'))

    def test_chat_input_keeps_ime_guard(self) -> None:
        source = (FRONTEND / "chat_input.js").read_text(encoding="utf-8")
        self.assertRegex(source, re.compile(r"event\.isComposing|keyCode\s*===\s*229"))
        self.assertIn("form.requestSubmit()", source)

    def test_version_and_asset_version_stay_in_sync(self) -> None:
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        version_match = re.search(r'globalThis\.PETIT_VERSION = "v(\d+\.\d+\.\d+)"', source)
        asset_match = re.search(r'globalThis\.PETIT_ASSET_VERSION = "(\d+\.\d+\.\d+)"', source)
        self.assertIsNotNone(version_match)
        self.assertIsNotNone(asset_match)
        self.assertEqual(version_match.group(1), asset_match.group(1))
        self.assertIn('window.PETIT_VERSION = globalThis.PETIT_VERSION', source)
        self.assertIn('updateViaCache: "none"', source)

    def test_developer_options_and_chat_log_export_ui(self) -> None:
        """開発者オプションおよび会話ログ取得UIの連携要素を検証する。"""
        universe_html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        preferences_css = (FRONTEND / "petit-ui-preferences.css").read_text(encoding="utf-8")
        preferences_js = (FRONTEND / "petit-ui-preferences.js").read_text(encoding="utf-8")
        universe_app = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")

        # HTML: 開発者限定のログ取得ボタンとモーダルダイアログ
        self.assertIn('id="chat-export-log-btn"', universe_html)
        self.assertIn('data-developer-only', universe_html)
        self.assertIn('id="chat-log-dialog"', universe_html)
        self.assertIn('id="chat-log-output"', universe_html)
        self.assertIn('id="chat-log-copy"', universe_html)

        # CSS: 開発者モードOFF時の非表示ルールとモーダルスタイル
        self.assertIn(':root:not([data-petit-developer="true"]) [data-developer-only]', preferences_css)
        self.assertIn('.chat-log-dialog', preferences_css)

        # JS: 開発者モード設定、トグル、およびログエクスポート制御
        self.assertIn('petit_developer_mode', preferences_js)
        self.assertIn('data-petit-developer-choice', preferences_js)
        self.assertIn('setupChatLogDialog', universe_app)
        self.assertIn('window.PetitChatLog', universe_app)
        self.assertIn('history: () => [...state.history]', universe_app)


if __name__ == "__main__":
    unittest.main()

