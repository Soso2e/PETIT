# PROGRESS — 変更履歴

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書きしてよい。

- TimeTree バックアップ: `tools/timetree_backup.py` 実装済みだが本番 E2E 未検証（実認証情報待ち）。カレンダーコード確認は初回だけ対話実行が必要（`timetree-exporter -e your@email.com`）。
- Notion / RAG: 実装済み。LM Studio・Notion 実接続での動作確認は未確認。
- 自律要約 / 記憶注入 / 能動的な opener: 実装済み。実 LM Studio での口調・記憶想起・要約品質は未確認。
- ニュース / 天気 / バックグラウンドキュー: 実装済み。ツール登録・SQLite キュー・ワーカーモック・外部 API 疎通（ニュース1件、東京天気）は確認済み。LM Studio 経由の意図選択は未確認。
- 次にやること: 実 `.env` で TimeTree を E2E 確認 → launchd（Mac）/ cron（Linux）で毎日自動実行を有効化。実 LM Studio で PETIT の会話品質とキュー選択も確認する。
## 履歴

変更を加えるたびに1行追記する（追記専用・既存行は触らない）。時刻は UTC。

| 日付 | 時間 | 回数 | 変更内容 |
|------|------|------|----------|
| 2026-06-25 | 08:47 | #1 | MVP 実装: FastAPI バックエンド（agent ループ + LM Studio クライアント + SQLite）、ツール（save/search_memory, get/add_task, get_schedule）、ブラウザ用チャット UI、CLAUDE.md / README / .gitignore を追加。`develop` ブランチを作成。 |
| 2026-06-25 | 09:05 | #2 | Notion 連携実装: notion_client.py（REST APIクライアント・ページパース・ページネーション対応）、tools/notion.py（sync_notion_tasks ツール + upsert）、get_tasks が Notion 設定時に自動同期、/api/health に Notion 設定状況を追加、.env.example 作成。`feat/notion` ブランチ。 |
| 2026-06-25 | 13:20 | #3 | RAG検索実装: chroma_client.py（ChromaDB永続化 + LM Studio embeddings カスタム関数 + graceful fallback）、search_memory がセマンティック検索→キーワード自動フォールバック、save_memory と会話ターンを Chroma に自動索引化、起動時に既存SQLiteデータをバックグラウンド同期、/api/health に RAG ステータス追加。`feat/rag` ブランチ。 |
| 2026-06-25 | 17:50 | #4 | Progress Log を1ファイルに整理: 詳細ログ `progress.md` を削除し、進捗記録を `PROGRESS.md`（表形式）に一本化。CLAUDE.md の Progress Log ルールとディレクトリ構成を更新。 |
| 2026-06-25 | 18:10 | #5 | PROGRESS.md に「現在の状態 / 未確認・TODO」セクション（上書き可）を追加し、履歴表（追記専用）と2部構成に。CLAUDE.md の作業開始/終了ルールを同期。 |
| 2026-06-25 | 18:30 | #6 | 自律的な会話蓄積を実装: N時間おきの自動要約 scheduler.py、summarizer.py、Obsidian形式の markdown_export.py、summaries テーブル、summarize_now ツール、/api/summarize・/api/summaries、search_memory の要約検索対応を追加。`claude/autonomous-conversation-md-db-tlyat4` ブランチ。 |
| 2026-06-25 | 18:28 | #7 | 「人間っぽく喋る」実装: recall.py で毎ターン関連記憶+直近要約を注入、proactive.py + /api/proactive で開いた瞬間の話しかけ、agent.py の相棒口調プロンプト、フロントの opener 表示を追加。`claude/autonomous-conversation-md-db-tlyat4` ブランチ。 |
| 2026-07-05 | 07:43 | #8 | ローカル予定追加ツール `add_schedule` を実装。`calendar_events_cache` に予定を保存し、`get_schedule` で取得できることをテスト用DBで確認。README のツール一覧を更新。 |
| 2026-07-05 | 07:49 | #9 | 朝ブリーフィング実装: `briefing.py`、`/api/briefing`、`create_daily_briefing` ツールを追加。予定・未完了タスク・直近要約から「今やる1個」を含むブリーフィングを生成し、LM Studio 不通時は定型文へフォールバック。 |
| 2026-07-06 | 03:13 | #10 | ニュース/天気ツールと SQLite バックグラウンドキューを実装。ツール登録・構文・ワーカーモック・外部 API 疎通を確認、LM Studio 経由の意図選択は未確認。 |
| 2026-07-08 | 08:09 | #11 | PETIT 用ローカルLLM要件を調査・整理。コード変更なし、実モデル検証は未実施。 |

