# PROGRESS — 変更履歴

変更を加えるたびに1行追記する。時刻は UTC。

| 日付 | 時間 | 回数 | 変更内容 |
|------|------|------|----------|
| 2026-06-25 | 08:47 | #1 | MVP 実装: FastAPI バックエンド（agent ループ + LM Studio クライアント + SQLite）、ツール（save/search_memory, get/add_task, get_schedule）、ブラウザ用チャット UI、CLAUDE.md / README / .gitignore を追加。`develop` ブランチを作成。 |
| 2026-06-25 | 09:05 | #2 | Notion 連携実装: notion_client.py（REST APIクライアント・ページパース・ページネーション対応）、tools/notion.py（sync_notion_tasks ツール + upsert）、get_tasks が Notion 設定時に自動同期、/api/health に Notion 設定状況を追加、.env.example 作成。`feat/notion` ブランチ。 |
| 2026-06-25 | 13:20 | #3 | RAG検索実装: chroma_client.py（ChromaDB永続化 + LM Studio embeddings カスタム関数 + graceful fallback）、search_memory がセマンティック検索→キーワード自動フォールバック、save_memory と会話ターンを Chroma に自動索引化、起動時に既存SQLiteデータをバックグラウンド同期、/api/health に RAG ステータス追加。`feat/rag` ブランチ。 |
| 2026-06-25 | 18:30 | #4 | 自律的な会話蓄積を実装: 会話を N時間おき(既定3h)に自動要約して長期記憶へ蓄積する scheduler.py（標準ライブラリ threading）と summarizer.py（要約+事実/作業中の自動抽出→SQLite/Chroma/Markdown）、Obsidian形式の markdown_export.py（AI_Daily/AI_Memory・YAMLフロントマター・ウィキリンク・追記専用）、summaries テーブル、summarize_now ツール、/api/summarize・/api/summaries エンドポイント、search_memory が要約も検索対象に。`claude/autonomous-conversation-md-db-tlyat4` ブランチ。 |
| 2026-06-25 | 18:28 | #5 | 「人間っぽく喋る」実装（有能アシスタント寄りのまま人間味）: recall.py で毎ターン関連記憶+直近要約を自動でプロンプト注入（記憶の常時注入）、proactive.py + /api/proactive で PETIT 側から最初に話しかける能動性（時間帯・作業中文脈を踏まえた切り出し、LM不在時テンプレ）、agent.py のシステムプロンプトを相棒口調＋短文＋相槌＋記憶コールバックに刷新、フロント（app.js/index.html）が起動時に opener を取得して表示。全て LM/embedding 不在でも degrade。`claude/autonomous-conversation-md-db-tlyat4` ブランチ。 |
