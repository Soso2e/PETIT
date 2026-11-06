# Develop: Codex / Claude Code / Antigravity 統合方針とACP初期診断

対象: PETIT v0.42.2 / #357 / #378。現在の実装は **ACP v1 initialize の明示診断だけ**。
これを「3 AIのセッション統合・同時実行が完成した」と解釈しない。

## 現状と接続先

| Provider | 現在の開発Job経路 | ACP診断 | 注記 |
| --- | --- | --- | --- |
| Codex | 既存Codex app-server / Coding Jobs | `codex-acp` | ACP接続は別経路。認証を実行しない |
| Antigravity | 既存公式 `agy` CLI / Coding Jobs | `agy acp` | 公式ACP。CLIのログイン・利用枠は独立 |
| Claude Code | PR #386（未統合）で公式CLI Executor追加中 | ACP起動なし、導入有無だけ | サブスク資格情報をAgent SDK等へ中継しない |

公式資料:
- ACP v1: https://agentclientprotocol.com/protocol/v1/initialization
- Codex ACP: https://github.com/agentclientprotocol/codex-acp
- Antigravity公式 ACP: https://antigravity.google/docs/cli/acp/
- Claude Code規約: https://code.claude.com/docs/en/legal-and-compliance

## 初期化診断

Windows/PCで本人が明示実行。追加API課金なし、既存のCoding JobやChat Brainは変更しない。

```powershell
npm install -g @agentclientprotocol/codex-acp
agy acp --help
python scripts/develop_acp_probe.py --provider all
python scripts/develop_acp_probe.py --provider codex
python scripts/develop_acp_probe.py --provider antigravity_cli
python -m unittest tests.test_develop_acp -v
```

Developの管理者画面にも「ACP接続診断」を追加。実行要求はCSRF確認済みの管理者POSTのみ。
Codex / Antigravityへ `initialize` を送信し、ACP v1互換性・Agent名・セッション復元フラグ・認証手段の**識別子のみ**を表示する。
`session/new`、`session/prompt`、`authenticate`、ファイル・ターミナル操作は呼ばない。
環境からPETITのAPIシークレットは除外し、raw stdout/stderrや認証トークンは保持・表示しない。
診断プロセスは終了させる。認証成功・利用枠・課金・コードの変更権限・モデル品質を保証しない。

ClaudeのACP経由利用は契約条件が解決するまで保留する。本人が無改変の公式Claude Code CLIを使うことと、
開発者が第三者UIからサブスク認証を仲介することは別条件。PR #386はレビュー・契約確認後に扱う。

## 続く実装（別PR）

1. **Project → Thread → Coding Job:** #378の既存SQLite Thread/Turnとproject_idの正本を保ち、複数回の依頼・結果を同じPETIT会話に表示。
2. **ACP session runtime:** Providerごとのプロセス/Session/Prompt/Permission/Cancelを扱う。実端末で隔離を確認するまで実コード書き込みを有効にしない。
3. **Handoff:** Git commit、未統合diff、テスト証拠、残課題を明示したartifactを渡す。会話履歴を丸投げせず、未統合diffを適用済みと誤認しない。
4. **Worktreeと実テスト:** リポジトリごとの許可・専用作業領域・テストコマンド・差分レビュー・PR作成。危険操作は本人承認。
5. **Auto選択:** 完了率・レビュー品質・待ち時間・使用枠（公式取得可能な場合のみ）で選択。まず単一AI、複数起動は必要な場合だけ。

**既存コードは維持:** `backend/coding_jobs.py`、`backend/coding_agents.py`、`backend/conversation_store.py`、`backend/project_continuity.py`。
Current UIの1 Job = 1依頼、元checkout非変更、実テスト未実施、Push/PR/merge不可という制約もそのまま。

## 受入境界

- 合成エージェントの単体テストは実CLI認証・実モデル推論の証拠ではない。
- Windows本人PCで Codex ACP と agy ACP の `initialized` を目視確認し、実利用枠は unknown とする。
- 既存PR #386の変更と重複しないようClaude統合は別途。#385のdocs全面移動がマージされると相対パス要調整。
- ACPのinitialize成功でもDevセッション再開・Permission表示・Git差分・Worktreeは未実装。
