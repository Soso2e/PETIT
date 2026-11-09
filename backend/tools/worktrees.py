"""Worktree Tools for agents (H4). L1 runs without confirmation; a PR needs approval."""
from __future__ import annotations

from typing import Any, Callable

from .. import worktrees
from .registry import tool

ID = {"worktree_id": {"type": "string", "description": "open_worktree が返した worktree_id"}}


def _safe(func: Callable[..., dict]) -> Callable[..., dict]:
    def wrapper(**kwargs: Any) -> dict:
        try:
            return func(**kwargs)
        except worktrees.WorktreeError as exc:
            return {"ok": False, "error": str(exc)}
    wrapper.__name__ = func.__name__
    return wrapper


@tool(name="open_worktree",
      description=("開発用に登録済みのリポジトリから、PETIT Home の worktrees/ に作業用 worktree と petit/ ブランチを作る。"
                   "コードの変更はこの中でだけ行う。repository は list_coding_repositories の path。"),
      parameters={"type": "object", "properties": {"repository": {"type": "string"}, "task": {"type": "string", "description": "作業内容の短い説明（ブランチ名に使う）"}},
                  "required": ["repository", "task"], "additionalProperties": False},
      risk="low_risk_write")
def open_worktree(repository: str, task: str) -> dict:
    return _safe(worktrees.open_worktree)(repository=repository, task=task)


@tool(name="list_worktrees", description="開いている作業用 worktree の一覧。",
      parameters={"type": "object", "properties": {}, "additionalProperties": False}, risk="safe_read")
def list_worktrees() -> dict:
    return {"worktrees": worktrees.list_open()}


@tool(name="get_worktree_status", description="worktree の未 commit の変更・commit 一覧・差分の統計。",
      parameters={"type": "object", "properties": ID, "required": ["worktree_id"], "additionalProperties": False},
      risk="safe_read")
def get_worktree_status(worktree_id: str) -> dict:
    return _safe(worktrees.status)(worktree_id=worktree_id)


# Repeatable and local to the worktree, so it is not deduplicated like a write receipt.
@tool(name="run_worktree_check",
      description=("worktree でテスト・ビルド・静的検査を実行する（例: [\"python\",\"-m\",\"pytest\",\"-q\"]、[\"npm\",\"test\"]、"
                   "[\"go\",\"test\",\"./...\"]）。シェルは使わず、許可されたテスト系コマンドだけ。結果の末尾を返す。"),
      parameters={"type": "object", "properties": {**ID, "command": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 40}},
                  "required": ["worktree_id", "command"], "additionalProperties": False},
      risk="safe_read")
def run_worktree_check(worktree_id: str, command: list[str]) -> dict:
    return _safe(worktrees.run_check)(worktree_id=worktree_id, command=command)


@tool(name="commit_worktree", description="worktree の変更をすべて commit する（petit/ ブランチ上）。",
      parameters={"type": "object", "properties": {**ID, "message": {"type": "string"}},
                  "required": ["worktree_id", "message"], "additionalProperties": False},
      risk="low_risk_write")
def commit_worktree(worktree_id: str, message: str) -> dict:
    return _safe(worktrees.commit)(worktree_id=worktree_id, message=message)


@tool(name="push_worktree",
      description=("worktree の petit/ ブランチを origin へ push する（main など既定ブランチへは push できない、force push なし）。"
                   "commit には commit_worktree が返した commit を渡す。"),
      parameters={"type": "object", "properties": {**ID, "commit": {"type": "string"}},
                  "required": ["worktree_id", "commit"], "additionalProperties": False},
      risk="low_risk_write")
def push_worktree(worktree_id: str, commit: str) -> dict:
    return _safe(worktrees.push)(worktree_id=worktree_id, commit=commit)


@tool(name="create_worktree_pull_request",
      description="push 済みの petit/ ブランチから既定ブランチへの Pull Request を作る。実行前にユーザーの承認を取る。",
      parameters={"type": "object", "properties": {**ID, "title": {"type": "string"}, "body": {"type": "string"}},
                  "required": ["worktree_id", "title", "body"], "additionalProperties": False},
      risk="confirm_write", preview=worktrees.pull_request_preview)
def create_worktree_pull_request(worktree_id: str, title: str, body: str) -> dict:
    return _safe(worktrees.create_pull_request)(worktree_id=worktree_id, title=title, body=body)


@tool(name="close_worktree", description="作業が終わった worktree のフォルダを片付ける。ブランチと commit は残す。",
      parameters={"type": "object", "properties": ID, "required": ["worktree_id"], "additionalProperties": False},
      risk="low_risk_write")
def close_worktree(worktree_id: str) -> dict:
    return _safe(worktrees.close)(worktree_id=worktree_id)
