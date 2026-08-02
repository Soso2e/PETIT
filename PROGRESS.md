# PROGRESS — 変更履歴

**Current Version: v0.1.0**  
**Last Updated: 2026-08-02**

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。現状はFastAPI + ブラウザのテキストチャットMVPで、最終形はスマホとPCの音声中心常駐アシスタント。
- バージョン管理: v0.1.0。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する運用を開始。
- 会話 / Agent Runtime: Project Continuity・挨拶・正確な現在時刻だけを決定論的な安全ゲートで処理し、通常会話はChatモデルのCapability Routerが最大4領域を選ぶ。Agentには選択領域内の登録済みToolだけを公開し、既定3ラウンド・Tool総数6・同一Tool同一引数1回の上限、結果圧縮、書き込み承認、30分以内のAgent状態再開、履歴へ残さない進捗表示を実装。Toolが必要な依頼への「確認します／調べます」だけの最終回答を再実行へ戻すガードと、保存済みプロジェクト状況を読む`get_project_status`を追加。関連43テストと稼働中APIへのTool登録は確認済み、実DeepSeek会話での結果返答・承認後返答・iPhone進捗表示E2Eは未確認。
- モデル切替: WebからChat／Agentを個別にローカルLM Studio・DeepSeek V4 Flash・DeepSeek V4 Proへ切替でき、選択だけをローカル保存する。DeepSeek APIキーはブラウザや保存ファイルへ返さず、Embeddingはローカルのまま。専用テスト5件成功、実DeepSeek／ブラウザE2Eは未確認。
- 音声: AivisSpeech Engineの`/audio_query`→`/synthesis`をFastAPI経由で呼び、WAV再生・中断・再読上げ・ブラウザTTS fallback、一時的な429／502／503／504の1回再試行、合成直列化、上流エラー詳細診断、モバイル音声アンロック、文単位チャンク生成・先読み再生・5秒タイムアウト・生成キャンセル、独立診断CLI、2回連続失敗後の60秒回路遮断を実装。Windows初期セットアップ、音声モデル、Engine、`.env`、診断CLI、WAV確認、Docker／WSL差の手順書とREADME導線も追加。実AivisSpeechモデルとPC／スマホブラウザE2Eは未確認。
- 汎用リスト: 組み込みタスクと任意のカスタムリストを保存先付きで取得し、ローカルSQLiteへリスト作成・項目取得・項目追加できる。`lists_and_tasks` Capability内でタスクとリストを文脈・対象存在・Tool結果から区別し、書き込みは確認必須、存在しないリストをタスクへ誤変換せず、Notion DBも自動生成しない。関連CI成功、実LM Studio／ブラウザ会話E2Eは未確認。
- 会話記憶: 短期履歴、エピソード、長期記憶を分離。エピソード要約はAgent endpointを使い、朝ブリーフィングとproactive openerはエピソードを優先し旧summariesを移行用fallbackにした。実LM Studioでの確定・再起動後検索は未確認。
- 日次生活インデックス: 全`session_id`の会話をAsia/Tokyo基準で1日1回まとめ、空・記号のみ・連続重複だけを除外してローカルLM Studioへ送る。雑談の外出・食事・人・場所・感情・制作等をSQLite／Memory／Chroma／Markdownへ保存し、長期記憶候補は自動昇格しない。専用CIと実ローカルLLM E2Eは未確認。
- セッション: SQLite会話をsession_idで取得し、ブラウザ再読み込み時に直近履歴を復元する。バックグラウンドjobはrequest/sessionへ紐付け、GETは読み取り専用、表示後のPOST ackで配信済みにする。実ブラウザ複数タブ／複数端末E2Eは未確認。
- 制作伴走Web UI: 作業モード、経過時間、一時停止・終了、10分／20分ごとの前景限定自律声かけ、Highタスク・次の予定・次の一手、直近3ラリー表示、2時間アイドルでのセッション分離、途中経過メッセージ、PWAを実装。作業状態をサーバーSQLiteにも保存し、20分ごとの継続確認、`まだ続けてる`／チャット返答、さらに20分無応答時の自動停止、40分超の旧localStorage状態停止を追加。スマホ向け画面崩れ・重複IDを修正し、縦積み、44px以上の主要操作、16px入力、下部ナビを390×844のブラウザで4画面確認済み。関連20テストと構文確認は成功、実iPhoneホーム画面／AivisSpeech／Push E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in設定、SQLiteの通知イベント・配信履歴、Web Push Provider境界、設定UI、テスト通知を実装。端末でPushを明示的に有効化すると作業セッション通知もONにし、後から個別OFFにできる。Push失敗時も作業停止判定は継続する。関連24テストとJavaScript構文確認は成功、実VAPID／HTTPSブラウザ／バックグラウンド受信／通知タップ／実iPhone PWA E2Eは未確認。
- SQLite: WAL、busy_timeout、会話session index、job delivery index、保存artifact用単一executorを追加。同時書き込みの実負荷試験は未実施。
- Notion Adapter v2: Project Relation、担当者、親子タスク、ブロックRelation、source更新時刻、候補確認、部分失敗を保持。成功したsource同期では取得されなくなったProject／Task cacheを削除し、loader失敗時は以前のcacheを維持する。実Notion v2 E2Eは未確認。
- Notion会話検索: `knowledge` Capability内の読み取りToolとして共有済みページを最大3件検索し、プロパティ・本文抜粋・更新日時・URLを圧縮してAgentへ戻す。未設定・0件・API失敗を区別する。関連CI成功、実Notion／LM Studio／ブラウザE2Eは未確認。
- タスク管理: Notionを人間向け外部正本、SQLiteをPETITの即時統合ビューとして扱う。PETIT→Notionは既存Outbox、Notion→PETITは署名検証Webhook Inbox、5分差分同期、日次全件補修で同期し、フィールド単位三者マージと論理削除でpending/failed/conflictを保護する。通常の`get_tasks`はSQLiteだけを読み、既定でHighのみ、暇・やりたいこと候補はMid/Medium＋Low、全件要求時だけ未設定を含む全優先度を返す。作成既定High・日付未指定は期限なし。名前つき完了報告はProject完了やAgentより先にSQLiteで一意／複数／完了済み／0件へ決定論的に解決し、一意候補だけ確認付き`complete_task`へ進める。関連28テストと一時DBのAPI縦切りは成功、実ブラウザの確認操作と実Notion同期E2Eは未確認。
- Linkraft Adapter: owner-only読み取りAPI、差分cursor、task/activity/support/knowledge cache、候補確認、stale fallbackを実装済み。実公開URL・token・owner user id E2Eは未確認。
- GitHub evidence Adapter: confirmation-firstでcommit／PR／check／deploymentを分離cacheし、確認済みrepositoryだけresume直前に同期する。private repository tokenの実E2Eは未確認。
- GitHub Daily Review: access可能な全repositoryを横断し、前回cursor以降のcommit／PR／checkと`PROGRESS.md`を朝ブリーフィング・明示会話でレビューする。CIは成功済み。実Fine-grained PAT／LM Studio／ブラウザE2Eは未確認。
- BRAIN / RAG: 実vault限定検索と確認付き安全編集を実装済み。`_private`・Vault外・Markdown以外は拒否。確認付きproject mappingを実装済み、実vault E2Eは#53で確認する。
- Calendar: ICSは読み取り専用、`add_schedule`はPETITローカル予定のみ。任意日付の予定確認を実装済み。Google private iCal実E2Eと将来のOAuth書き込みproviderは未対応。
- Project Continuity: 内部project台帳、alias、確認済みsource link、episode Relation、active state、checkpoint、handoff、cache-first resumeを統合済み。Phase 1/2 Issueは完了し、実外部サービスE2Eだけを#53で追跡する。
- Sona Agent Core: Feature Flag ON時の`add_schedule`をApproval／Idempotency／Audit付きAdapterへ接続済み。固定commit更新と実ブラウザE2Eが残る。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、`.env`は到達不能な `169.254.83.107` を参照しPETITは停止中。localhostへ修正して再起動する必要がある。
- 検証手順: `docs/CORE_HARDENING_VALIDATION.md` に、自動テスト → 1モデルE2E → 2モデルE2Eの順で固定した。AivisSpeechは`docs/AIVIS_SPEECH_SETUP.md`と診断CLIで段階的に切り分ける。
- 次にやること: 新機能追加より実環境E2Eを優先する。まずLM Studioの`.env`をlocalhostへ直してPETITを起動し、文脈駆動Agent Runtimeと汎用リストの実会話を確認する。次にAivisSpeech診断CLI→PC／iPhone音声、Issue #92のVAPID／HTTPS／通知、Issue #75のNotion Webhook、Issue #53のProject Continuity外部sourceを順に検証する。

## 履歴

変更を加えるたびに1行追記する（追記専用・既存行は触らない）。時刻は UTC。

| 日付 | 時間 | 回数 | 変更内容 |
|------|------|------|----------|
| 2026-08-02 | 08:54 | #1 | v0.1.0としてバージョン管理ルール、PROGRESS表記、Web UI表示を追加 |
