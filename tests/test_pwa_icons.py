import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class PwaIconTests(unittest.TestCase):
    def test_manifest_separates_desktop_and_maskable_icons(self) -> None:
        manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
        icons = manifest["icons"]

        desktop = [icon for icon in icons if icon.get("src", "").startswith("/static/icon-desktop.svg")]
        maskable = [icon for icon in icons if icon.get("purpose") == "maskable"]

        self.assertEqual(len(desktop), 1)
        self.assertEqual(desktop[0]["sizes"], "any")
        self.assertEqual(desktop[0]["type"], "image/svg+xml")
        self.assertEqual(desktop[0]["purpose"], "any")
        self.assertGreaterEqual(len(maskable), 2)

    def test_all_manifest_icon_files_exist(self) -> None:
        manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
        for icon in manifest["icons"]:
            relative_path = icon["src"].split("?", 1)[0].removeprefix("/static/")
            self.assertTrue((FRONTEND / relative_path).is_file(), icon["src"])

    def test_service_worker_precaches_desktop_icon(self) -> None:
        service_worker = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('"/static/icon-desktop.svg"', service_worker)
        self.assertIn('const CACHE_NAME =', service_worker)

    def test_html_entrypoints_declare_apple_touch_icon(self) -> None:
        for name in ("universe.html", "index.html", "legacy.html"):
            html = (FRONTEND / name).read_text(encoding="utf-8")
            self.assertIn('rel="apple-touch-icon"', html, name)
            self.assertIn('/static/apple-touch-icon.png', html, name)
            self.assertIn('name="apple-mobile-web-app-title" content="PETIT"', html, name)
            self.assertIn('rel="manifest" href="/static/manifest.webmanifest"', html, name)

    def test_root_apple_touch_icon_routes(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend import frontend_api

        app = FastAPI()
        frontend_api.register(app)
        client = TestClient(app)

        for path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            res = client.get(path)
            self.assertEqual(res.status_code, 200, path)
            self.assertEqual(res.headers.get("content-type"), "image/png", path)
            self.assertTrue(res.content.startswith(b"\x89PNG\r\n\x1a\n"), path)


if __name__ == "__main__":
    unittest.main()
