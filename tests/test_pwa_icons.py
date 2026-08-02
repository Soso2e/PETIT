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


if __name__ == "__main__":
    unittest.main()
