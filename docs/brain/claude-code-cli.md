# Claude Code CLI Executor

> Status: **現行（v0.44.0 開発版）** / 関連: Concept.md §4・§10、Refs #345
>
> 実装フローの正本は [../runtime-flows.md](../runtime-flows.md) の「Claude Code CLI Executor」。

## 目的

Concept §4 のExecutor順位（Antigravity CLI ＞ Codex ＞ **Claude Code** ＞ DeepSeek）の3番目として、公式 `claude` CLI を会話BrainとCoding Jobで使えるようにする。

## 仕組み

- `backend/claude_code_brain.py` が、会話の各roundで公式 `claude` を1回起動する。
  - `claude -p --output-format json --json-schema <content/tool_calls> --tools "" --strict-mcp-config --setting-sources "" --disable-slash-commands --no-session-persistence --system-prompt <固定文>`
  - 利用者の本文と文脈は stdin だけで渡す（argv に入れない）。作業ディレクトリは毎回の一時フォルダ。
  - 子プロセスの環境変数は PATH / HOME などの最小限と `CLAUDE_CONFIG_DIR` だけ。`ANTHROPIC_API_KEY` や PETIT の秘密値は渡さない。**公式CLIのログインだけ**で動く。
- CLI は `{"content", "tool_calls"}` を返すだけ。Tool名は PETIT の公開catalog（＋`discover_tools`）に限り、引数検証・risk・承認・receipt は既存の native Loop（`brain._run`）が行う。
- `is_error`・JSON不正・`permission_denials`・catalog外のTool はすべて `CLIError` になり、Toolは実行しない。理由は固定コード（`authentication_required` / `usage_limit` / `invalid_cli_response` など）だけを保存し、CLIの本文は保存しない。
- Tool実行前の失敗は、既存のFallback規則で次の候補へ切り替わる。
- Coding Job（`provider=claude_code`）も同じ `completion` を使い、Job限定catalog（list / read / SHA照合write / 静的check）だけで作業する。実テスト・Push・PRは引き続き未対応。

## 設定

- Settings の「Claude Code CLI」カードで **明示的に接続**したときだけ使う（`claude_code_enabled` と `connected`）。環境変数からは有効化しない。
- 接続すると、保存済みの優先順位を並べ替えずに、方針順（Codexの次）の位置へ挿入する。
- モデルは空欄でCLI既定。候補はCLIの別名（sonnet / opus / haiku）を表示するだけで、利用権の証明ではない。
- Windows では npm の `claude.cmd` は使わず、ネイティブ版 `claude.exe`（`~/.local/bin`）だけを検出する（バッチ経由の引数解釈を避けるため）。

## 確認済み / 未確認

| 項目 | 状態 |
| --- | --- |
| 合成出力での契約テスト（コマンド・秘密非継承・検証・承認・Fallback理由・Coding Job） | 確認済み（`tests/test_claude_code_brain.py`） |
| 実CLI（Linux開発コンテナ、claude 2.1.x）での雑談・Read Tool・discover→承認→ローカル予定保存→receipt | 確認済み（合成DB） |
| 実Chromiumでの設定画面（診断・モデル候補保存・接続順・切断） | 確認済み（`scripts/test-setup-ui.cjs` の該当部分。agy未導入の後半は未実施） |
| Windows / macOS の実端末、本人アカウントでのログイン・利用枠 | **未確認** |
| 自作アプリから呼び出す使い方の契約上の扱い | **未確認**（Concept §10） |
| 利用枠の残量 | 取得できないため `unknown`。`total_cost_usd` は目安として記録するだけで請求額ではない |
