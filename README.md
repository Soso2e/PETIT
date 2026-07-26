# PETIT — Personal AI Assistant (MVP)

設計とデータソースの役割は [ASSISTANT_ARCHITECTURE.md](ASSISTANT_ARCHITECTURE.md) を参照。
主要な概念の使い分けは [docs/terminology.md](docs/terminology.md) を参照。

会話から意図を読み取り、ツールを使って生活・タスク・予定・記憶を支える、
自分専用のローカル AI アシスタント。詳しい思想は [`Concept.md`](./Concept.md) を参照。

この MVP は **ブラウザ（localhost）で動くテキストチャット** で、
LLM は **LM Studio**（OpenAI 互換のローカルサーバー）を利用します。

## 構成

```text
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

## 音声読み上げを使う

PETITの音声読み上げは、追加料金なしで次の2方式を使います。

- **ブラウザ標準TTS**: AivisSpeech未準備・停止中でも使える高速なフォールバック
- **AivisSpeech**: ローカルで高品質な日本語音声を生成

AivisSpeechを使う場合は、先に初期セットアップが必要です。
インストール、音声モデル追加、Engine起動、`.env`設定、診断CLI、WAV再生までの手順は
[`docs/aivis_speech.md`](docs/aivis_speech.md) を参照してください。

最初に次を実行し、結果の `stage` を確認します。

```bash
python scripts/diagnose_aivis_speech.py
```

成功条件は次です。

```json
{
  "ok": true,
  "stage": "complete"
}
```

AivisSpeechが使えなくても、PETITのテキスト会話は継続し、対応ブラウザでは標準TTSへ切り替わります。

## 環境変数（主なもの）

| 変数 | 既定値 | 説明 |
|------|--------|------|
| `PETIT_LM_BASE_URL` / `PETIT_LM_MODEL` / `PETIT_LM_API_KEY` | local default | 旧互換の共通設定。個別設定未指定時のフォールバック |
| `PETIT_CHAT_BASE_URL` / `PETIT_CHAT_MODEL` / `PETIT_CHAT_API_KEY` | 各 `PETIT_LM_*` | 雑談・短い確認用の接続先・モデル |
| `PETIT_AGENT_BASE_URL` / `PETIT_AGENT_MODEL` / `PETIT_AGENT_API_KEY` | 各 `PETIT_LM_*` | ツール・計画・BRAIN/Notion/予定用の接続先・モデル |
| `PETIT_LIGHT_MAX_TOKENS` | `512` | 軽量回答の最大生成量 |
| `PETIT_MAX_TOOL_ITERATIONS` | `3` | 1ターンで許可するツール実行ラウンド数。最終回答用のLLM呼び出しは別に許可 |
| `PETIT_TOOL_RESULT_MODE` | `auto` | `role=tool`を優先し、LM Studioのテンプレート非対応時だけ互換user follow-upへ退避。`tool` / `user`固定も可能 |
| `PETIT_USE_SONA_CORE` | `0` | `1`の場合のみ、予定取得とローカル予定追加をSona Agent Core経由で実行 |
| `PETIT_OWNER_ID` / `PETIT_PERSONAL_SCOPE_ID` | `soso` / `soso` | PETIT内部ユーザー、Core Actor、`personal` Scopeの識別子 |
| `PETIT_SONA_CORE_AUDIT_PATH` | `storage/audit/sona_agent_core.jsonl` | Core Tool実行の監査ログ |
| `PETIT_SONA_CORE_APPROVAL_TTL_SECONDS` | `600` | Core Approvalの有効期限（秒） |
| `PETIT_HOST` / `PETIT_PORT` | `127.0.0.1` / `8000` | サーバーの待受 |
| `PETIT_OBSIDIAN_VAULT_DIRS` | なし | RAG検索対象にする既存Obsidian vault。Windowsは`;`区切り |
| `PETIT_VAULT_SUBDIR` | `PETIT` | PETITがMarkdownを書き込むvault内サブディレクトリ |
| `PETIT_EMBED_RETRY_SECONDS` | `60` | Embedding停止時の再試行間隔 |
| `PETIT_CALENDAR_ICS_URLS` | なし | Google CalendarなどのiCal/ICS URL |
| `PETIT_CALENDAR_ICS_FILES` | なし | ローカルの`.ics`ファイル |
| `PETIT_CALENDAR_SYNC_TTL_SECONDS` | `300` | カレンダー読み取り同期のTTL |
| `PETIT_AI_DAILY_DIR` / `PETIT_AI_MEMORY_DIR` | vault設定時は`<vault>/PETIT/Daily` / `Memory` | 会話ログ・長期記憶Markdownの出力先 |
| `NOTION_API_KEY` | なし | NotionインテグレーションのAPIキー |
| `NOTION_PROJECTS_DB_ID` | なし | 個人プロジェクトDBのID |
| `NOTION_TASKS_DB_ID` | なし | タスクDBのID |
| `NOTION_SYNC_TTL_SECONDS` | `300` | Notion読み取り同期のTTL |
| `NOTION_PROP_TITLE` | `name` | 旧互換タスク名プロパティ |
| `NOTION_PROP_DUE` | `Date` | 期限/日時プロパティ |
| `NOTION_PROP_STATUS` | `Status` | 状態プロパティ |
| `NOTION_PROP_PRIORITY` | `Priority` | 優先度プロパティ |
| `NOTION_PROP_CATEGORY` | `Category` | 分類プロパティ |
| `NOTION_PROP_DONE_DATE` | `DoneDate` | 完了日プロパティ |
| `LINKRAFT_BASE_URL` | なし | owner-only PETIT read APIを公開したLinkraftのURL |
| `LINKRAFT_PETIT_READ_TOKEN` | なし | Linkraftと共有する読み取り専用Bearer Token |
| `LINKRAFT_SYNC_TTL_SECONDS` | `300` | Linkraftプロジェクト差分同期のTTL |
| `PETIT_GITHUB_TOKEN` | なし | private repositoryにも使える最小権限のGitHub read token |
| `PETIT_GITHUB_API_URL` | `https://api.github.com` | GitHub REST APIの接続先 |
| `PETIT_GITHUB_SYNC_TTL_SECONDS` | `300` | GitHub evidence同期のTTL |
| `PETIT_GITHUB_INITIAL_LOOKBACK_DAYS` | `30` | 初回同期で遡る日数 |
| `PETIT_GITHUB_MAX_CHECK_COMMITS` | `50` | 1回でcheckを確認するcommit数の上限 |
| `PETIT_GITHUB_MAX_DEPLOYMENTS` | `20` | 1回でstatusを確認する最近のdeployment数 |
| `PETIT_VAPID_PUBLIC_KEY` | なし | ブラウザ購読に渡すURL-safe Base64のVAPID公開鍵 |
| `PETIT_VAPID_PRIVATE_KEY` | なし | Git管理外に置くVAPID秘密鍵PEMの絶対パスまたはエンコード済み秘密鍵 |
| `PETIT_VAPID_SUBJECT` | なし | VAPID連絡先。`mailto:`または公開可能な`https:` URL |
| `PETIT_WEB_PUSH_TTL_SECONDS` | `300` | Push Serviceが通知を保持する秒数 |

