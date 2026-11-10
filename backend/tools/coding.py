"""Conversation tools for separately approved, durable local coding tasks."""
from .registry import tool
from .. import coding_jobs as jobs, development_models, request_context


@tool(name="list_coding_repositories", description="開発用に利用者が登録したフォルダとGitルートを取得する。対象パスを推測しない。",
      parameters={"type": "object", "properties": {}, "additionalProperties": False}, risk="safe_read")
def list_coding_repositories():
    return {"repositories": jobs.roots(), "providers": ["codex", "antigravity_cli", "claude_code"]}


@tool(name="add_coding_repository",
      description="開発・調査対象のローカルGitリポジトリまたは作業フォルダをPETITに登録する。利用者が『このリポジトリ登録して』『PETITのパスこれ。登録できる？』と言ったときに使う。サーバー上の絶対パスを指定する。",
      parameters={"type": "object", "properties": {
          "path": {"type": "string", "minLength": 1, "maxLength": 1000, "description": "登録するフォルダの絶対パス（例: C:\\#Project\\Server\\PersonalAssistant_PETIT）"}
      }, "required": ["path"], "additionalProperties": False},
      risk="low_risk_write")
def add_coding_repository(path: str):
    import os
    from pathlib import Path
    from .. import setup_store as settings, development_pc

    raw_path = str(path or "").strip()
    p = Path(raw_path)
    if not p.is_absolute():
        raise ValueError("サーバーPC上の絶対パスを指定してください。")
    safe_path = jobs.project_workspaces._safe_root(p)
    development_pc.host_path(str(safe_path), directory=True)
    resolved = str(safe_path)

    with settings._guard():
        paths = settings.load().get("coding_roots", [])
        if os.path.normcase(resolved) in {os.path.normcase(item) for item in paths}:
            return {"registered": True, "already_registered": True, "path": resolved, "repositories": jobs.roots()}
        if len(paths) >= 8:
            raise ValueError("登録できるフォルダは8件までです。")
        settings.update({"coding_roots": [*paths, resolved]})
    return {"registered": True, "already_registered": False, "path": resolved, "repositories": jobs.roots()}


@tool(name="propose_development_job",
      description="開発・コード修正・リポジトリ調査・PCファイル作業の依頼を具体的な開発プロンプトに整え、利用者の開始確認待ちとして保存する。実行は始まらない。先に list_coding_repositories で対象を確認する。全PCが意図された場合は repository を空文字にする。軽量な読み取り調査だけ lightweight を true にする。",
      parameters={"type": "object", "properties": {
          "repository": {"type": "string", "maxLength": 1000},
          "goal": {"type": "string", "minLength": 1, "maxLength": 8000},
          "model_key": {"type": "string", "enum": ["auto", *development_models.MODELS]},
          "effort": {"type": "string", "enum": list(development_models.EFFORTS)},
          "lightweight": {"type": "boolean"}},
          "required": ["repository", "goal"], "additionalProperties": False},
      risk="low_risk_write")
def propose_development_job(repository: str, goal: str, model_key="auto", effort="medium", lightweight=False):
    from .. import delegations
    request_id, thread_id = request_context.current_ids()
    if not request_context.current_is_admin() or request_context.local_only() or delegations.is_work_thread(thread_id):
        raise ValueError("管理者の通常会話で開発ジョブを提案できます。")
    if not request_id or not thread_id:
        raise ValueError("request_id_required")
    job = jobs.create_development("chat:" + request_id, repository, goal, model_key, effort, lightweight,
                                  thread_id=thread_id, turn_id=request_id)
    return {"job_id": job["id"], "status": job["status"], "selection": job["selection"]}


@tool(name="delegate_coding_task", description="明示された開発依頼をCodex CLIかAntigravity CLIの別タスクへ渡す。確認画面で対象repository・目的・providerを確認する。元フォルダは変更せず開始時HEADのコピーで実装し、進捗は開発タスク画面で確認する。Push/PR/merge/任意Shellはしない。",
      parameters={"type": "object", "properties": {"repository": {"type": "string"}, "goal": {"type": "string"},
          "provider": {"type": "string", "enum": ["codex", "antigravity_cli", "claude_code"]}, "base_commit": {"type": "string"}, "task_id": {"type": "integer"}, "project_id": {"type": "string"}},
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
