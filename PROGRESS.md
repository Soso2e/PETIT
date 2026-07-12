# PROGRESS — 変更履歴

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書きしてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。最終形はスマホとPCの両方から使える音声中心の常駐アシスタントで、現状はテキストチャットMVPを土台にしている。
- TimeTree バックアップ: `tools/timetree_backup.py` 実装済みだが本番 E2E 未検証（実認証情報待ち）。カレンダーコード確認は初回だけ対話実行が必要（`timetree-exporter -e your@email.com`）。
- Notion: PETIT本体から実タスクDB 124件の読み取りとSQLite同期を確認済み。計画系会話と朝ブリーフィングは読み取り同期を通り、5分TTLで再利用する。作成・完了更新の実Notion書き込みE2Eは未確認。
- BRAIN / RAG: 実vault 290チャンクを確認。Embedding停止時でも自然な日本語質問から関連ノートを順位付き検索して会話へ少数件注入できる。`_private`・添付・内部設定は索引対象外。実Embedding検索はLM Studio停止中のため未確認。
- 能動支援: 予定・優先順位・期限などの相談でNotionタスクと予定キャッシュを自動収集し、朝のopenerはブリーフィングを返す。外部サービスへの書き込みは明示確認後のみ。
- 二モデル構成: 会話モデルとエージェントモデルのルーター、長文・ツール・複雑処理の判定、エージェント回答を会話モデルで整える受け渡しを実装。現在の`.env`では両方とも `qwen/qwen3.5-9b` へフォールバックしており、別モデルでの実動作は未確認。
- 応答速度改善: 純粋な挨拶（例: `PETITこんばんわ`）はLLMを呼ばずアプリ側で即答する。雑談系チャットではBRAIN検索を行わない。BRAIN/vault同期はダミー検索Embeddingと未変更チャンク再Embeddingを廃止し、`content_hash` 比較で変更チャンクのみバッチUpsertする。会話保存後のChroma/Markdown反映はレスポンス後のバックグラウンド処理へ分離済み。構文・標準テスト・差分同期モック計測は確認済み、実LM Studio + ブラウザでの体感確認は未確認。
- Google Calendar: Codex側コネクタの認証はPETITへ共有されないため、PETIT側は `PETIT_CALENDAR_ICS_URLS` / `PETIT_CALENDAR_ICS_FILES` からICSを読み取る同期アダプターを実装済み。サンプルICSで単体確認済み、実Google非公開iCal URLでの同期E2Eは未確認。
- LM Studio: `/v1/models` は到達可能でモデル一覧を取得できる。tool実行後の再問い合わせは、LM Studioの一部Jinjaテンプレートで `role: tool` を処理できないため、ツール結果をユーザーfollow-upとして返す互換形式へ変更済み。構文と単体テスト8件は確認済み。実モデルでの「調べて」系最小実行はReadTimeoutで完走未確認、ブラウザ会話E2Eも未確認。
- 次にやること: LM Studio側で会話モデル/エージェントモデルの応答速度とロード状態を確認 → PETITを再起動してブラウザ会話E2E → Google Calendarの非公開iCal URLまたはエクスポートICSを設定して `/api/calendar/sync` E2E → 週次レビュー／停滞プロジェクト検出を追加。

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
