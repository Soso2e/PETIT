"""Official CLI catalogs, never treated as inference/entitlement proof."""
import re
import tempfile
from pathlib import Path
from . import codex_brain, antigravity_cli, antigravity_cli_brain


def parse_agy(text):
    models = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([a-z0-9][a-z0-9._-]{0,199})\t([^\r\n]{1,300})", line.strip())
        if match:models[match[1]] = {"id": match[1], "label": match[2]}
    if not models:raise ValueError("公式CLIからモデル一覧を取得できませんでした。")
    return list(models.values())


def list_models(provider):
    if provider == "antigravity_cli":
        binary = antigravity_cli.executable()
        if not binary:raise ValueError("公式Antigravity CLIが見つかりません。")
        with tempfile.TemporaryDirectory(prefix="petit-models-", ignore_cleanup_errors=True) as folder:
            code, out, err = antigravity_cli_brain.invoke([binary, "models"], Path(folder), "", lambda: None, timeout=30)
        if code:raise ValueError("公式CLIのモデル一覧取得に失敗しました。CLIの認証・接続を確認してください。")
        models = parse_agy(out + "\n" + err)
    elif provider == "codex":
        client = codex_brain.RPC()
        models, cursor, seen = [], None, set()
        try:
            for _ in range(20):
                params = {"limit": 100, "includeHidden": False}
                if cursor:params["cursor"] = cursor
                page = client.request("model/list", params)
                for item in page.get("data", []):
                    ident = item.get("model") or item.get("id")
                    if isinstance(ident, str) and ident and ident not in seen:
                        seen.add(ident);models.append({"id": ident, "label": item.get("displayName") or ident})
                next_cursor = page.get("nextCursor")
                if not next_cursor:break
                if next_cursor == cursor:raise ValueError("モデル一覧のページを確認できません。")
                cursor = next_cursor
            else:raise ValueError("モデル一覧の上限に達しました。")
            if not models:raise ValueError("モデル一覧が空です。公式CLIの状態を確認してください。")
        finally:client.close()
    else:raise ValueError("一覧取得はCodex CLIとAntigravity CLIに対応しています。")
    return {"models": models, "provider": provider, "inference_verified": False}
