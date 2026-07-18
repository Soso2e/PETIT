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
| `PETIT_LM_BASE_URL` / `PETIT_LM_MODEL` / `PETIT_LM_API_KEY` | local default | 旧互換の共通設定。個別設定未指定時のフォールバック |
| `PETIT_CHAT_BASE_URL` / `PETIT_CHAT_MODEL` / `PETIT_CHAT_API_KEY` | 各 `PETIT_LM_*` | 雑談・短い確認用の接続先・モデル |
| `PETIT_AGENT_BASE_URL` / `PETIT_AGENT_MODEL` / `PETIT_AGENT_API_KEY` | 各 `PETIT_LM_*` | ツール・計画・BRAIN/Notion/予定用の接続先・モデル |
| `PETIT_LIGHT_MAX_TOKENS` | `512` | 軽量回答の最大生成量 |
| `PETIT_USE_SONA_CORE` | `0` | `1`の場合のみ、予定取得とローカル予定追加をSona Agent Core経由で実行するFlag |
| `PETIT_OWNER_ID` / `PETIT_PERSONAL_SCOPE_ID` | `soso` / `soso` | PETIT内部のユーザー、Core Actor、`personal` Scopeの識別子 |
| `PETIT_SONA_CORE_AUDIT_PATH` | `storage/audit/sona_agent_core.jsonl` | Core Tool実行のJSON Lines監査ログ出力先 |
| `PETIT_SONA_CORE_APPROVAL_TTL_SECONDS` | `600` | Core Approvalの有効期限（秒） |
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
- `create_internal_project` / `activate_internal_project` / `add_internal_project_alias` — 確認後にPETIT内部プロジェクトを登録・切替・別名追加
- `save_project_completion` — 確認済みの到達状態をプロジェクトcheckpointとイベントへ保存

## Project Continuity Engine — Phase 1

PETITは、複数プロジェクトの開始・終了・切り替え・再開をSQLiteで継続管理します。通常雑談とは別の決定論的な経路で処理するため、LM Studioが停止していても保存済み状態から再開できます。

### 開始・再開

```text
Linkraftやる
プチ進める
PETITに戻る
さっきの続きやる
```

確認済みの正式名・別名が一意なら、`active_project_state`を切り替え、次の順で対象プロジェクトだけを取得します。

1. `project_checkpoints`
2. 確認済みの`project_events`
3. 確認済み`episode_project_links`の会話エピソード
4. 旧`handoff_notes`の互換情報
5. 確認済み外部source linkのfresh/stale状態

別プロジェクトの記憶や未確認Relationは混ぜません。別名が衝突する場合は候補を出し、勝手に切り替えません。

### 終了確認

```text
終わった
実装だけ終わった。ブラウザ確認はまだ
テストも通った。次は実画面確認
デプロイしたけど本番確認はまだ
今日はここまで
```

`終わった`を即座に完全完了へせず、実装・自動テスト・実画面・デプロイ・本番確認のどこまで到達したかを確認します。明示された事実だけを証拠として扱い、プレビュー承認後に一度だけ保存します。

保存状態は最低限、`implemented`、`automated_tests_verified`、`ui_verified`、`deployed`、`production_verified`、`paused`、`blocked`、`completed`を区別します。

### 新規登録・別名

```text
Roomies開発する
「Cooking Combat」をプロジェクト登録して
「プチ」をPETITの別名にして
```

未登録名は自動作成せず、登録プレビューを表示します。承認後に`projects`と`project_aliases`へ一度だけ保存し、必要なら現在プロジェクトへ切り替えます。別名衝突は事前に明示し、承認して追加した場合も以降のルーティングでは候補確認を維持します。

### 外部ソース

Phase 1のSQLiteは外部正本を置き換えず、内部ID、別名、確認状態、checkpoint、source linkを保持します。source linkは未確認のまま候補登録でき、確認・解除が可能です。別プロジェクトへ変更する場合は、アクティブな紐付けを先に解除した上で明示的に再割り当てします。

Phase 2では次を接続します。

- 個人プロジェクト・個人タスク: Notion
- Life is Tech／教え子向けプロジェクト: Linkraft（そそ本人所有のみ）
- コード変更の事実: GitHub
- 長期知識・設計: BRAIN / Obsidian

## 会話処理の最小フロー

