from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class ChatMotionComponentsTests(unittest.TestCase):
    def test_chat_motion_assets_exist_and_are_registered(self) -> None:
        js = (FRONTEND / "petit-chat-motion.js").read_text(encoding="utf-8")
        css = (FRONTEND / "petit-chat-motion.css").read_text(encoding="utf-8")
        universe_html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        sw = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")

        self.assertIn("window.PetitChatMotion", js)
        self.assertIn(".petit-prompt-status", css)
        self.assertIn(".petit-stream-bubble", css)
        self.assertIn("/static/petit-chat-motion.css", universe_html)
        self.assertIn("/static/petit-chat-motion.js", universe_html)
        self.assertIn("/static/petit-chat-motion.css", sw)
        self.assertIn("/static/petit-chat-motion.js", sw)

    def test_spring_constants_and_reduced_motion_are_preserved(self) -> None:
        js = (FRONTEND / "petit-chat-motion.js").read_text(encoding="utf-8")
        css = (FRONTEND / "petit-chat-motion.css").read_text(encoding="utf-8")

        # Prompt box springs: height (420, 34), status (380, 30), send/stop (520, 30)
        self.assertIn("S(initialH, 420, 34)", js)
        self.assertIn("S(0, 380, 30)", js)
        self.assertIn("S(0, 520, 30)", js)
        # Streaming reply springs: message entrance (300, 22), bubble (260, 26), think (300, 30), words (340, 26)
        self.assertIn("S(0, 300, 22)", js)
        self.assertIn("260, 26", js)
        self.assertIn("S(1, 300, 30)", js)
        self.assertIn("S(0, 340, 26)", js)

        self.assertIn("prefers-reduced-motion: reduce", js)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def test_chat_and_develop_wire_motion_components(self) -> None:
        universe_app = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        chat_input = (FRONTEND / "chat_input.js").read_text(encoding="utf-8")
        development = (FRONTEND / "development.js").read_text(encoding="utf-8")

        self.assertIn("createPromptBox", universe_app)
        self.assertIn("createStreamingController", universe_app)
        self.assertIn("animateMessageIn", universe_app)
        self.assertIn("_petitPromptBox", chat_input)
        self.assertIn("createPromptBox", development)
        self.assertIn("is-streaming-status", development)


if __name__ == "__main__":
    unittest.main()
