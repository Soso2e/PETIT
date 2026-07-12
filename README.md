# PETIT — Personal AI Assistant (MVP)

設計とデータソースの役割は [ASSISTANT_ARCHITECTURE.md](ASSISTANT_ARCHITECTURE.md) を参照。

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

   プロジェクトルートの `.env` は起動時に自動読込されます。既に設定されているOS環境変数が優先されます。

4. ブラウザで <http://127.0.0.1:8000> を開く。

## 環境変数（任意）

| 変数 | 既定値 | 説明 |
|------|--------|------|
| `PETIT_LM_BASE_URL` | `http://localhost:1234/v1` | LM Studio のエンドポイント |
| `PETIT_LM_MODEL` | `local-model` | 使用モデル名（LM Studio 上の id） |
| `PETIT_CHAT_MODEL` | `PETIT_LM_MODEL` | 通常会話とツール結果の返答に使う常駐モデル |
| `PETIT_LIGHT_MAX_TOKENS` | `512` | 軽量回答の最大生成量 |
| `PETIT_HOST` / `PETIT_PORT` | `127.0.0.1` / `8000` | サーバーの待受 |
| `PETIT_OBSIDIAN_VAULT_DIRS` | なし | RAG検索対象にする既存Obsidian vault。Windowsは`;`区切りで複数指定 |
| `PETIT_VAULT_SUBDIR` | `PETIT` | PETITがMarkdownを書き込むvault内サブディレクトリ |
| `PETIT_EMBED_RETRY_SECONDS` | `60` | Embedding停止時に再試行するまでの秒数 |
| `NOTION_SYNC_TTL_SECONDS` | `300` | 自動読み取り同期を再利用する秒数 |
| `PETIT_CALENDAR_ICS_URLS` | なし | Google CalendarなどのiCal/ICS URL。Windowsは`;`区切りで複数指定 |
| `PETIT_CALENDAR_ICS_FILES` | なし | ローカルにエクスポートした`.ics`ファイル。Windowsは`;`区切りで複数指定 |
| `PETIT_CALENDAR_SYNC_TTL_SECONDS` | `300` | カレンダー読み取り同期を再利用する秒数 |
| `PETIT_AI_DAILY_DIR` / `PETIT_AI_MEMORY_DIR` | vault設定時は`<vault>/PETIT/Daily` / `Memory` | 会話ログ・長期記憶Markdownの出力先 |
| `NOTION_API_KEY` | なし | Notion インテグレーションの API キー |
| `NOTION_TASKS_DB_ID` | なし | タスクDBのID |
| `NOTION_PROP_TITLE` | `name` | タスク名プロパティ |
| `NOTION_PROP_DUE` | `Date` | 期限/日時プロパティ |
| `NOTION_PROP_STATUS` | `Status` | 状態プロパティ |
| `NOTION_PROP_PRIORITY` | `Priority` | 優先度プロパティ |
| `NOTION_PROP_CATEGORY` | `Category` | 分類プロパティ |
| `NOTION_PROP_DONE_DATE` | `DoneDate` | 完了日プロパティ |

## 現在使えるツール

- `save_memory` / `search_memory` — 記憶の保存・検索
- `search_brain_notes` / `edit_brain_note` — BRAINを限定検索し、対象Markdownへ安全に追記・完全一致置換
- `get_tasks` / `create_task` / `complete_task` — タスクの取得・作成・完了（Notion 設定時は連携）
- `add_task` — ローカル DB だけに保存する旧タスク追加ツール
- `create_handoff_note` / `restore_context` — 中断時の引き継ぎ・復帰
- `summarize_now` — 未整理の会話を手動要約
- `sync_obsidian_vault` — 既存Obsidian vaultをRAG検索用に手動同期
- `get_schedule` / `add_schedule` / `sync_calendar` — 予定取得、PETITローカル予定への追加、設定済みICSの読み取り同期
- `create_daily_briefing` — 予定・タスク・最近の流れから朝ブリーフィングを作成
- `get_current_time` — 現在の日付・時刻を取得
- `get_weather` / `search_news` / `start_background_research` — 天気・ニュース取得とバックグラウンド調査キュー

## 会話処理の最小フロー

通常の雑談は、短いsystem prompt・直近5会話・ユーザー発話だけを渡し、会話モデルを1回だけ呼びます。
ツール、RAG、Embedding、Notion/カレンダー同期、要約は実行しません。現在時刻はルールベースで直接取得します。
明確なタスク・予定・検索などだけ、発話に関係するツール定義を絞って渡します。
「今日何からやる？」のような計画相談では、未完了タスク・当日予定・BRAIN候補だけをPython側で限定取得し、LM Studio 1回で整理します。
会話のEmbeddingとMarkdown出力は応答後のバックグラウンド処理です。
Embeddingは同一テキストをプロセス内キャッシュで重複送信せず、Vaultはチャンク内容が変わったファイルだけ再Embeddingします。

Google CalendarのCodex/MCP接続はPETITプロセスへ自動共有されません。PETIT側で読むには
`PETIT_CALENDAR_ICS_URLS` にGoogle Calendarの非公開iCal URLを設定するか、`PETIT_CALENDAR_ICS_FILES`
にエクスポート済み`.ics`ファイルを指定します。設定後は予定相談、朝ブリーフィング、`sync_calendar`、
`POST /api/calendar/sync` から `calendar_events_cache` へ読み取り専用で同期します。
`add_schedule` はICSやGoogle Calendar本体へは書かず、現在は `destination=local` のPETITローカル予定だけへ追加します。
書き込み先はprovider境界で分離しており、将来Google Calendar OAuthアダプターを追加できます。

## 書き込み確認

Notionタスク作成・完了、ローカル予定追加、長期記憶・引き継ぎ保存、BRAIN修正は、ツール呼び出し時点では実行されません。
ブラウザに対象と変更内容、および「実行する / キャンセル」を表示し、`POST /api/actions/{approval_id}` で確認された操作だけを1回実行します。確認待ちは10分で期限切れになります。
BRAIN編集は設定済みVault内の既存`.md`だけに限定し、`_private`・除外フォルダ・Vault外パスを拒否します。

LM Studio が未起動でもサーバーは落ちず、UI 上にエラーを表示します。

## Obsidian vault をPETITのMarkdown脳にする

既存のObsidian vaultを使う場合は、`.env` などで `PETIT_OBSIDIAN_VAULT_DIRS` を指定します。PETITは`_private`・添付・内部設定を除くvaultのMarkdownを `petit_vault` としてChromaに索引化し、`search_memory` から会話記憶・要約・vaultノートを横断検索します。手動で同期したい場合は `sync_obsidian_vault` ツール、または `POST /api/vault/sync` を使います。

PETITが自動追記するMarkdownは、既定では最初のvault内の `PETIT/Daily` と `PETIT/Memory` に置かれます。既存ノートは読み取り・検索対象、自動書き込みは `PETIT/` 配下に限定する想定です。

## 開発

- 主軸ブランチは `develop`。機能追加は `feat/<機能名>`。
- 変更のたびに `PROGRESS.md` に追記する。
- ルール詳細は [`CLAUDE.md`](./CLAUDE.md)。
