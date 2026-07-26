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

### GitHub evidenceと完了状態の境界

GitHub上の事実は、PETIT checkpointを自動で上書きしません。

- commit存在は、特定のrevisionが存在する証拠であり、実装全体の完了証明ではありません。
- check successは、そのcheckが対象SHAで成功した証拠です。実画面・本番確認は証明しません。
- PR mergeはbase branchへ統合された証拠です。deployは証明しません。
- deployment successはGitHubがenvironment/refへの配布成功を報告した証拠です。本番機能確認は証明しません。

同じcheckが`in_progress`から`success`へ変わる場合はdefault branch headを再確認し、deployment本体の作成後にstatusだけ変わった場合も最近のdeployment statusを再確認します。

### 新規登録・別名

```text
Roomies開発する
「Cooking Combat」をプロジェクト登録して
「プチ」をPETITの別名にして
```

未登録名は自動作成せず、登録プレビューを表示します。承認後に`projects`と`project_aliases`へ一度だけ保存し、必要なら現在プロジェクトへ切り替えます。別名衝突は事前に明示し、承認して追加した場合も以降のルーティングでは候補確認を維持します。

### 外部ソース

SQLiteは外部正本を置き換えず、内部ID、別名、確認状態、checkpoint、source link、正規化イベント、キャッシュを保持します。source linkは未確認候補として登録でき、確認・解除・再割り当てが可能です。

現在接続済み:

- 個人プロジェクト・個人タスク: Notion Adapter v2
- Life is Tech／教え子向けプロジェクト: Linkraft（そそ本人所有のみ）
- コード・PR・CI・deploymentの事実: GitHub evidence Adapter

次の対象:

- 長期知識・設計: BRAIN / Obsidian

## 会話処理の最小フロー

通常の雑談は、短いsystem prompt・直近3往復以内・ユーザー発話だけを渡し、会話モデルを1回だけ呼びます。ツール、RAG、Embedding、外部同期、要約は実行しません。

明確なプロジェクト開始・終了・登録、純粋な挨拶、現在時刻、明示的なタスク・予定・BRAIN要求は、AIルーターより前に決定論的に処理します。これにより、明確な要求で経路判定用LLMを余分に呼びません。

明示的なツール語がない「傘を持つべき？」のような発話だけ、軽量Chatルーターが許可リスト内の候補ツールを提案します。提案は登録済みツールと照合し、未許可・未登録名を捨ててからAgentへ公開します。

GitHubの一般的な雑談ではツールを公開しません。`owner/name`やGitHub URLの登録・紐付け、候補確認、明示的な同期依頼だけをGitHub evidenceツールへルーティングします。

「Notionから〜を調べて」のような明示的なNotion参照は、ルーターLLMを通さず`search_notion`を実行します。検索結果がある場合だけAgentを1回呼んで整理し、未設定・0件・API失敗はPython側で区別して直接返します。通常会話ではNotion APIを呼びません。

ツール呼び出し後は、標準の`assistant.tool_calls`と`role: tool`で結果を戻します。LM StudioのJinjaテンプレートがこの形式を拒否した場合だけ、同じターン内で従来のuser follow-up形式へ自動的に切り替えます。

Agentは既定で最大3回のツール実行ラウンドを行え、その後に最終回答を生成できます。同じツールでも引数が異なれば再実行でき、完全一致する重複呼び出しは停止します。書き込みツールは従来どおり確認待ちへ変換され、即時実行されません。

「今日何からやる？」のような計画相談では、未完了タスク・当日予定・BRAIN候補だけをPython側で限定取得し、LM Studio 1回で整理します。

会話のEmbeddingとMarkdown出力は応答後のバックグラウンド処理です。Embeddingは同一テキストをプロセス内キャッシュで重複送信せず、Vaultは内容が変わったファイルだけ再Embeddingします。

ChatとAgentはURL・APIキー・モデルを個別設定できます。Agent停止時は、安全に取得済みの読み取り結果だけChatモデルで整形できます。ツール選択や書き込みを勝手に省略しません。

