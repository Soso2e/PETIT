# PROGRESS — 変更履歴

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。現状はFastAPI + ブラウザのテキストチャットMVPで、最終形はスマホとPCの音声中心常駐アシスタント。
- 音声: AivisSpeech Engineの`/audio_query`→`/synthesis`をFastAPI経由で呼び、WAV再生・中断・再読上げ・ブラウザTTS fallbackを実装。実AivisSpeechモデルとブラウザでのE2Eは未確認。
- モデル経路: Chat/AgentのURL・モデル・APIキーを独立設定できる。明示ツール・挨拶・時刻はルーター前に決定論処理し、曖昧な自然文だけChatルーターの提案を許可リストと登録済みツールで検証する。Agentは標準`role=tool`を優先し、Jinja非対応時だけuser follow-upへ退避、既定3ツールラウンド後に最終回答できる。実LM Studio 1／2モデル・標準tool／互換fallback・ブラウザE2Eは未確認。
- 会話記憶: 短期履歴、エピソード、長期記憶を分離。エピソード要約はAgent endpointを使い、朝ブリーフィングとproactive openerはエピソードを優先し旧summariesを移行用fallbackにした。実LM Studioでの確定・再起動後検索は未確認。
- セッション: SQLite会話をsession_idで取得し、ブラウザ再読み込み時に直近履歴を復元する。バックグラウンドjobはrequest/sessionへ紐付け、GETは読み取り専用、表示後のPOST ackで配信済みにする。実ブラウザ複数タブ／複数端末E2Eは未確認。
- SQLite: WAL、busy_timeout、会話session index、job delivery index、保存artifact用単一executorを追加。同時書き込みの実負荷試験は未実施。
- Notion Adapter v2: Project Relation、担当者、親子タスク、ブロックRelation、source更新時刻、候補確認、部分失敗を保持。成功したsource同期では取得されなくなったProject／Task cacheを削除し、loader失敗時は以前のcacheを維持する。実Notion v2 E2Eは未確認。
- Notion会話検索: 明示的なNotion参照をルーターLLM前に決定論的検出し、共有済みページを最大3件検索、プロパティ・本文抜粋・更新日時・URLを取得する。結果ありはAgent 1回、未設定・0件・API失敗はLLMなしで区別する。実Notion／ブラウザE2Eは未確認。
- タスク管理: area・確認済みproject Relationに加え、承認後のSQLite即時保存、`pending / synced / failed / conflict`、Notion書き込みキュー、指数バックオフ、手動再試行、タスク編集、競合スナップショットを実装。全回帰CI成功、実Notion／ブラウザE2Eは未確認。
- Linkraft Adapter: owner-only読み取りAPI、差分cursor、task/activity/support/knowledge cache、候補確認、stale fallbackを実装済み。実公開URL・token・owner user id E2Eは未確認。
- GitHub evidence Adapter: confirmation-firstでcommit／PR／check／deploymentを分離cacheし、確認済みrepositoryだけresume直前に同期する。private repository tokenの実E2Eは未確認。
- GitHub Daily Review: access可能な全repositoryを横断し、前回cursor以降のcommit／PR／checkと`PROGRESS.md`を朝ブリーフィング・明示会話でレビューする。CIは成功済み。実Fine-grained PAT／LM Studio／ブラウザE2Eは未確認。
- BRAIN / RAG: 実vault限定検索と確認付き安全編集を実装済み。`_private`・Vault外・Markdown以外は拒否。確認付きproject mappingを実装済み、実vault E2Eは#53で確認する。
- Calendar: ICSは読み取り専用、`add_schedule`はPETITローカル予定のみ。任意日付の予定確認を実装済み。Google private iCal実E2Eと将来のOAuth書き込みproviderは未対応。
- Project Continuity: 内部project台帳、alias、確認済みsource link、episode Relation、active state、checkpoint、handoff、cache-first resumeを統合済み。Phase 1/2 Issueは完了し、実外部サービスE2Eだけを#53で追跡する。
- Sona Agent Core: Feature Flag ON時の`add_schedule`をApproval／Idempotency／Audit付きAdapterへ接続済み。固定commit更新と実ブラウザE2Eが残る。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、`.env`は到達不能な `169.254.83.107` を参照しPETITは停止中。localhostへ修正して再起動する必要がある。
- 検証手順: `docs/CORE_HARDENING_VALIDATION.md` に、自動テスト → 1モデルE2E → 2モデルE2Eの順で固定した。
- 次にやること: Issue #60の実LM Studio／ブラウザE2Eと、Issue #62の実Fine-grained PATによる全repository朝レビューE2Eを確認する。その後Notion・AivisSpeech・タスク同期E2Eへ戻る。

