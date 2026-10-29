"""Authenticated setup/admin API. No credential values in responses or errors."""
from __future__ import annotations

import hmac
import ipaddress
import os
import threading
import time
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, ConfigDict

from . import setup_store as settings, service_sync, google_services, brain_priority

router = APIRouter(prefix="/api/setup", tags=["setup"])
_attempts: dict[str, list[float]] = {}
_bootstrap_lock = threading.Lock()


def _admin(request: Request):
    if not settings.valid_session(request.cookies.get("petit_admin", "")):
        raise HTTPException(401, "管理者ログインが必要です。")


def _same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "別のサイトからの操作を拒否しました。")
    if not origin and request.headers.get("x-petit-request") != "1":
        raise HTTPException(403, "操作元を確認できません。設定画面から操作してください。")


def install(app):
    from fastapi.exceptions import RequestValidationError
    from fastapi.exception_handlers import request_validation_exception_handler

    @app.exception_handler(RequestValidationError)
    async def redact_credential_errors(request, exc):
        if request.url.path.startswith("/api/setup/"):
            return JSONResponse({"detail": "入力形式または文字数を確認してください。"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        path = request.url.path
        try:
            initialized = settings.initialized()
            if path in {"/", "/static/universe.html", "/static/legacy.html", "/static/desktop/index.html"} and request.method == "GET":
                if not initialized or not settings.load()["completed"] or not settings.valid_session(request.cookies.get("petit_admin", "")):
                    from urllib.parse import urlencode
                    return RedirectResponse("/static/setup.html?" + urlencode({"next": path if path != "/" else "/static/universe.html", "resume": "1"}))
            public = path in {"/api/setup/session", "/api/setup/login", "/api/setup/bootstrap", "/api/health", "/api/setup/google/callback"}
            if path.startswith("/api/") and initialized and not public:
                _admin(request)
            if path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"} and (initialized or path.startswith("/api/setup/")):
                _same_origin(request)
            response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if path == "/api/setup/google/callback":
            request.scope["query_string"] = b""
        if path.startswith("/api/setup"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response


class Password(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    bootstrap_token: str = Field(default="", max_length=256)


def _session_response(request, password):
    token = settings.authenticate(password)
    if not token:
        raise HTTPException(401, "パスワードを確認してください。")
    result = JSONResponse({"authenticated": True})
    result.set_cookie("petit_admin", token, httponly=True, secure=request.url.scheme == "https", samesite="lax", max_age=43200, path="/")
    return result


@router.get("/session")
def session(request: Request):
    return {"initialized": settings.initialized(), "completed": settings.load()["completed"],
            "authenticated": settings.valid_session(request.cookies.get("petit_admin", ""))}


@router.post("/bootstrap")
def bootstrap(payload: Password, request: Request):
    with _bootstrap_lock:
        if settings.initialized():
            raise HTTPException(409, "セットアップ済みです。ログインしてください。")
        expected = os.getenv("PETIT_BOOTSTRAP_TOKEN", "")
        host = request.client.host if request.client else ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        # A cloud administrator must provision a one-time host secret. Never let the first LAN visitor claim Core.
        if expected:
            if not hmac.compare_digest(expected, payload.bootstrap_token):
                raise HTTPException(403, "初期設定トークンを確認してください。")
        elif not loopback or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(403, "初期設定はサーバーのlocalhostから行うか、PETIT_BOOTSTRAP_TOKENを設定してください。")
        try:
            settings.set_password(payload.password)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return _session_response(request, payload.password)


@router.post("/login")
def login(payload: Password, request: Request):
    key = request.client.host if request.client else "unknown"
    with _bootstrap_lock:
        now = time.time()
        _attempts[key] = [x for x in _attempts.get(key, []) if now-x < 300]
        if len(_attempts[key]) >= 10:
            raise HTTPException(429, "ログインの試行が多すぎます。5分後に再試行してください。")
        _attempts[key].append(now)
    return _session_response(request, payload.password)


@router.post("/logout", dependencies=[Depends(_admin)])
def logout(request: Request):
    settings.logout(request.cookies.get("petit_admin", ""))
    result = JSONResponse({"authenticated": False})
    result.delete_cookie("petit_admin", path="/")
    return result


@router.get("/config", dependencies=[Depends(_admin)])
def get_config():
    from . import codex_brain
    from .antigravity_cli import status
    return {"settings": settings.public(), "brain": brain_priority.public_status(), "sync": service_sync.status(),
            "antigravity_cli": status(settings.load()), "codex_cli": codex_brain.status()}


@router.get("/antigravity-acp", dependencies=[Depends(_admin)])
def antigravity_acp_status():
    from . import antigravity_acp
    data = settings.load()
    return {**antigravity_acp.status(data.get("antigravity_acp_install_path") or None),
            "install_root": data.get("antigravity_acp_install_path") or str(antigravity_acp.DEFAULT_ROOT),
            "auth_last_success_utc": data.get("antigravity_acp_auth_last_success_utc"),
            "last_error": data.get("antigravity_acp_last_error")}


class AntigravityACPInstall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: str | None = Field(default=None, max_length=1000)


@router.post("/antigravity-acp/install", dependencies=[Depends(_admin)])
def install_antigravity_acp(payload: AntigravityACPInstall | None = None):
    from pathlib import Path
    from . import antigravity_acp
    from scripts.install_antigravity_acp import install
    destination = payload.destination if payload else None
    try:
        root = Path(destination).expanduser() if destination else None
        result = install(root)
        settings.update({"antigravity_acp_install_path": str(root.resolve()) if root else "",
                         "antigravity_acp_last_error": None})
        return {**result, **antigravity_acp.status(root)}
    except Exception as exc:
        settings.update({"antigravity_acp_last_error": "ACP Agent installation failed (" + type(exc).__name__ + ")."})
        return JSONResponse({"installed": False, "error": "ACP Agent installation failed.",
                             "error_type": type(exc).__name__}, status_code=400)


@router.post("/antigravity-acp/handshake", dependencies=[Depends(_admin)])
async def antigravity_acp_handshake():
    from . import antigravity_acp
    try:
        result = await antigravity_acp.inspect_agent()
        settings.update({"antigravity_acp_last_error": None})
        return result
    except Exception as exc:
        settings.update({"antigravity_acp_last_error": "ACP initialization failed (" + type(exc).__name__ + ")."})
        return JSONResponse({"ok": False, "error": "ACP initialization failed.",
                             "error_type": type(exc).__name__}, status_code=400)


@router.post("/antigravity-acp/authenticate", dependencies=[Depends(_admin)])
async def antigravity_acp_authenticate():
    from . import antigravity_acp
    try:
        result = await antigravity_acp.authenticate_personal()
    except Exception as exc:
        settings.update({"antigravity_acp_last_error": "Google OAuth via the official ACP agent failed (" + type(exc).__name__ + ")."})
        return JSONResponse({"ok": False, "error": "Google OAuth via the official ACP agent did not complete.",
                             "error_type": type(exc).__name__}, status_code=400)
    if result.get("ok"):
        settings.update({"antigravity_acp_auth_last_success_utc": datetime.now(timezone.utc).isoformat(),
                         "antigravity_acp_last_error": None})
    return {**result, "auth_last_success_utc": settings.load().get("antigravity_acp_auth_last_success_utc")}


@router.get("/antigravity-cli", dependencies=[Depends(_admin)])
def antigravity_cli_status():
    # File existence only. No login, prompt, process, credential inspection or network.
    from .antigravity_cli import status
    return status(settings.load())


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: list[Literal["codex", "antigravity", "deepseek", "antigravity_cli"]] | None = None
    paid_allowed: list[Literal["antigravity", "deepseek"]] | None = None
    brain_enabled: bool | None = None
    brain_transport: Literal["mixed", "cli_only"] | None = None
    calendar: Literal["local", "google_calendar", "timetree"] | None = None
    google_calendar_id: str | None = Field(default=None, max_length=300)
    google_redirect_uri: str | None = Field(default=None, max_length=1000)
    antigravity_auth: Literal["local", "gemini"] | None = None
    antigravity_model: str | None = Field(default=None, max_length=200)
    antigravity_url: str | None = Field(default=None, max_length=500)
    deepseek_model: str | None = Field(default=None, max_length=200)
    codex_model: str | None = Field(default=None, max_length=200)
    antigravity_cli_model: str | None = Field(default=None, max_length=200)
    sync_notifications: bool | None = None


@router.put("/config", dependencies=[Depends(_admin)])
def put_config(payload: SettingsUpdate):
    values = payload.model_dump(exclude_none=True)
    if "priority" in values and (len(values["priority"]) != len(set(values["priority"]))
            or not {"codex", "antigravity", "deepseek"} <= set(values["priority"])):
        raise HTTPException(400, "既存3種類と、任意のAntigravity CLIを重複なく指定してください。")
    if values.get("google_redirect_uri"):
        uri = urlsplit(values["google_redirect_uri"])
        if (uri.scheme != "https" and not (uri.scheme == "http" and uri.hostname in {"localhost", "127.0.0.1", "::1"})) or uri.username or uri.query or uri.fragment or uri.path != "/api/setup/google/callback":
            raise HTTPException(400, "Redirect URIはHTTPS（localhostのみHTTP可）の/api/setup/google/callbackを指定してください。")
    if values.get("antigravity_url"):
        from .model_routing import sdk_local_url
        if not sdk_local_url(values["antigravity_url"]):
            raise HTTPException(400, "SDKローカル接続にはloopback URLを指定してください。")
    data = settings.load()
    if values.get("calendar", "local") != "local" and values["calendar"] not in data["connected"]:
        raise HTTPException(400, "接続済みのカレンダーを選択してください。")
    if "google_calendar_id" in values and "google_calendar" in data["connected"]:
        if values["google_calendar_id"] not in {x["id"] for x in google_services.calendars()} and values["google_calendar_id"] != "primary":
            raise HTTPException(400, "アクセス可能なカレンダーを選択してください。")
    if values.get("brain_enabled", data["brain_enabled"]) and ("brain_enabled" in values or "brain_transport" in values):
        candidate = {**data, **values}
        if not any(brain_priority.permitted(x, candidate) and brain_priority.target(x, candidate)["configured"] for x in candidate["priority"]):
            raise HTTPException(400, "AIを接続し、必要な費用許可を設定してください。")
    settings.update(values)
    if "sync_notifications" in values:
        from . import notifications
        notifications.update_preferences({"sync_failure": values["sync_notifications"]})
    return get_config()


@router.post("/codex/diagnose", dependencies=[Depends(_admin)])
def codex_diagnose():
    """Explicit local CLI/auth check; does not start inference or log in."""
    from . import codex_brain
    return codex_brain.diagnose()


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, str | None]


SECRET_FIELDS = {"deepseek_key", "antigravity_key", "notion_key", "google_client_id", "google_client_secret",
                 "timetree_email", "timetree_password", "timetree_calendar"}


@router.put("/credentials", dependencies=[Depends(_admin)])
def credentials(payload: Credentials):
    if not payload.values or set(payload.values) - SECRET_FIELDS or any(v is not None and len(v) > 4096 for v in payload.values.values()):
        raise HTTPException(400, "変更可能な認証情報を指定してください。")
    # Empty means deliberate deletion/disable, not fallback to legacy .env.
    values = {k: v or "" for k, v in payload.values.items()}
    if {"google_client_id", "google_client_secret"} & set(values):
        data = settings.load()
        settings.update({"connected": [x for x in data["connected"] if x not in google_services.SCOPES],
                         **({"calendar": "local"} if data["calendar"] == "google_calendar" else {})},
                        {**values, "google_tokens": None, "oauth_pending": None})
    else:
        settings.update({}, values)
    return {"settings": settings.public()}


@router.post("/google/{service}/authorize", dependencies=[Depends(_admin)])
def google_authorize(service: str, request: Request):
    try:
        return google_services.authorize(service, request.cookies.get("petit_admin", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/google/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    try:
        if error or not code or len(code) > 4096 or len(state) > 256:
            raise ValueError("authorization_declined")
        google_services.callback(state, code, request.cookies.get("petit_admin", ""))
        text = "Googleの接続を保存しました。設定画面へ戻って接続テストを実行してください。"
    except Exception:
        text = "Google認証を完了できませんでした。設定画面から再接続してください。"
    return HTMLResponse('<!doctype html><html lang="ja"><meta charset="utf-8"><title>Google接続</title><p>' + text + '</p><a href="/static/setup.html">設定へ戻る</a></html>', headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/google/calendars", dependencies=[Depends(_admin)])
def calendars():
    return {"items": google_services.calendars()}


@router.get("/notion/search", dependencies=[Depends(_admin)])
def notion_search(query: str = "", cursor: str = ""):
    from . import notion_client
    data = notion_client._post("/search", {"query": query[:200], "page_size": 50, **({"start_cursor": cursor} if cursor else {})})
    result = []
    for item in data.get("results", []):
        title = item.get("title") or next((v.get("title") for v in item.get("properties", {}).values() if v.get("type") == "title"), [])
        result.append({"id": item["id"], "type": item["object"], "title": "".join(x.get("plain_text", x.get("text", {}).get("content", "")) for x in title),
                       "url": item.get("url", "")})
    return {"items": result, "next_cursor": data.get("next_cursor")}


class NotionSelection(BaseModel):
    tasks_db: str = Field(default="", max_length=100)
    projects_db: str = Field(default="", max_length=100)
    pages: list[str] = Field(default_factory=list, max_length=50)


@router.put("/notion/selection", dependencies=[Depends(_admin)])
def notion_selection(payload: NotionSelection):
    import re
    from . import notion_client
    for ident in [payload.tasks_db, payload.projects_db, *payload.pages]:
        if ident and not re.fullmatch(r"[a-fA-F0-9-]{32,36}", ident):
            raise HTTPException(400, "Notion IDを確認してください。")
    for ident in (payload.tasks_db, payload.projects_db):
        if ident:
            notion_client._get("/databases/" + ident)
    for ident in payload.pages:
        notion_client._get("/pages/" + ident)
    settings.update({"notion_tasks_db": payload.tasks_db, "notion_projects_db": payload.projects_db, "notion_pages": payload.pages})
    return {"settings": settings.public()}


@router.post("/services/{service}/connect", dependencies=[Depends(_admin)])
def connect(service: str):
    if service == "antigravity_cli":
        if not brain_priority.target(service)["configured"]:
            raise HTTPException(400, "公式agy CLIをサーバーへ導入してください。")
        data = settings.load()
        settings.update({"antigravity_cli_enabled": True,
                         "connected": sorted(set(data["connected"]) | {service}),
                         "priority": [service] + [x for x in data["priority"] if x != service]})
        return {"connected": True, "tested": False, "authentication": "unknown", "officially_supported": False}
    data = settings.load()
    if service == "codex":
        from . import codex_brain
        return codex_brain.login()
    if service == "notion":
        from . import notion_client
        notion_client._get("/users/me")
    elif service == "timetree":
        from .calendar_sources import timetree
        if not timetree.configured():
            raise HTTPException(400, "TimeTreeのメール・パスワード・カレンダーコードを設定してください。")
    elif service in {"deepseek", "antigravity"}:
        if not brain_priority.target(service)["configured"]:
            raise HTTPException(400, "APIキー・モデル・SDK依存を設定してください。")
    else:
        raise HTTPException(400, "利用できないサービスです。")
    settings.update({"connected": sorted(set(data["connected"]) | {service})})
    return {"connected": True, "tested": service == "notion"}


@router.post("/services/codex/confirm", dependencies=[Depends(_admin)])
def codex_confirm():
    from . import codex_brain
    result = codex_brain.account()
    if result["authenticated"]:
        settings.update({"connected": sorted(set(settings.load()["connected"]) | {"codex"})})
    return result


@router.post("/services/{service}/disconnect", dependencies=[Depends(_admin)])
def disconnect(service: str):
    data = settings.load()
    remote_confirmed = True
    try:
        if service in google_services.SCOPES:
            google_services.disconnect(service)
        elif service == "codex":
            from . import codex_brain
            codex_brain.logout()
    except Exception:
        remote_confirmed = False
    credentials = {"deepseek": {"deepseek_key": ""}, "antigravity": {"antigravity_key": ""},
                   "notion": {"notion_key": ""}, "timetree": {"timetree_email": "", "timetree_password": "", "timetree_calendar": ""}}
    settings.update({"connected": [x for x in settings.load()["connected"] if x != service],
                     **({"antigravity_cli_enabled": False} if service == "antigravity_cli" else {}),
                     **({"calendar": "local"} if data["calendar"] == service else {})}, credentials.get(service))
    return {"disconnected": True, "remote_revocation_confirmed": remote_confirmed}


@router.post("/services/{service}/test", dependencies=[Depends(_admin)])
def test_connection(service: str):
    try:
        if service in {"google_calendar", "gmail"}:
            result = google_services.calendars() if service == "google_calendar" else google_services.get("gmail", "profile")
            return {"ok": True, "read_only": True}
        if service == "notion":
            from . import notion_client
            notion_client._get("/users/me")
            return {"ok": True}
        if service == "timetree":
            from .calendar_sources import timetree
            from .calendar_sync import parse_ics
            events = parse_ics(timetree.fetch_ics())
            return {"ok": True, "read_only": True, "count": len(events)}
        if service in {"codex", "antigravity", "deepseek", "antigravity_cli"}:
            from . import brain, conversation_store as store, request_context
            data = settings.load()
            if not brain_priority.permitted(service, data):
                raise ValueError("接続と必要なAPI費用許可を設定してください。")
            request_id, thread_id = "setup-test-" + uuid4().hex, "setup-test-" + uuid4().hex
            store.create_thread(thread_id, title="AI接続テスト")
            store.accept(thread_id, request_id, {"message": "接続テストです。Toolを呼ばず、接続しました、とだけ返答してください。"})
            store.claim(request_id)
            token = brain_priority._active.set({**brain_priority.target(service), "_connection_test": True})
            try:
                with request_context.bind(request_id=request_id, session_id=thread_id):
                    result = brain._run(request_id)
                return {"ok": result["status"] == "completed", "status": result["status"], "provider": service}
            except Exception as exc:
                failure = _test_failure(exc)
                store.finish(request_id, {"reply": "", "error": failure["error"], "reason": failure["reason"]}, status="failed")
                raise
            finally:
                brain_priority._active.reset(token)
        raise ValueError("unknown_service")
    except Exception as exc:
        # Provider response bodies and secret URLs never cross this boundary.
        return JSONResponse(_test_failure(exc), status_code=400)


@router.post("/services/{service}/models", dependencies=[Depends(_admin)])
def models(service: str):
    from . import cli_models
    try:return cli_models.list_models(service)
    except Exception as exc:
        return JSONResponse({"error": "モデル一覧を取得できません。公式CLIの導入・認証・接続を確認してください。",
                             "error_type": type(exc).__name__}, status_code=400)


def _test_failure(exc):
    """Only fixed diagnostic codes/messages cross the API, never provider text."""
    messages = {
        "authentication_required": "公式CLIへのログインが必要です。サーバーPCのCLIで認証してください。",
        "authentication_expired": "CLIの認証を確認できません。公式の認証をやり直してください。",
        "usage_limit": "CLIが利用枠の上限を報告しました。公式CLIで利用状況を確認してください。",
        "timeout": "CLIの応答が90秒の制限を超えました。公式CLIの応答速度・モデル・混雑を確認してください。",
        "invalid_cli_response": "CLIは応答しましたが、PETIT用の返答JSON（content・tool_calls）を検証できませんでした。",
        "invalid_cli_protocol": "CLIが返したイベント形式をPETITで検証できませんでした。",
        "direct_tool_detected": "CLIの直接Toolを検出したため、接続テストを停止しました。",
        "cli_start_failed": "CLIを起動できません。実行ユーザー・配置・実行権限を確認してください。",
        "not_configured": "CLIが見つかりません。サーバー上の導入状態を確認してください。",
        "permission_denied": "CLIの実行または保存場所へのアクセスが拒否されました。サーバーの実行ユーザーと権限を確認してください。",
        "output_limit": "CLIの出力が上限を超えました。",
        "provider_changed": "テスト中にAI設定が変更されました。設定を保存してから再試行してください。",
        "cli_error": "公式CLIがエラーを返しました。公式CLI本体で認証・モデル・利用枠を確認してください。",
    }
    reason = getattr(exc, "reason", None)
    if isinstance(exc, PermissionError):reason = "permission_denied"
    if reason not in messages:reason = "unknown"
    return {"ok": False, "reason": reason, "error": messages.get(reason,
        "接続テストに失敗しました。認証・権限・モデル・依存を確認してください。"), "error_type": type(exc).__name__}


@router.post("/sync/{service}", dependencies=[Depends(_admin)])
def retry(service: str):
    if service == "notion":
        from . import notion_task_sync
        result = notion_task_sync.sync_now(mode="full")
        service_sync.observe_notion()
        return {"ok": result["ok"], "synced_count": result.get("synced_count", 0)}
    return service_sync.sync(service, manual=True)


@router.post("/complete", dependencies=[Depends(_admin)])
def complete():
    settings.update({"completed": True})
    return {"completed": True}
