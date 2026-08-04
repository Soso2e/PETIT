from __future__ import annotations

import json
import struct
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
LEGACY_HTML = FRONTEND / "legacy.html"


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)


class MobileWorkCompanionStaticTests(unittest.TestCase):
    def test_index_loads_session_before_chat_and_companion_after_voice(self) -> None:
        html = LEGACY_HTML.read_text(encoding="utf-8")
        self.assertLess(html.index('/static/session.js'), html.index('/static/app.js'))
        self.assertLess(html.index('/static/voice.js'), html.index('/static/companion.js'))
        self.assertLess(html.index('/static/companion.js'), html.index('/static/shell.js'))
        for element_id in (
            "work-task",
            "work-toggle",
            "work-continue",
            "work-frequency",
            "work-elapsed",
            "history-toggle",
            "dashboard-tasks",
            "dashboard-schedule",
        ):
            self.assertIn(f'id="{element_id}"', html)

    def test_app_shell_has_four_distinct_views_and_mobile_navigation(self) -> None:
        html = LEGACY_HTML.read_text(encoding="utf-8")
        for view in ("today", "chat", "notifications", "settings"):
            self.assertIn(f'data-app-view="{view}"', html)
            self.assertIn(f'data-app-nav="{view}"', html)
        self.assertIn('class="app-shell"', html)
        self.assertIn('class="app-sidebar"', html)
        self.assertIn('id="notification-panel"', html)
        self.assertIn('id="chat-form"', html)

        css = (FRONTEND / "style.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: var(--sidebar-width) minmax(0, 1fr)", css)
        self.assertIn("@media (max-width: 680px)", css)
        self.assertIn("position: fixed", css)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", css)

    def test_app_shell_html_has_unique_ids_and_closed_topbar(self) -> None:
        html = LEGACY_HTML.read_text(encoding="utf-8")
        parser = IdCollector()
        parser.feed(html)
        duplicates = [element_id for element_id, count in Counter(parser.ids).items() if count > 1]

        self.assertEqual(duplicates, [])
        self.assertLess(html.index("</header>"), html.index('<main class="view-stack">'))

    def test_shell_navigation_supports_prompts_and_notification_deep_links(self) -> None:
        source = (FRONTEND / "shell.js").read_text(encoding="utf-8")
        self.assertIn("petit_active_view", source)
        self.assertIn("data-chat-prompt", source)
        self.assertIn('params.has("task") || params.has("notification")', source)
        self.assertIn('document.dispatchEvent(new CustomEvent("petit:viewchange"', source)
        self.assertIn("window.PETITShell", source)

        service_worker = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('const CACHE_NAME = "petit-shell-v0.14.0"', service_worker)
        self.assertIn('const ACTIVE_CACHE_NAME = `${CACHE_NAME}-corner-shell-v0.14.0`', service_worker)
        self.assertIn('"/static/petit-galaxy.css"', service_worker)
        self.assertIn('"/static/shell.js"', service_worker)
        self.assertIn('"/static/branding/icon_logo.png"', service_worker)
        self.assertIn('"/static/branding/name_logo.png"', service_worker)

    def test_manifest_is_valid_and_standalone(self) -> None:
        manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertTrue(manifest["icons"])
        self.assertEqual(
            {icon["purpose"] for icon in manifest["icons"]},
            {"any", "maskable"},
        )

    def test_pwa_icons_are_valid_png_files_with_declared_sizes(self) -> None:
        manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
        for icon in manifest["icons"]:
            if icon["type"] == "image/svg+xml":
                self.assertEqual(icon["sizes"], "any")
                self.assertTrue((FRONTEND / icon["src"].split("?", 1)[0].removeprefix("/static/")).is_file())
                continue
            self.assertEqual(icon["type"], "image/png")
            path = FRONTEND / icon["src"].split("?", 1)[0].removeprefix("/static/")
            data = path.read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(data[-12:], b"\x00\x00\x00\x00IEND\xaeB`\x82")
            width, height = struct.unpack(">II", data[16:24])
            declared_size = tuple(int(value) for value in icon["sizes"].split("x"))
            self.assertEqual((width, height), declared_size)

    def test_apple_touch_icon_is_valid_180px_png(self) -> None:
        data = (FRONTEND / "apple-touch-icon.png").read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(data[-12:], b"\x00\x00\x00\x00IEND\xaeB`\x82")
        self.assertEqual(struct.unpack(">II", data[16:24]), (180, 180))

    def test_pwa_icon_references_use_current_png_assets(self) -> None:
        manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
        manifest_sources = {icon["src"] for icon in manifest["icons"]}
        self.assertEqual(
            manifest_sources,
            {
                "/static/icon-desktop.svg?v=2",
                "/static/icon-192.png?v=2",
                "/static/icon-512.png?v=2",
                "/static/icon-maskable-192.png?v=2",
                "/static/icon-maskable-512.png?v=2",
            },
        )
        shortcut_sources = {
            icon["src"]
            for shortcut in manifest.get("shortcuts", [])
            for icon in shortcut.get("icons", [])
        }
        self.assertEqual(shortcut_sources, {"/static/icon-192.png?v=2"})

        service_worker = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        for source in manifest_sources | shortcut_sources | {"/static/apple-touch-icon.png"}:
            self.assertIn(source.split("?", 1)[0], service_worker)
        self.assertNotIn("icon-192.jpg", service_worker)
        self.assertNotIn("icon-512.jpg", service_worker)

        notifications = (ROOT / "backend" / "notifications.py").read_text(encoding="utf-8")
        self.assertIn('"icon": "/static/icon-192.png"', notifications)
        self.assertNotIn("icon-192.jpg", notifications)

    def test_brand_logo_sources_are_preserved(self) -> None:
        for filename in ("name_logo.png", "icon_logo.png"):
            data = (FRONTEND / "branding" / filename).read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(data[-12:], b"\x00\x00\x00\x00IEND\xaeB`\x82")

    def test_session_split_and_internal_prompt_filter_are_present(self) -> None:
        source = (FRONTEND / "session.js").read_text(encoding="utf-8")
        self.assertIn("2 * 60 * 60 * 1000", source)
        self.assertIn("[PETIT_INTERNAL_EVENT]", source)
        self.assertIn('/api/conversations', source)

    def test_companion_is_foreground_only_and_keeps_three_rallies(self) -> None:
        source = (FRONTEND / "companion.js").read_text(encoding="utf-8")
        self.assertIn("const MAX_VISIBLE_MESSAGES = 6", source)
        self.assertIn('document.visibilityState === "visible"', source)
        self.assertIn("10 * 60 * 1000", source)
        self.assertIn("Highタスク", source)
        self.assertIn("作業モードを終了したよ", source)
        self.assertIn('/api/work-sessions', source)
        self.assertIn('state.awaitingResponse', source)
        self.assertIn('maximumLegacyMs', source)

    def test_chat_session_commands_bypass_agent_and_keep_button_flow(self) -> None:
        source = (FRONTEND / "companion.js").read_text(encoding="utf-8")
        self.assertIn("classifySessionCommand", source)
        self.assertIn("handleSessionCommand", source)
        self.assertIn("event.stopImmediatePropagation()", source)
        self.assertIn("workSessionId", source)
        self.assertIn("pauseReason", source)
        self.assertIn("endWorkImmediately", source)
        self.assertIn('workPauseEl?.addEventListener("click", pauseOrResume)', source)
        self.assertIn('workEndEl?.addEventListener("click", () => void endWork())', source)
        self.assertIn("PETITの音声が途中で停止する", "PETITの音声が途中で停止する")
        self.assertIn("isPhenomenonReport", source)
        self.assertIn("音声", source)
        command_handler = source[source.index("const handleSessionCommand"):source.index("const tick")]
        self.assertNotIn('/api/chat', command_handler)
        self.assertNotIn('/api/actions/', command_handler)
        self.assertNotIn('Notion', command_handler)

    def test_service_worker_never_caches_api_requests(self) -> None:
        source = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('url.pathname.startsWith("/api/")', source)
        self.assertIn("fetch(request)", source)
        self.assertIn('self.addEventListener("push"', source)
        self.assertIn('self.addEventListener("notificationclick"', source)

    def test_enabling_push_enables_work_session_check_ins(self) -> None:
        source = (FRONTEND / "notifications.js").read_text(encoding="utf-8")
        self.assertIn('input[data-category="work_session"]', source)
        self.assertIn("Push通知と作業セッションの声かけを有効にしました", source)


if __name__ == "__main__":
    unittest.main()