Notion Adapter v2、Notion会話検索、Linkraft、GitHub evidence、Web Pushの詳細設定は、
[`docs/notion_adapter_v2.md`](docs/notion_adapter_v2.md)、
[`docs/notion_search.md`](docs/notion_search.md)、
[`docs/linkraft_owner_sync.md`](docs/linkraft_owner_sync.md)、
[`docs/github_evidence.md`](docs/github_evidence.md)、
[`docs/web_push_notifications.md`](docs/web_push_notifications.md) を参照してください。

## 現在使える主なツール

- `save_memory` / `search_memory` — 記憶の保存・検索
- `search_brain_notes` / `edit_brain_note` — BRAINを限定検索し、安全に追記・完全一致置換
- `get_tasks` / `create_task` / `complete_task` — タスク取得・作成・完了
- `add_task` — ローカルDBだけに保存する旧タスク追加
- `create_handoff_note` / `restore_context` — 中断時の引き継ぎ・復帰
- `summarize_now` — 未整理会話の手動要約
- `sync_obsidian_vault` — 既存Obsidian vaultをRAG検索用に同期
- `get_schedule` / `add_schedule` / `sync_calendar` — 予定取得、ローカル予定追加、ICS同期
- `create_daily_briefing` — 予定・タスク・最近の流れから朝ブリーフィングを作成
- `get_current_time` — 現在の日付・時刻
- `get_weather` / `search_news` / `start_background_research` — 天気・ニュース・調査キュー
- `create_internal_project` / `activate_internal_project` / `add_internal_project_alias` — 確認後に内部プロジェクトを登録・切替・別名追加
- `save_project_completion` — 確認済み到達状態をcheckpointとイベントへ保存
- `search_notion` — 共有済みNotionページを限定検索し、プロパティ・本文抜粋・更新日時・URLを取得
- `sync_notion_tasks` / `get_notion_project_candidates` / `link_notion_project_candidate` — Notion Relation同期と確認付き紐付け
- `sync_linkraft_projects` / `get_linkraft_project_candidates` / `link_linkraft_project_candidate` — Linkraft owner-only同期と確認付き紐付け
- `inspect_github_repository` / `sync_github_evidence` — GitHub repository候補の読取と確認済みrepositoryの証拠同期
- `get_github_repository_candidates` / `link_github_repository_candidate` — GitHub候補一覧と確認付き紐付け

## Project Continuity Engine

PETITは複数プロジェクトの開始・終了・切り替え・再開をSQLiteで継続管理します。通常雑談とは別の決定論的な経路で処理するため、LM Studioが停止していても保存済み状態から再開できます。

### 開始・再開

```text
Linkraftやる
プチ進める
PETITに戻る
さっきの続きやる
```

確認済みの正式名・別名が一意なら、`active_project_state`を切り替えます。その直後、選択した内部プロジェクトに紐付く外部sourceのうち、次の条件をすべて満たすものだけを更新します。

```text
project_id = 選択したプロジェクト
status = active
confirmed_at IS NOT NULL
```

- Notionは再開ターン内で最大1回だけ、既存TTLを尊重して同期します。
- Linkraftは選択プロジェクトの確認済み外部IDだけを、保存済みcursorから差分同期します。
- GitHubは選択プロジェクトの確認済み`owner/name`だけを読み、commit・PR・check・deploymentを別種のevidenceとして同期します。
- 未確認候補、removed link、別プロジェクト、未対応providerは呼びません。
- 1ソースが失敗しても、保存済みcheckpointからの再開は止めません。
- 前回成功キャッシュがある場合は保持し、staleと明示します。

同期後、次の順で対象プロジェクトだけを取得します。

1. `project_checkpoints`
2. 確認済み・正規化済み`project_events`
3. 確認済み`episode_project_links`の会話エピソード
4. 旧`handoff_notes`の互換情報
5. 確認済み外部source linkのfresh/stale状態

別プロジェクトの記憶や未確認Relationは混ぜません。別名が衝突する場合は候補を出し、勝手に切り替えません。詳細は [`docs/project_source_refresh.md`](docs/project_source_refresh.md) を参照してください。
