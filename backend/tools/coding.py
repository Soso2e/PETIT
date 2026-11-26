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
      description="開発・コード修正・リポジトリ調査・PCファイル作業の依頼を開発ジョブとして登録する（Webでは開始確認待ち、Discordでは即座にバックグラウンド実行キューへ入り会話はブロックしない）。goal には利用者の依頼を原文のまま入れ、会話の文脈がないと分からない対象や前提だけを補う。利用者が言っていない制約・手順・完了条件は足さない（進め方はCLIが決める）。repository には登録名か登録済みの絶対パスを指定する。対象の登録名が「現在状況」の開発対象に出ていればそのまま使い、出ていない・どれか分からない場合だけ先に list_coding_repositories で確認する。全PCが意図された場合は repository を空文字にする。軽量な読み取り調査だけ lightweight を true にする。既存の開発スレッドの続き（同じ作業場所・ブランチ・CLIセッションを引き継ぐ場合）は dev_thread_id にその開発スレッドIDを指定する。新規で始める場合は dev_thread_id を省略する。",
      parameters={"type": "object", "properties": {
          "repository": {"type": "string", "maxLength": 1000},
          "goal": {"type": "string", "minLength": 1, "maxLength": 8000},
          "dev_thread_id": {"type": "string", "maxLength": 200, "description": "既存の開発スレッドを引き継ぐ場合の開発スレッドID。新規なら省略する。"},
          "model_key": {"type": "string", "enum": ["auto", *development_models.MODELS]},
          "effort": {"type": "string", "enum": list(development_models.EFFORTS)},
          "lightweight": {"type": "boolean"}},
          "required": ["repository", "goal"], "additionalProperties": False},
      risk="low_risk_write")
def propose_development_job(repository: str, goal: str, dev_thread_id: str | None = None,
                            model_key="auto", effort="medium", lightweight=False):
    from .. import delegations, development_threads
    request_id, thread_id = request_context.current_ids()
    if not request_context.current_is_admin() or request_context.local_only() or delegations.is_work_thread(thread_id):
        raise ValueError("管理者の通常会話で開発ジョブを提案できます。")
    if not request_id or not thread_id:
        raise ValueError("request_id_required")
    is_discord = request_context.current_source() == "discord"
    clean_dev_thread = str(dev_thread_id or "").strip()
    if clean_dev_thread:
        development_threads.verify(clean_dev_thread, repository)
        target_thread_id = clean_dev_thread
    elif is_discord:
        root = jobs.require_repository(repository) if repository else None
        target_thread_id = development_threads.create(
            repository=str(root) if root else "",
            title=goal.strip()[:120],
        )["thread_id"]
    else:
        target_thread_id = thread_id
    discord_target = None
    if is_discord and str(thread_id).startswith("discord:"):
        discord_target = {
            "channel_id": str(thread_id).removeprefix("discord:"),
            "guild_id": request_context.current_discord_guild_id(),
            "author_id": request_context.current_discord_author_id() or "",
            "conversation_thread_id": str(thread_id),
        }
    job = jobs.create_development("chat:" + request_id, repository, goal, model_key, effort, lightweight,
                                  direct=is_discord, thread_id=target_thread_id, turn_id=request_id,
                                  discord_target=discord_target)
    return {
        "job_id": job["id"],
        "dev_thread_id": target_thread_id,
        "repository": job["repository"],
        "status": job["status"],
        "selection": job["selection"],
        "direct": is_discord,
        "queued_async": is_discord,
    }


@tool(name="delegate_coding_task", description="明示された開発依頼をCodex CLIかAntigravity CLIの別タスクへ渡す。確認画面で対象repository・目的・providerを確認する。元フォルダは変更せず開始時HEADのコピーで実装し、進捗は開発タスク画面で確認する。Push/PR/merge/任意Shellはしない。",
      parameters={"type": "object", "properties": {"repository": {"type": "string"}, "goal": {"type": "string"},
          "provider": {"type": "string", "enum": ["codex", "antigravity_cli", "claude_code"]}, "base_commit": {"type": "string"}, "task_id": {"type": "integer"}, "project_id": {"type": "string"}},
          "required": ["repository", "goal", "provider", "base_commit"], "additionalProperties": False}, requires_confirmation=True)
def delegate_coding_task(repository: str, goal: str, provider: str, base_commit: str, task_id: int | None = None, project_id: str | None = None):
    if request_context.local_only():
        raise ValueError("ローカル専用Threadから外部CLIへ開発依頼を送信しません。")
    request_id, thread_id = request_context.current_ids()
    if not request_id:raise ValueError("request_id_required")
    return jobs.create("coding:" + request_id, repository, goal, provider, approved=True,
                       task_id=task_id, project_id=project_id, base_commit=base_commit,
                       thread_id=thread_id, turn_id=request_id)


@tool(name="get_coding_task_status", description="開発CLIのジョブIDまたは開発スレッドID（dev_thread_id）から、状態・変更・静的チェックと結果を取得する。",
      parameters={"type": "object", "properties": {
          "job_id": {"type": "string"},
          "dev_thread_id": {"type": "string"},
      }, "additionalProperties": False}, risk="safe_read")
def get_coding_task_status(job_id: str | None = None, dev_thread_id: str | None = None):
    if job_id:
        return jobs.get(job_id)
    if dev_thread_id:
        from .. import development_threads
        detail = development_threads.detail(dev_thread_id)
        latest = detail["jobs"][0] if detail.get("jobs") else None
        return {
            "dev_thread_id": detail["thread_id"],
            "title": detail.get("title", ""),
            "repository": detail.get("repository", ""),
            "triage_status": detail.get("triage_status", "active"),
            "latest_job": jobs.get(latest["id"]) if latest else None,
            "job_count": len(detail.get("jobs") or []),
        }
    raise ValueError("job_id または dev_thread_id のどちらかを指定してください。")


@tool(name="list_development_threads", description="最近の開発スレッド一覧（dev_thread_id、対象リポジトリ、最新ジョブの状態と要約）を取得する。続きを依頼したいスレッドを探すときに使う。",
      parameters={"type": "object", "properties": {
          "repository": {"type": "string", "maxLength": 1000},
          "limit": {"type": "integer", "minimum": 1, "maximum": 30},
      }, "additionalProperties": False}, risk="safe_read")
def list_development_threads(repository: str | None = None, limit: int = 10):
    from .. import development_threads
    rows = development_threads.list_threads(repository=repository or None, limit=limit)
    items = []
    for row in rows[: max(1, min(int(limit), 30))]:
        latest = row.get("latest_job") or {}
        items.append({
            "dev_thread_id": row["thread_id"],
            "title": row.get("title", ""),
            "repository": row.get("repository", ""),
            "triage_status": row.get("triage_status", "active"),
            "latest_job": {
                "job_id": latest.get("id"),
                "status": latest.get("status"),
                "provider": latest.get("provider"),
                "goal": latest.get("goal"),
                "summary": latest.get("summary"),
                "error": latest.get("error"),
                "updated_at": latest.get("updated_at"),
            } if latest else None,
        })
    return {"threads": items}


@tool(name="cancel_coding_task", description="実行中または待機中の開発タスクへ取消要求を出す。実行済み変更と専用コピーは保持する。",
      parameters={"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"], "additionalProperties": False}, requires_confirmation=True)
def cancel_coding_task(job_id: str):return jobs.cancel(job_id)
