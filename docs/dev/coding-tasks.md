# CLIによるローカル開発タスク（#225 / #362）

## 責務と既存機能の再利用

会話のBrainと開発Jobの実行Providerを別々に選択する。BrainがCodexでも、承認した開発JobをAntigravity CLIへ渡せる。既存のThread/Turn/Approval/Effect Receipt、tasks_cache、SQLiteを正本として使い、別DBは作らない。既存機能の削除・置換は不要。

- `coding_jobs.py`: 同じSQLiteのJob/イベント、明示許可したrepository、専用コピー、取消/復旧、作業ファイルの検証。
- `coding_agents.py`: Codex app-server dynamic ToolまたはAntigravity CLI構造化出力。両方とも直接のShell/ファイルToolを公開せず、Jobに限定したCoreのToolを呼ぶ。
- `coding_api.py` / `tools/coding.py`: Webと会話の入口。会話開始は既存の確認付きTool、Web開始は対象・開始コミット・目的・CLIを表示した明示承認。
- `frontend/development.html`: 状態・進捗・変更ファイル・diff・静的チェック・未確認事項を同じJob IDで表示。

## 最初の実装単位

1. 管理者がGitルートを最大8件登録。既存の観測用Read許可を開発Write許可に流用しない。
2. 依頼を`proposed`として保存し、通常Task IDと関連付ける。曖昧なrepository名を推測で選ばない。
3. 承認後に`queued`へ進める。sourceのHEADを再検査し、固定したcommitからローカルcloneを作る。未コミット変更を含めず、元checkoutは変更しない。cloneのremoteは除去する。
4. CLIへ目的・制約・Tool catalogを送り、Coreが`list_files`、`read_file`、`write_file`、`run_static_checks`を検証して実行する。`.git`、`_private`、実環境設定、リンク、外部パスは拒否する。
5. 静的チェックと差分を保存し、`ready_for_review`または`checks_failed`へ進める。モデルの成功発言だけで`completed`にしない。利用者の明示したレビュー完了のみで完了にする。

最初の単位では任意Shell・依存インストール・任意テストコード実行・ファイル削除・Push・PR作成・mergeを公開しない。Python構文、JavaScript構文、git diff --checkを静的に確認する。実際のテスト・実ホスト動作・CIは`not_run`として区別し、後続でrepositoryごとに承認した実行方式を追加する。

## 永続状態と移行

`coding_jobs` / `coding_job_events`を既存DBへ追加する前にSQLite backup APIでbackupしquick_checkする。既存のTask・会話・履歴は削除しない。既存3Provider順位は維持し、Antigravity CLIは明示接続時に追加する。

再送はrequest IDと入力hashを照合し、同一Jobを返す。承認とclaimは条件付きUPDATEで一度だけ消費する。再起動時の`running`は`interrupted`にし、自動再実行しない。取消後も差分と専用コピーを残す。設定・接続の取消、deadline、出力上限を実行中にも検査し、所有CLIプロセスを終了する。

`local_only`のThreadから外部CLIへの開発委譲は承認後も拒否し、そのThreadの文脈を送らない。

## CLI利用の境界

Antigravityは本人の明示依頼による実装であり、Googleの個人契約における第三者アプリ内利用の許諾を取得したことにはならない。OAuth token抽出、非公開API、MCP proxy、アカウント回転は行わない。公式CLIが管理する認証を使い、CoreのAPIキー等を子プロセスへ渡さない。取得できない契約枠・実モデル名・quotaはunknownのまま表示する。

CLI本体に公開する直接Toolは制限し、JobができることはCoreのcatalogに限定する。CLIのプロンプトへの注意書きや事後のイベント検出だけを権限制御の根拠にはしない。実CLI・合成DB・Mock・ブラウザ・実端末の証拠を分ける。
