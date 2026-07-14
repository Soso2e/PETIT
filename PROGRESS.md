# PROGRESS — 変更履歴

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書きしてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。最終形はスマホとPCの両方から使える音声中心の常駐アシスタントで、現状はテキストチャットMVPを土台にしている。
- TimeTree バックアップ: `tools/timetree_backup.py` 実装済みだが本番 E2E 未検証（実認証情報待ち）。カレンダーコード確認は初回だけ対話実行が必要（`timetree-exporter -e your@email.com`）。
- Notion: 実タスクDBの未完了取得、確認画面を経由した作成・完了更新を実ブラウザ + LM StudioでE2E確認済み。Notion失敗時はローカルへ代替保存しない。
- BRAIN / RAG: 実vaultの限定検索と、対象ファイル・追記内容の確認後に既存Markdownへ追記するE2Eを確認済み。`_private`・除外フォルダ・Vault外・Markdown以外は編集拒否し、変更後は該当ノートを再索引化する。
- 能動支援: 「今日何からやる？」では未完了タスク・当日予定・BRAIN候補だけをPython側で限定取得し、LM Studio 1回で整理する。雑談ではツール・RAG・Embeddingを動かさない。
- 書き込み確認: Notion、ローカル予定、長期記憶、引き継ぎ、BRAINの書き込みツールは10分有効のプレビューへ変換し、ブラウザの「実行する」確認後に同一引数を1回だけ実行する。
- 二モデル構成: Chat/AgentのURL・モデル・APIキーを独立設定でき、未設定時は従来の`PETIT_LM_*`へフォールバックする。ルーティングは意図・関連ソースに基づき、長さだけではAgentへ送らない。安全に取得済みの読み取り結果だけはAgent停止時にChatで整形でき、ツール選択・書き込みは省略せず利用不能として返す。実別PC/別GPU動作は未確認。
- 応答速度改善: 通常会話は9B用の`CHAT_MODEL`・短いsystem prompt・直近5会話・LM Studio 1回に固定し、ツール・RAG・Embeddingを実行しない。空回答、LM Studio/内部エラー、ツール失敗はSQLite・Markdown・Embeddingへ保存しない。実ブラウザで雑談・時刻・天気・各連携の応答を確認済み。
- 軽量回答上限: `PETIT_LIGHT_MAX_TOKENS` を 512 に変更済み。`PETIT_ENABLE_THINKING=0` と `.env.example` に反映済み。実LM Studio応答のreasoning tokens 0は未確認。
- Calendar: ICSは読み取り専用同期、`add_schedule`はPETITローカル予定への書き込みとして分離。ローカル予定の確認付き追加・再取得は実ブラウザE2E済み。実Google非公開iCal URLは未設定のため同期E2E未確認。将来のGoogle書き込みはprovider境界へ追加する。
- 観測性: `/api/health` はChat/Agent別のキャッシュ付き`/models`確認（接続先、モデル、loaded、遅延、Agentフォールバック可否）を返す。各ターンはrequest ID、実経路、モデル／endpoint ID、ツール、LLM回数、同期状態、参照件数、フォールバック、時間をログ・折りたたみ詳細へ出す。実ブラウザ表示は未確認。
- LM Studio: 現在の実行環境ではChat/Agentの`/models`到達を確認できず、実モデル総合E2E・1/2モデル時間比較は未実施。単体テストで接続先分離とAgent→Chat読み取りフォールバックを確認済み。
- 外部同期信頼性: Notion/ICS/TimeTreeの成功・失敗・stale状態をSQLite `sync_state` に保存する実装済み。自動テスト済み、実認証情報を使うNotion/Google/TimeTree E2Eは未確認。
- 会話記憶: 短期（ブラウザセッション履歴）、エピソード（SQLite `conversation_episodes` / `petit_episodes`）、長期（SQLite `memory`）を分離。エピソードは20分のアイドル、8往復、明示まとめ、定期実行で確定する。単体テスト済み、実ブラウザ＋実LM Studioでのエピソード確定・再起動後検索は未確認。
- 索引: SQLite記憶/エピソードは`content_hash`・Embeddingモデル/版・Chromaメタデータで差分だけを再索引化する。Vault差分索引は維持。起動時の実LM Studio件数は未測定。
- 次にやること: LM Studioを起動して1モデル（Chat/Agent同一9B）と2モデル（別endpoint）で、READMEの意図別チャット・承認・同期・記憶・再起動ケースを実ブラウザ確認する。Agent停止／復旧、stale表示、起動前後Embedding件数、各経路の応答時間を記録する。

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
| 2026-07-12 | 18:19 | #28 | 純粋な挨拶のLLM非依存即答と、会話保存後のChroma/Markdown反映のバックグラウンド化を実装。構文確認・標準 unittest 9件・一時DBでの即答スモークを確認、ブラウザ体感は未確認。 |
| 2026-07-12 | 18:32 | #29 | BRAIN/vault同期のEmbedding重複対策を実装。同期開始時のダミー検索Embeddingを廃止し、チャンク `content_hash` 比較・変更分バッチUpsert・削除差分処理・Embedding統計/単調時計計測を追加。構文確認、標準 unittest 12件、モック計測を確認。実LM Studio + ブラウザ体感は未確認。 |
| 2026-07-12 | 18:45 | #30 | Git運用ルールを更新。Codexは検証済みの作業単位を原則随時コミットし、Pushは明示依頼時のみ行う方針を `AGENTS.md` に追記。 |
| 2026-07-12 | 19:01 | #31 | 会話処理を最小化。通常会話を会話モデル1回・直近5会話・短いsystem promptへ固定し、関連ツール限定、時刻の直接ルーティング、Embedding重複キャッシュ、軽量回答100トークン、遅延フォローアップ停止を実装。構文・標準テスト12件・モック計測を確認、実ブラウザE2Eは未確認。 |
| 2026-07-12 | 19:08 | #32 | `PETIT_LIGHT_MAX_TOKENS` の既定値を 512 に変更し、README の設定表も更新。設定反映のみで実動作は未確認。 |
| 2026-07-12 | 19:23 | #33 | 通常会話を9B/Thinking OFF/LLM 1回へ統一し、関連ツール限定の27B経路、空回答再試行、messages user検証、空回答保存抑止、request ID、healthキャッシュ、Embedding重複ロックを実装。標準テスト15件・compileall・diffチェックを確認、実LM Studio + ブラウザE2Eは未確認。 |
| 2026-07-12 | 20:11 | #34 | 動作確認済み: 意図別の限定取得、書き込み承認キュー、BRAIN安全編集、Calendar read/write分離、失敗保存抑止を実装。標準テスト30件と実ブラウザ+LM Studioで雑談/時刻/天気/Notion取得・作成・完了/BRAIN検索・追記/予定取得・追加をE2E確認。実Google ICSと別27Bモデルは未確認。 |

| 2026-07-14 | 00:00 | #35 | Notion/ICS/TimeTreeの同期状態をSQLiteへ永続化し、失敗時キャッシュ維持・stale表示・TimeTree読取アダプター・回帰テストを追加。実サービスE2Eは未確認。 |
| 2026-07-14 | 12:09 | #36 | 会話記憶を短期・エピソード・長期へ分離。エピソードSQLite/Markdown/Chroma差分索引、失敗時再試行、長期記憶の重複抑止と出典、ブラウザセッションID、回帰テストを追加。実ブラウザ＋実LM StudioのエピソードE2Eは未確認。 |
| 2026-07-14 | 13:41 | #37 | 2モデル分散・観測性を実装。Chat/Agentの独立endpoint設定と旧設定fallback、Agent停止時の安全なChat整形fallback、`/api/health`別モデル状態、ターン詳細表示・ログ、無効な長さ/遅延Agent設定削除、旧DB索引作成順を修正。標準unittest 43件・compileall・health構造スモークは確認、実LM Studio/ブラウザE2Eと計測は未実施。 |