## 履歴

変更を加えるたびに1行追記する（追記専用・既存行は触らない）。時刻は UTC。

| 日付 | 時間 | 回数 | 変更内容 |
|------|------|------|----------|
| 2026-06-25 | 08:47 | #1 | MVP 実装: FastAPI バックエンド（agent ループ + LM Studio クライアント + SQLite）、ツール（save/search_memory, get/add_task, get_schedule）、ブラウザ用チャット UI、CLAUDE.md / README / .gitignore を追加。`develop` ブランチを作成。 |
| 2026-06-25 | 09:05 | #2 | Notion 連携実装: notion_client.py（REST APIクライアント・ページパース・ページネーション対応）、tools/notion.py（sync_notion_tasks ツール + upsert）、get_tasks が Notion 設定時に自動同期、/api/health に Notion 設定状況を追加、.env.example 作成。`feat/notion` ブランチ。 |
| 2026-06-25 | 13:20 | #3 | RAG検索実装: chroma_client.py（ChromaDB永続化 + LM Studio embeddings カスタム関数 + graceful fallback）、search_memory がセマンティック検索→キーワード自動フォールバック、save_memory と会話ターンを Chroma に自動索引化、起動時に既存SQLiteデータをバックグラウンド同期、/api/health に RAG ステータス追加。`feat/rag` ブランチ。 |
| 2026-06-25 | 17:50 | #4 | Progress Log を1ファイルに整理: 詳細ログ `progress.md` を削除し、進捗記録を `PROGRESS.md`（表形式）に一本化。CLAUDE.md の Progress Log ルールとディレクトリ構成を更新。 |
| 2026-06-25 | 18:10 | #5 | PROGRESS.md に「現在の状態 / 未確認・TODO」セクション（上書き可）を追加し、履歴表（追記専用）と2部構成に。CLAUDE.md の作業開始/終了ルールを同期。 |
| 2026-06-25 | 18:30 | #6 | 自律的な会話蓄積を実装: N時間おきの自動要約 scheduler.py、summarizer.py、Obsidian形式の markdown_export.py、summaries テーブル、summarize_now ツール、/api/summarize・`/api/summaries`、search_memory の要約検索対応を追加。`claude/autonomous-conversation-md-db-tlyat4` ブランチ。 |
| 2026-06-25 | 18:28 | #7 | 「人間っぽく喋る」実装: recall.py で毎ターン関連記憶+直近要約を注入、proactive.py + `/api/proactive` で開いた瞬間の話しかけ、agent.py の相棒口調プロンプト、フロントの opener 表示を追加。`claude/autonomous-conversation-md-db-tlyat4` ブランチ。 |
| 2026-06-30 | 10:08 | #8 | Notion タスク作成/完了更新、引き継ぎメモ、中断復帰ツールを実装。一時DBでローカル fallback と復帰ツールの最小動作を確認。実 Notion E2E は未確認。 |
| 2026-07-05 | 07:43 | #8 | ローカル予定追加ツール `add_schedule` を実装。`calendar_events_cache` に予定を保存し、`get_schedule` で取得できることをテスト用DBで確認。README のツール一覧を更新。 |
| 2026-07-05 | 07:49 | #9 | 朝ブリーフィング実装: `briefing.py`、`/api/briefing`、`create_daily_briefing` ツールを追加。予定・未完了タスク・直近要約から「今やる1個」を含むブリーフィングを生成し、LM Studio 不通時は定型文へフォールバック。 |
| 2026-07-06 | 03:13 | #10 | ニュース/天気ツールと SQLite バックグラウンドキューを実装。ツール登録・構文・ワーカーモック・外部 API 疎通を確認、LM Studio 経由の意図選択は未確認。 |
| 2026-07-08 | 08:09 | #11 | PETIT 用ローカルLLM要件を調査・整理。コード変更なし、実モデル検証は未実施。 |
| 2026-07-08 | 07:47 | #12 | 朝の初回会話向け実装状況を確認。`create_daily_briefing` / `/api/briefing` は実装済み、天気統合・起床時刻記録・初回おはよう判定は未実装。 |
| 2026-07-08 | 08:29 | #13 | マージ後のコンフリクト解消結果を確認し、`backend/db.py` の構文破損、ツール import 重複、README / PROGRESS の重複記載を修正。構文・一時DBで最小動作を確認。 |
| 2026-07-09 | 18:18 | #14 | 会話ログからパーソナルデータを作る設計方針を確認。コード変更なし、SQLite/Chroma をAI用正本、Markdown を人間用副本、Notion は公開・手動編集用に分ける案を整理。 |
| 2026-07-09 | 18:22 | #15 | 既存 Obsidian vault を参照するRAG化方針を確認。コード変更なし、外部Markdownは読み込み用インデックス、会話由来の新情報はSQLite正本とMarkdown副本に追記する案を整理。 |
| 2026-07-09 | 18:23 | #16 | Markdown の脳みそは既存 Obsidian vault に統一する方針を確認。SQLite は構造化正本、Chroma は検索インデックス、Markdown は vault 内のPETIT領域へ集約する案に更新。 |
| 2026-07-09 | 18:34 | #17 | 既存 Obsidian vault をPETITのMarkdown脳として扱うRAG連携を実装。`vault_indexer`、`petit_vault`、`sync_obsidian_vault`、`/api/vault/sync`、vault配下Markdown出力設定を追加。一時vaultでキーワード検索を確認、実vault + embedding索引化は未確認。 |
| 2026-07-10 | 09:12 | #18 | 現在時刻取得の実装状況を確認。現状は `agent.py` で日付のみ注入、正確な現在時刻取得ツールは未実装。コード変更なし。 |
| 2026-07-10 | 09:14 | #19 | `get_current_time` ツールを追加し、現在時刻・日付を聞かれたら使うよう agent ルールと README を更新。構文・ツール登録・実行を確認。 |
| 2026-07-12 | 18:44 | #20 | NotionタスクDBの`.env`設定を更新し、完了日プロパティ`DoneDate`をコード・サンプル設定・READMEへ反映。実Notion E2Eは未確認。 |
| 2026-07-12 | 18:49 | #21 | プロジェクトルートの`.env`をPETIT起動時に自動読込する処理を追加。明示的なOS環境変数を優先。構文と設定読込のスモーク確認済み。 |
| 2026-07-11 | 19:31 | #22 | LM Studioの実エンドポイントを確認し、`.env` の `PETIT_LM_BASE_URL` に `/v1` を追加。モデル一覧取得と単純なチャット応答を確認済み。PETITブラウザ画面での再確認は未実施。 |
| 2026-07-12 | 05:50 | #23 | 専用アシスタント環境を再監査・再構築。BRAIN関連検索と自動注入、Notion状況同期/TTL、朝ブリーフィング、二モデルルーティング/受け渡し、Embedding障害時保護、連携状態可視化を実装。単体4件・実Notion読取・実vault検索を確認、Google Calendar本体同期と実LM会話は未確認。 |
| 2026-07-12 | 13:38 | #24 | PETIT_AS_JARVIS を最終像として明示し、スマホ利用とPC常駐を含む音声中心アシスタントへコンセプト表現を調整。 |
| 2026-07-12 | 13:56 | #25 | Google Calendar向けICS読み取り同期を実装。`sync_calendar`ツール、`/api/calendar/sync`、朝ブリーフィング/状況注入への同期、README/.env例、単体テストを追加。実Google iCal URLでのE2Eは未確認。 |
| 2026-07-12 | 17:09 | #26 | 軽量モデル即答 + `agent_followup` Job追記を実装。読み取り系の重い相談を遅延実行できるようにし、構文確認と標準 unittest 7件を確認。実LM Studio + ブラウザ体感は未確認。 |
| 2026-07-12 | 17:28 | #27 | LM StudioのJinjaテンプレート互換性対策として、tool実行結果を`role: tool`ではなくユーザーfollow-up形式で再投入するよう修正。構文確認と標準 unittest 8件は確認済み、実モデル完走はReadTimeoutで未確認。 |
| 2026-07-12 | 18:19 | #28 | 純粋な挨拶のLLM非依存即答と、会話保存後のChroma/Markdown反映のバックグラウンド化を実装。構文確認・標準unittest 9件・一時DBでの即答スモークを確認、ブラウザ体感は未確認。 |
| 2026-07-12 | 18:32 | #29 | BRAIN/vault同期のEmbedding重複対策を実装。同期開始時のダミー検索Embeddingを廃止し、チャンク `content_hash` 比較・変更分バッチUpsert・削除差分処理・Embedding統計/単調時計計測を追加。構文確認、標準unittest 12件、モック計測を確認。実LM Studio + ブラウザE2Eは未確認。 |
| 2026-07-12 | 18:45 | #30 | Git運用ルールを更新。Codexは検証済みの作業単位を原則随時コミットし、Pushは明示依頼時のみ行う方針を `AGENTS.md` に追記。 |
| 2026-07-12 | 19:01 | #31 | 会話処理を最小化。通常会話を会話モデル1回・直近5会話・短いsystem promptへ固定し、関連ツール限定、時刻の直接ルーティング、Embedding重複キャッシュ、軽量回答100トークン、遅延フォローアップ停止を実装。構文・標準テスト12件・モック計測を確認、実LM Studio + ブラウザE2Eは未確認。 |
| 2026-07-12 | 19:08 | #32 | `PETIT_LIGHT_MAX_TOKENS` の既定値を 512 に変更し、README の設定表も更新。設定反映のみで実動作は未確認。 |
| 2026-07-12 | 19:23 | #33 | 通常会話を9B/Thinking OFF/LLM 1回へ統一し、関連ツール限定の27B経路、空回答再試行、messages user検証、空回答保存抑止、request ID、healthキャッシュ、Embedding重複ロックを実装。標準テスト15件・compileall・diffチェックを確認、実LM Studio + ブラウザE2Eは未確認。 |
| 2026-07-12 | 20:11 | #34 | 動作確認済み: 意図別の限定取得、書き込み承認キュー、BRAIN安全編集、Calendar read/write分離、失敗保存抑止を実装。標準テスト30件と実ブラウザ+LM Studioで雑談/時刻/天気/Notion取得・作成・完了/BRAIN検索・追記/予定取得・追加をE2E確認。実Google ICSと別27Bモデルは未確認。 |
| 2026-07-14 | 00:00 | #35 | Notion/ICS/TimeTreeの同期状態をSQLiteへ永続化し、失敗時キャッシュ維持・stale表示・TimeTree読取アダプター・回帰テストを追加。実サービスE2Eは未確認。 |
| 2026-07-14 | 12:09 | #36 | 会話記憶を短期・エピソード・長期へ分離。エピソードSQLite/Markdown/Chroma差分索引、失敗時再試行、長期記憶の重複抑止と出典、ブラウザセッションID、回帰テストを追加。実ブラウザ＋実LM Studioでのエピソード確定・再起動後検索は未確認。 |
| 2026-07-14 | 13:41 | #37 | 2モデル分散・観測性を実装。Chat/Agentの独立endpoint設定と旧設定fallback、Agent停止時の安全なChat整形fallback、`/api/health`別モデル状態、ターン詳細表示・ログ、無効な長さ/遅延Agent設定削除、旧DB索引作成順を修正。標準unittest 43件・compileall・health構造スモークは確認、実LM Studio/ブラウザE2Eと計測は未実施。 |
| 2026-07-17 | 00:09 | #38 | Milestone 2の`get_schedule`縦切りを追加。固定commitのSona Agent Core依存、Feature Flag、PETIT Adapter、`personal` Scope・`schedule.read`検証、Source/Freshness、JSON Lines監査、旧経路互換テストを追加。標準unittest 49件・compileall確認済み。実ブラウザ/実CalendarのCore経路は未確認。 |
| 2026-07-17 | 03:09 | #39 | 動作確認済み: Milestone 2の予定取得Audit metadataへSource/Freshness・stale・最終同期日時・同期エラーを記録し、正常/stale両ケースと誤Primary Scope拒否（既存ハンドラー未呼出し）のテストを追加。依存導入、標準unittest 52件、compileall成功。 |
| 2026-07-17 | 04:29 | #40 | Milestone 3 PETIT Safe Writeを実装。`add_schedule`だけをFeature FlagでCoreのSQLite Approval/Idempotency/Auditへ接続し、既存書き込みをAdapterで一回実行。標準unittest 59件、compileall、依存導入、Flag OFF旧Approvalスモーク成功。実ブラウザはLM Studioタイムアウトで確認UI以降未確認、Core固定commit更新も公開後対応。 |
| 2026-07-16 | 18:38 | #40 | 動作確認済み: Milestone 2残りE2Eを完了。Core ON/OFFで同じ3件、`personal:soso` / `schedule.read` / JSONL Audit、外部ICS SourceReference、fresh/stale、失敗時キャッシュ保持と古さ表示を実ブラウザ+LM Studioで確認。失敗時の最終同期時刻保持と空モデル回答時の予定フォールバックを修正し、標準unittest 53件・compileall成功。Issue #6は対象外のまま維持。 |
| 2026-07-18 | 03:20 | #41 | Project Continuity Engine Phase 1をstacked PRで実装。SQLite project identity／alias／source link／episode Relation／active state／checkpoint、決定論的な開始・切替、終了確認と承認保存、限定resume context、確認付き新規登録・別名追加を追加。外部source linkの明示解除後再割当も実装。各専用GitHub Actions・compileall・unittest成功。実ブラウザE2Eとstack統合は未実施。 |
| 2026-07-18 | 03:27 | #42 | Phase 1のPR #18／#19／#20／#21／#23を順番にmainへ統合。内部project台帳、切替、終了確認、限定resume、確認付き登録・別名がmainで利用可能になり、最終branchとの差分0を確認。 |
| 2026-07-18 | 03:44 | #43 | Notion Adapter v2をPR #24でmainへ統合。Project／Task DBをRaw取得と個別parserへ分離し、Relation・担当者・親子タスク・ブロックRelation・source更新時刻・候補確認・部分失敗・source別freshnessを追加。専用／Project Continuity CI成功。 |
| 2026-07-18 | 05:24 | #44 | Linkraft側owner-only PETIT read APIとPETIT側Adapterを統合。Bearer token hash＋owner user id境界、project snapshot／delta cursor、task・activity・support・knowledge cache、idempotent project event、候補確認、stale fallbackを追加。PETIT側のtool import漏れを修正し、Notion／Linkraft／Project Continuity CI成功後にPR #25をmainへ統合。 |
| 2026-07-18 | 05:40 | #45 | 選択projectの確認済みactive sourceだけを再開直前に更新する`project_source_refresh`を実装。Notionはprovider単位で1回、Linkraftは対象external idだけをTTL／cursor付きで同期し、未確認・removed・別project・未対応providerを除外。失敗時もcheckpointと既存cacheで再開し、attempted／failed／skippedを観測可能にした。4系統CI成功。 |
| 2026-07-18 | 06:05 | #46 | GitHub evidence Adapterを実装。repository候補の確認付き紐付け、commit／PR／check／deploymentの分離cache、idempotent project events、per-repository cursor／TTL／stale fallback、token秘匿、resume直前refresh、明示的会話ルーティングを追加。check非同期完了とdeployment status後更新を再確認し、GitHub専用・Project Continuity・Notion・Linkraft・source refreshのテストを追加。 |
| 2026-07-18 | 17:03 | #47 | 調査完了: LM Studio未接続はSona Agent Core化ではなく、`169.254.83.107:1234`へのネットワーク経路不在が直接原因。稼働中PETITの正しいURL参照と`ConnectError`、正しい`/v1/models`への疎通失敗、該当Wi-Fi切断を確認。さらにディスク上`.env`のURLで`/`欠落を確認。設定・コード修正および復旧後E2Eは未実施。 |
| 2026-07-18 | 17:19 | #48 | 調査完了: 同一PCのLM Studio `127.0.0.1:1234/v1/models`は正常応答し、6モデルを確認。`.env`が到達不能な`169.254.83.107`を参照し、PETITプロセスは停止中。直接原因を設定先の不一致に確定。localhostへの変更・再起動・ブラウザE2Eは未実施。 |
| 2026-07-18 | 18:09 | #49 | Core hardeningを実装。model_routerを実経路へ接続、エピソード要約のAgent endpoint修正、briefing/proactiveのepisode優先、Notion成功同期のsource置換、SQLite WAL/busy timeout、session履歴復元、jobのsession/request紐付けと明示ack、回帰テスト・検証手順を追加。変更ファイルのpy_compileとfrontendのnode構文確認成功、全CIと実ブラウザE2Eは未確認。 |
| 2026-07-21 | 11:43 | #50 | Issue #49対応として`AGENTS.md`を整理。PETIT固有の概要・技術構成・安全境界・Progress Logを維持し、調査・Issue・テスト・PR・禁止事項を追加、Git運用を`main` + 専用ブランチ + PRへ統一。文書差分のみでコードテストは未実施。 |
| 2026-07-21 | 12:14 | #51 | Issue #6の予定日付解析を実会話経路へ接続。今日・明日・昨日、ISO、日本語年月日、月日を解釈し、不正・曖昧日付は確認要求、Legacy/Coreで同一日付、モデル停止時の簡易予定表示、専用回帰テストとCI対象追加を実装。全CI成功後にPR #52をmainへ統合、実ブラウザE2Eは未実施。 |
| 2026-07-21 | 13:05 | #52 | Issue #40 Phase 2を実装。承認後のSQLite即時保存、Notion非同期create/update、pending/synced/failed/conflict、指数バックオフ、手動再試行、タスク編集、競合保護、Worker配線、Agent経路、専用テストと設計文書を追加。全6系統CI成功、実Notion／ブラウザE2Eは未実施。 |
| 2026-07-21 | 14:18 | #53 | Issue #56でAivisSpeech Engine TTSを実装。FastAPIの`/api/tts`・状態確認、話者自動選択、話速・感情・音量設定、WAV再生・中断・ブラウザTTS fallback、専用テスト5件とCIを追加。ローカルのunittest・compileall・node構文確認成功、実Engine／ブラウザE2Eは未確認。 |
| 2026-07-21 | 19:40 | #54 | Issue #58対応として読み取り専用`search_notion`、明示Notion参照の決定論ルーティング、上位3ページのプロパティ・本文抜粋取得、0件／未設定／API失敗の分離、モデル停止時の事実一覧fallback、回帰テスト・CI・README・設計文書を追加。構文確認済み、CIと実Notion／ブラウザE2Eは未確認。 |
| 2026-07-22 | 01:35 | #55 | Issue #60対応として決定論的経路をAIルーター前へ移動し、ルーター提案ツールの許可・登録検証、Chat/Agent prompt分離、標準tool messageとJinja互換fallback、最大3ツールラウンド＋最終回答、重複呼び出し防止、観測情報、回帰テスト・設定例・設計文書を追加。構文・簡易ハーネス確認済み、CIと実LM Studio／ブラウザE2Eは未確認。 |
| 2026-07-22 | 11:35 | #56 | Issue #62対応として全GitHub repositoryの朝差分レビューを実装。global cursor、archived／empty／fork除外、commit／PR／check、`PROGRESS.md`参照、部分失敗時cursor維持、LM Studio fallback、朝briefing、決定論会話routing、scheduler、設定・テスト・文書を追加。全6系統CI成功、実Fine-grained PAT／LM Studio／ブラウザE2Eは未確認。 |
