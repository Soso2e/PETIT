# PROGRESS — 変更履歴

変更を加えるたびに1行追記する。時刻は UTC。

| 日付 | 時間 | 回数 | 変更内容 |
|------|------|------|----------|
| 2026-06-25 | 08:47 | #1 | MVP 実装: FastAPI バックエンド（agent ループ + LM Studio クライアント + SQLite）、ツール（save/search_memory, get/add_task, get_schedule）、ブラウザ用チャット UI、CLAUDE.md / README / .gitignore を追加。`develop` ブランチを作成。 |
| 2026-06-25 | 09:05 | #2 | Notion 連携実装: notion_client.py（REST APIクライアント・ページパース・ページネーション対応）、tools/notion.py（sync_notion_tasks ツール + upsert）、get_tasks が Notion 設定時に自動同期、/api/health に Notion 設定状況を追加、.env.example 作成。`feat/notion` ブランチ。 |
