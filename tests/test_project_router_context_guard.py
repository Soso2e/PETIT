import unittest
from unittest.mock import patch
from backend import project_router


class ProjectRouterContextGuardTests(unittest.TestCase):
    def test_noun_compounds_are_not_project_actions(self):
        for noun in ("ゲーム開発", "Web開発", "AI開発", "アプリ開発"):
            with self.subTest(noun=noun), patch.object(project_router.project_continuity, "get_active_project") as active:
                self.assertEqual(project_router.resolve_project(noun, user_id="owner").kind, "none")
                active.assert_not_called()

    def test_explicit_actions_keep_the_entire_project_name(self):
        for message in ("PETIT開発する", "PETITの開発を進める", "PETITやる", "PETITに戻る", "PETITの続きやる"):
            with self.subTest(message=message), patch.object(project_router.project_continuity, "get_active_project", return_value=None), patch.object(project_router, "_match_alias", return_value=([{"id": "p", "name": "PETIT"}], "PETIT", 1.0)) as aliases:
                result = project_router.resolve_project(message, user_id="owner")
                self.assertEqual(result.kind, "resolved")
                aliases.assert_called_once_with("PETIT")

    def test_compound_project_name_is_preserved_with_explicit_verb(self):
        self.assertEqual(project_router._parse_action("ゲーム開発やる"), ("ゲーム開発", "やる"))