`/api/health` と各応答の詳細欄では、経路、モデル、ツール、同期鮮度、LLM/Embedding回数、Agentフォールバック、Project Continuityの参照件数、source refreshのattempted/failed/skippedを確認できます。`model_route`にはAIルーターの判断、提案ツール、実際に公開したツール、tool結果の伝達方式も含まれます。

## Web Push通知

Service Worker、Push API、VAPIDを使い、ブラウザを閉じている場合もPETITの通知を受け取れます。購読情報、カテゴリ別設定、通知イベント、端末ごとの配信結果はSQLiteへ保存します。

通知カテゴリはすべて初期OFFです。ヘッダーの通知設定から端末を購読し、必要な種類だけ有効にしてください。通知生成側は`dispatch_notification()`を呼び、配信先は`NotificationProvider`境界へ分離しているため、将来は同じ通知判断ロジックへAPNs Providerを追加できます。

VAPID未設定・依存未導入・通知無効時も既存チャットは動作します。設定、API、実iPhone PWA確認手順は[`docs/web_push_notifications.md`](docs/web_push_notifications.md)を参照してください。

## Calendar

Google CalendarのCodex/MCP接続はPETITプロセスへ自動共有されません。PETIT側で読むには`PETIT_CALENDAR_ICS_URLS`に非公開iCal URLを設定するか、`PETIT_CALENDAR_ICS_FILES`にエクスポート済み`.ics`を指定します。

同期結果はSQLiteの`sync_state`へソース別に保存し、取得失敗時は直前の正常キャッシュを維持します。TimeTreeは`TIMETREE_EMAIL` / `TIMETREE_PASSWORD` / `TIMETREE_CALENDAR_CODE`を設定した場合だけ読み取り専用ICSソースとして同期します。

`add_schedule`はICSやGoogle Calendar本体へは書かず、現在はPETITローカル予定だけへ追加します。

## 書き込み確認

Notionタスク作成・完了、ローカル予定追加、長期記憶、引き継ぎ、BRAIN修正、プロジェクト登録・別名追加・終了checkpoint保存、外部プロジェクト候補の紐付けは、ツール呼び出し時点では実行されません。

ブラウザに対象と変更内容、および「実行する / キャンセル」を表示し、`POST /api/actions/{approval_id}`で確認された操作だけを1回実行します。確認待ちは10分で期限切れになります。

BRAIN編集は設定済みVault内の既存`.md`だけに限定し、`_private`・除外フォルダ・Vault外パスを拒否します。

`PETIT_USE_SONA_CORE=1`では`add_schedule`だけがCoreのSQLite Approval Storeへ切り替わります。他の書き込みToolは従来の確認経路を維持します。

LM Studioが未起動でもサーバーは落ちず、UI上にエラーを表示します。

## Obsidian vault をPETITのMarkdown脳にする

既存のObsidian vaultを使う場合は`.env`などで`PETIT_OBSIDIAN_VAULT_DIRS`を指定します。PETITは`_private`・添付・内部設定を除くMarkdownを`petit_vault`としてChromaに索引化し、`search_memory`から会話記憶・要約・vaultノートを横断検索します。

PETITが自動追記するMarkdownは、既定では最初のvault内の`PETIT/Daily`と`PETIT/Memory`に置かれます。既存ノートは読み取り・検索対象、自動書き込みは`PETIT/`配下に限定します。

## 開発

- 主軸ブランチは`develop`。機能追加は`feat/<機能名>`。
- Project Continuity限定テスト:

  ```bash
  python -m unittest \
    tests.test_project_continuity \
    tests.test_project_router \
    tests.test_project_completion \
    tests.test_project_resume \
    tests.test_project_registration \
    tests.test_project_source_refresh \
    tests.test_notion_adapter_v2 \
    tests.test_linkraft_owner_sync \
    tests.test_github_evidence \
    tests.test_github_client_evidence \
    tests.test_github_evidence_routing
  ```

- Notion会話検索テスト: `python -m unittest tests.test_notion_search -v`
- Web Push通知テスト: `python -m unittest tests.test_notifications -v`
- 全Python構文確認: `python -m compileall backend tests`
- 変更のたびに`PROGRESS.md`へ追記する。
- ルール詳細は[`CLAUDE.md`](./CLAUDE.md)。
