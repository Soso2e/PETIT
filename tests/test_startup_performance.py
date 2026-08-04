from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class StartupPerformanceTests(unittest.TestCase):
    def test_frontend_startup_does_not_wait_for_integrations(self) -> None:
        source = (FRONTEND / "app.js").read_text(encoding="utf-8")
        initialize = source.split("function initialize()", 1)[1]

        self.assertIn("inputEl.focus();", initialize)
        self.assertIn("void loadModelRouting();", initialize)
        self.assertIn("void checkHealth();", initialize)
        self.assertIn("void restoreConversationOrOpener();", initialize)
        self.assertNotIn("await loadModelRouting();", initialize)
        self.assertNotIn("await checkHealth();", initialize)

    def test_job_polling_is_deferred_and_not_subsecond(self) -> None:
        source = (FRONTEND / "app.js").read_text(encoding="utf-8")
        self.assertIn("window.setTimeout(() =>", source)
        self.assertIn("window.setInterval(pollJobs, 2000)", source)
        self.assertNotIn("setInterval(pollJobs, 700)", source)


if __name__ == "__main__":
    unittest.main()