通常の雑談は、短いsystem prompt・直近5会話・ユーザー発話だけを渡し、会話モデルを1回だけ呼びます。
ツール、RAG、Embedding、Notion/カレンダー同期、要約は実行しません。現在時刻はルールベースで直接取得します。
明確なプロジェクト開始・終了・登録は、通常モデルより前に決定論的なProject Continuity経路で処理します。
明確なタスク・予定・検索などだけ、発話に関係するツール定義を絞って渡します。
「今日何からやる？」のような計画相談では、未完了タスク・当日予定・BRAIN候補だけをPython側で限定取得し、LM Studio 1回で整理します。
会話のEmbeddingとMarkdown出力は応答後のバックグラウンド処理です。
Embeddingは同一テキストをプロセス内キャッシュで重複送信せず、Vaultはチャンク内容が変わったファイルだけ再Embeddingします。

ChatとAgentはURL・APIキー・モデルを個別設定できます。両方を同じ値にすれば1モデル構成のままです。Agentの軽量`/models`確認が失敗した場合、既にPython側で安全に取得済みの読み取り結果はChatモデルで整形して返します。ツール選択・書き込みはChatへ勝手に落とさず、利用不能として表示します。
`/api/health` は生成を行わないキャッシュ付きモデル確認、同期状態、索引状態を返します。各応答の詳細欄では経路、モデル、ツール、同期鮮度、LLM/Embedding回数、時間、Agentフォールバック、Project Continuityの参照件数を確認できます。

Google CalendarのCodex/MCP接続はPETITプロセスへ自動共有されません。PETIT側で読むには
`PETIT_CALENDAR_ICS_URLS` にGoogle Calendarの非公開iCal URLを設定するか、`PETIT_CALENDAR_ICS_FILES`
にエクスポート済み`.ics`ファイルを指定します。設定後は予定相談、朝ブリーフィング、`sync_calendar`、
`POST /api/calendar/sync` から `calendar_events_cache` へ読み取り専用で同期します。
同期結果はSQLiteの `sync_state` にソース別で保存され、`/api/health` と予定・タスク取得結果で最終成功・失敗・stale状態を確認できます。取得失敗時は直前の正常キャッシュを維持します。TimeTreeは `TIMETREE_EMAIL` / `TIMETREE_PASSWORD` / `TIMETREE_CALENDAR_CODE` を設定した場合だけ、読み取り専用ICSソースとして同期されます（`timetree-exporter` が必要です）。

`add_schedule` はICSやGoogle Calendar本体へは書かず、現在は `destination=local` のPETITローカル予定だけへ追加します。
書き込み先はprovider境界で分離しており、将来Google Calendar OAuthアダプターを追加できます。

## 書き込み確認

Notionタスク作成・完了、ローカル予定追加、長期記憶・引き継ぎ保存、BRAIN修正、プロジェクト登録・別名追加・終了checkpoint保存は、ツール呼び出し時点では実行されません。
ブラウザに対象と変更内容、および「実行する / キャンセル」を表示し、`POST /api/actions/{approval_id}` で確認された操作だけを1回実行します。確認待ちは10分で期限切れになります。
BRAIN編集は設定済みVault内の既存`.md`だけに限定し、`_private`・除外フォルダ・Vault外パスを拒否します。

`PETIT_USE_SONA_CORE=1`では`add_schedule`だけがCoreのSQLite Approval Storeへ切り替わります。承認画面に表示した元Invocationを一回だけ消費し、永続IdempotencyとAuditを記録してから既存`add_schedule`をAdapter経由で呼びます。`destination=local`以外は拒否し、他の書き込みToolは従来経路のままです。

LM Studio が未起動でもサーバーは落ちず、UI 上にエラーを表示します。

## Obsidian vault をPETITのMarkdown脳にする

既存のObsidian vaultを使う場合は、`.env` などで `PETIT_OBSIDIAN_VAULT_DIRS` を指定します。PETITは`_private`・添付・内部設定を除くvaultのMarkdownを `petit_vault` としてChromaに索引化し、`search_memory` から会話記憶・要約・vaultノートを横断検索します。手動で同期したい場合は `sync_obsidian_vault` ツール、または `POST /api/vault/sync` を使います。

PETITが自動追記するMarkdownは、既定では最初のvault内の `PETIT/Daily` と `PETIT/Memory` に置かれます。既存ノートは読み取り・検索対象、自動書き込みは `PETIT/` 配下に限定する想定です。

## 開発

- 主軸ブランチは `develop`。機能追加は `feat/<機能名>`。
- Project Continuityの限定テスト: `python -m unittest tests.test_project_continuity tests.test_project_router tests.test_project_completion tests.test_project_resume tests.test_project_registration`
- 全Python構文確認: `python -m compileall backend tests`
- 変更のたびに `PROGRESS.md` に追記する。
- ルール詳細は [`CLAUDE.md`](./CLAUDE.md)。
