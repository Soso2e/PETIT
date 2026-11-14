# CLIによるローカル開発ジョブ（#418）

管理者は Develop タブの「フォルダを管理」からサーバーPCの絶対パスを登録する。設定の `coding_roots` と既存の `PETIT_WORKSPACE_CONTEXT_DIRS` を合わせて表示する。環境変数の有効化フラグは Develop の利用条件に含まれない。観測を会話コンテキストへ注入する設定と、Develop の観測は別扱いとする。

## 依頼と実行

- Chat は `list_coding_repositories` で対象を確認し、`propose_development_job` に整えたプロンプト、対象、モデルと Effort を渡す。同じジョブの `proposed` カードが返信内と Develop に表示される。開始操作で `queued` に進む。
- DeepSeekのFront Brainは[委譲スキル](../../backend/skills/compact-cli-handoff/SKILL.md)を読み、目的、必須の制約、完了条件に絞って依頼する。
- Antigravityの開発ジョブはCLI応答1回に120秒を確保する。タイムアウト、一時的な起動・通信エラー、構造化応答の検証失敗は同じステップだけを1回再試行する。再試行は1ジョブに最大2回、実行全体は15分まで。認証・権限・利用枠は原因を表示する。
- Chatの開発カードとDevelopは、管理者向けSSEでCLIの受信・検証・再試行などの進捗文を表示する。保存済みの結果・差分・承認はジョブ詳細から取得する。CLIの内部思考、CLIの生出力、ツール引数は進捗配信の対象外。
- Develop のフォームは管理者の送信で `queued` を作る。以降はどちらも同じ Coding Job Worker が処理する。
- request ID と入力のハッシュで再送を判定し、状態の更新条件で承認と Worker の取得を一度に限る。実行中の Core 再起動は `interrupted` とし、作業コピーを保持する。
- 旧ジョブの記録と API は残す。旧開発ページの URL は Develop タブへ移動する。通常の会話カタログでは、旧 `delegate_coding_task` と worktree 変更 Tool に代わって開発提案を公開する。

## モデルと利用枠

| 選択 | 実行 CLI | モデルと Effort |
| --- | --- | --- |
| Claude Opus 5.5 | Claude Code | `opus` と `--effort` |
| Codex Sol 6.1 | Codex app-server | `gpt-6.1-sol` と `turn/start.effort` |
| Antigravity Argon | Antigravity CLI | `gemini-4-argon-<effort>` |
| Gemini 3.8 Flash | Antigravity CLI | `gemini-3.8-flash-<effort>` |

Effort は low / medium / high、既定は medium。自動選択は軽量調査で利用可能な Flash を優先し、通常の開発では認証を確認できた候補を週次、次いで5時間枠の残量順に比較する。0% の枠を持つ候補は除外し、不明な枠は既知の残量より後に置く。

`GET /api/coding/usage` は公式 CLI で得た結果を60秒キャッシュする。Antigravity の `/usage` は Gemini 共通の5時間枠と、Argon 専用または Gemini 共通の週次枠を使う。Codex は `account/rateLimits/read` を使う。Claude は認証確認に加え、PETIT のジョブ履歴から5時間40リクエスト・7日200リクエストを目安に推定する。Anthropic の実契約枠や他のアプリからの消費は含まない。利用制限エラーから5時間は5時間枠を0%と扱う。

Codex は OS 標準の CLI 認証を参照する。明示的に分離する場合は `PETIT_CODEX_HOME` を使う。Claude Code の設定ではサーバーPCの公式ブラウザ認証を開始でき、状態確認とログアウトを行える。Claude Code のエージェントモードで `--restricted` が見つからない場合は `claude update` を案内する。

## 実行範囲と承認

- Git ルートでは、開始コミットのローカル clone に専用作業ブランチを作り、元 checkout の未コミット差分を含めず、clone の remote を除去する。Core はファイル編集、静的チェック、許可リストのテスト・ビルドランナー、ローカル commit を提供する。差分レビューは開始コミットを基準にし、commit 済みの変更を含む。テスト・ビルドのランナーはホストでリポジトリ内のコードを実行するため、登録・選択するリポジトリは信頼できるものに限る。
- Git 以外の登録フォルダではそのフォルダを、指定なしでは Windows の論理ドライブ全体を対象にする。Everything の Windows IPC または `es.exe` で問い合わせ、利用できない場合は件数・時間を制限してファイル名を走査する。機密性の高い名前や認証領域、PETIT ストレージ、リンク経由のパスは Core で除外する。
- PC の検索・テキスト読み取りと、ジョブ専用の `storage/coding-scratch/` へのコピー・作業は開始確認の範囲に含む。読み取った本文は選択した CLI に渡り得る。
- 元ファイルへの書き込み・移動・削除、元フォルダでのコマンド実行は L2 の操作カードを作る。承認対象は登録済みのパス、引数と書き込み元のハッシュに固定する。元ファイルが変わった場合は適用しない。操作の承認は30分有効で、取消や不明結果からの自動再実行は行わない。コマンドは承認した argv をホストで実行する。
- CLI にはジョブごとの Core カタログを渡す。Git の push、PR、merge はこのカタログの対象外。静的検査、コマンド検証、実アプリの受入、利用者のレビュー完了は別々に表示する。

公式 CLI の認証を使用し、PETIT の API キーや認証トークンを抽出しない。個人契約を外部アプリから使う条件については各提供元の利用条件を参照する。[Claude Code の利用条件](https://code.claude.com/docs/en/legal-and-compliance)・[Antigravity CLI の接続条件](../brain/antigravity-cli.md)
