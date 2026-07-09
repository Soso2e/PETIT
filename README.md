# PETIT — Personal AI Assistant (MVP)

会話から意図を読み取り、ツールを使って生活・タスク・予定・記憶を支える、
自分専用のローカル AI アシスタント。詳しい思想は [`Concept.md`](./Concept.md) を参照。

この MVP は **ブラウザ（localhost）で動くテキストチャット** で、
LLM は **LM Studio**（OpenAI 互換のローカルサーバー）を利用します。

## 構成

```
backend/   FastAPI サーバー・エージェントループ・ツール
frontend/  チャット UI（静的ファイル）
storage/   SQLite などの実行時データ（git 管理外）
```

## セットアップ

1. 依存をインストール:

   ```bash
   pip install -r requirements.txt
   ```

2. LM Studio を起動し、ローカルサーバー（OpenAI 互換）を有効にする。
   デフォルトは `http://localhost:1234/v1`。モデルをロードしておく。

3. サーバー起動:

   ```bash
   uvicorn backend.main:app --reload
   # または
   python -m backend.main
   ```

4. ブラウザで <http://127.0.0.1:8000> を開く。

## 環境変数（任意）

| 変数 | 既定値 | 説明 |
|------|--------|------|
| `PETIT_LM_BASE_URL` | `http://localhost:1234/v1` | LM Studio のエンドポイント |
| `PETIT_LM_MODEL` | `local-model` | 使用モデル名（LM Studio 上の id） |
| `PETIT_HOST` / `PETIT_PORT` | `127.0.0.1` / `8000` | サーバーの待受 |
| `PETIT_OBSIDIAN_VAULT_DIRS` | なし | RAG検索対象にする既存Obsidian vault。Windowsは`;`区切りで複数指定 |
| `PETIT_VAULT_SUBDIR` | `PETIT` | PETITがMarkdownを書き込むvault内サブディレクトリ |
| `PETIT_AI_DAILY_DIR` / `PETIT_AI_MEMORY_DIR` | vault設定時は`<vault>/PETIT/Daily` / `Memory` | 会話ログ・長期記憶Markdownの出力先 |
| `NOTION_API_KEY` | なし | Notion インテグレーションの API キー |
| `NOTION_TASKS_DB_ID` | なし | タスクDBのID |
| `NOTION_PROP_TITLE` | `name` | タスク名プロパティ |
| `NOTION_PROP_DUE` | `Date` | 期限/日時プロパティ |
| `NOTION_PROP_STATUS` | `Status` | 状態プロパティ |
| `NOTION_PROP_PRIORITY` | `Priority` | 優先度プロパティ |
| `NOTION_PROP_CATEGORY` | `Category` | 分類プロパティ |

## 現在使えるツール

- `save_memory` / `search_memory` — 記憶の保存・検索（設定済みObsidian vaultも検索対象）
- `get_tasks` / `create_task` / `complete_task` — タスクの取得・作成・完了（Notion 設定時は連携）
- `add_task` — ローカル DB だけに保存する旧タスク追加ツール
- `create_handoff_note` / `restore_context` — 中断時の引き継ぎ・復帰
- `summarize_now` — 未整理の会話を手動要約
- `sync_obsidian_vault` — 既存Obsidian vaultをRAG検索用に手動同期
- `get_schedule` / `add_schedule` — 予定の取得・追加（ローカル DB）
- `create_daily_briefing` — 予定・タスク・最近の流れから朝ブリーフィングを作成
- `get_weather` / `search_news` / `start_background_research` — 天気・ニュース取得とバックグラウンド調査キュー

LM Studio が未起動でもサーバーは落ちず、UI 上にエラーを表示します。
## Obsidian vault をPETITのMarkdown脳にする

既存のObsidian vaultを使う場合は、`.env` などで `PETIT_OBSIDIAN_VAULT_DIRS` を指定します。PETITはvault全体のMarkdownを `petit_vault` としてChromaに索引化し、`search_memory` から会話記憶・要約・vaultノートを横断検索します。手動で同期したい場合は `sync_obsidian_vault` ツール、または `POST /api/vault/sync` を使います。

PETITが自動追記するMarkdownは、既定では最初のvault内の `PETIT/Daily` と `PETIT/Memory` に置かれます。既存ノートは読み取り・検索対象、自動書き込みは `PETIT/` 配下に限定する想定です。

## 開発

- 主軸ブランチは `develop`。機能追加は `feat/<機能名>`。
- 変更のたびに `PROGRESS.md` に追記する。
- ルール詳細は [`CLAUDE.md`](./CLAUDE.md)。
