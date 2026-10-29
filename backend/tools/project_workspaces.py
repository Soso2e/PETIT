"""Explicit project lookup and confirmation-gated local folder associations."""
from .. import config, db, project_continuity, project_registration, project_workspaces
from .registry import tool


@tool(name="find_projects", description=(
    "名前・確認済み別名からPETIT内部Project IDを探す。完全一致でも候補が複数なら選ばない。"
    "候補とフォルダの紐付けは別で、似た名前だけで対応を推測しない。"),
    parameters={"type": "object", "properties": {"query": {"type": "string"}},
                "required": ["query"], "additionalProperties": False}, risk="safe_read")
def find_projects(query: str) -> dict:
    matches = project_continuity.find_projects_by_alias(query)
    return {"status": "unique" if len(matches) == 1 else "ambiguous" if matches else "not_found",
            "projects": [{"id": p["id"], "name": p["name"], "matched_alias": p["matched_alias"]} for p in matches[:20]]}


@tool(name="list_project_workspaces", description=(
    "登録可能な明示allowlist内フォルダと、project_idに確認済みの対応を一覧する。"
    "フォルダの自動探索・全PC索引は行わない。登録にはlink_project_workspaceの確認が必要。"),
    parameters={"type": "object", "properties": {"project_id": {"type": "string"}},
                "additionalProperties": False}, risk="safe_read")
def list_project_workspaces(project_id: str | None = None) -> dict:
    return project_workspaces.list_workspaces(project_id)


@tool(name="link_project_workspace", description=(
    "既存Project IDへ明示allowlist内の正確なローカルGitルートを登録する。"
    "利用者が選んだProjectとpathを確認してから保存。名前が似ているだけで登録しない。"),
    parameters={"type": "object", "properties": {
        "project_id": {"type": "string"}, "path": {"type": "string"}},
        "required": ["project_id", "path"], "additionalProperties": False}, risk="confirm_write")
def link_project_workspace(project_id: str, path: str) -> dict:
    return project_workspaces.link(project_id, path)


@tool(name="unlink_project_workspace", description="確認済みProjectフォルダの対応だけ解除する。実ファイルは削除しない。",
    parameters={"type": "object", "properties": {
        "project_id": {"type": "string"}, "link_id": {"type": "integer"}},
        "required": ["project_id", "link_id"], "additionalProperties": False}, risk="confirm_write")
def unlink_project_workspace(project_id: str, link_id: int) -> dict:
    return project_workspaces.unlink(project_id, link_id)


@tool(name="register_project", description=(
    "本人が登録を依頼した名称で既存Project ContinuityにProjectを登録する。"
    "同名の確認済みProjectがあれば再利用し、曖昧なら作成しない。利用者確認を経て保存する。"),
    parameters={"type": "object", "properties": {
        "name": {"type": "string"}, "set_active": {"type": "boolean", "default": False}},
        "required": ["name"], "additionalProperties": False}, risk="confirm_write")
def register_project(name: str, set_active: bool = False) -> dict:
    name = project_registration._clean_name(name)
    if len(project_continuity.find_projects_by_alias(name)) > 1:
        raise ValueError("project_name_is_ambiguous")
    owner = config.PETIT_OWNER_ID
    result = project_registration.create_internal_project(user_id=owner, name=name, set_active=set_active,
        idempotency_key=project_registration._idempotency_key("create_project", owner, name))
    return {**result, "already_exists": not result["created"]}
