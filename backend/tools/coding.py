"""Conversation tools for separately approved, durable local coding tasks."""
from .registry import tool
from .. import coding_jobs as jobs, request_context


@tool(name="list_coding_repositories", description="開発用に利用者が明示許可したローカルGitルートを取得する。推測や全ドライブ探索はしない。",
      parameters={"type": "object", "properties": {}, "additionalProperties": False}, risk="safe_read")
def list_coding_repositories():
    return {"repositories": jobs.roots(), "providers": ["codex", "antigravity_cli"]}


@tool(name="delegate_coding_task", description="明示された開発依頼をCodex CLIかAntigravity CLIの別タスクへ渡す。確認画面で対象repository・目的・providerを確認する。元フォルダは変更せず開始時HEADのコピーで実装し、進捗は開発タスク画面で確認する。Push/PR/merge/任意Shellはしない。",
      parameters={"type": "object", "properties": {"repository": {"type": "string"}, "goal": {"type": "string"},
          "provider": {"type": "string", "enum": ["codex", "antigravity_cli"]}, "base_commit": {"type": "string"}, "task_id": {"type": "integer"}, "project_id": {"type": "string"}},
          "required": ["repository", "goal", "provider", "base_commit"], "additionalProperties": False}, requires_confirmation=True)
def delegate_coding_task(repository: str, goal: str, provider: str, base_commit: str, task_id: int | None = None, project_id: str | None = None):
    if request_context.local_only():
        raise ValueError("ローカル専用Threadから外部CLIへ開発依頼を送信しません。")
    request_id, _ = request_context.current_ids()
    if not request_id:raise ValueError("request_id_required")
    return jobs.create("coding:" + request_id, repository, goal, provider, approved=True, task_id=task_id, project_id=project_id, base_commit=base_commit)


@tool(name="get_coding_task_status", description="開発CLIのタスク状態・変更・静的チェックと、実テストや実機の未確認を取得する。",
      parameters={"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"], "additionalProperties": False}, risk="safe_read")
def get_coding_task_status(job_id: str):return jobs.get(job_id)


@tool(name="cancel_coding_task", description="実行中または待機中の開発タスクへ取消要求を出す。実行済み変更と専用コピーは保持する。",
      parameters={"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"], "additionalProperties": False}, requires_confirmation=True)
def cancel_coding_task(job_id: str):return jobs.cancel(job_id)
