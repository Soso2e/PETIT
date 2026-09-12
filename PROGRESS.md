# PROGRESS — 変更履歴

**Current Version: v0.21.0**

**Last Updated: 2026-09-12**

## 現在の状態 / 未確認・TODO（最新を上書き）

- Issue #270 Step 3: Desktop openWakeWordのinstaller配布経路を実装。WakeモデルはGit管理外のまま、build時にローカル`storage/wakeword/models/v0.1/hey_petit.onnx`または`PETIT_WAKE_MODEL_URL` + `PETIT_WAKE_MODEL_SHA256`から注入し、HTTPS・SHA-256検証、`wake-model.json` manifest同梱、packaged resources検証を行う。GitHub Actions Run #76でmacOS arm64 DMG / Windows x64 EXEを実生成し、Smoke・packaged Wake resources検証とも成功。PR #272はDraft継続。未完了は、実モデルを配布元へ置いたモデル同梱build、インストール版の自動設定→diagnostic、実マイクWake `ready`、実声「Hey プティ」検出と誤起動評価。

- Issue #270 Step 2: Desktop設定にopenWakeWordの「ウェイク環境を自動設定」を追加。Python 3検出→専用venv作成→依存導入→openWakeWord v0.5.1 backbone取得→既存/生成済み`hey_petit.onnx`を管理領域へコピー→マイクを開かないdiagnosticまで一括実行し、managed Python/runtime/model/backboneパスを設定へ保存する。中止・進捗表示・回帰テスト・Python runtime構文チェックを追加。Desktop CIでnpm test・Syntax checks成功。packaged EXE/DMGへのWakeモデル同梱と実マイク`ready`確認はStep 3で行う。

- Issue #270 Step 1: Desktop Wake設定をopenWakeWordへ一本化。旧Picovoice/Porcupine AccessKey・PPN・自動生成IPC・暗号化キー保存を撤去し、旧設定を読み込んだ場合も秘密情報と旧モデルmetadataを自動除去する。WakeはONNX分類モデル＋melspectrogram/embedding backbone＋Python runtimeのみを使用。Desktop CIでnpm test・Syntax checks成功。

- Issue #260追加: Three.js Univに天体の登場・選択拡大・発光パルスを実装。実WebGL fixtureで登場・選択・連続選択・reduced motion・描画停止を確認し、関連13テスト成功。大量実データ・実iPhone/macOS性能は未確認。詳細は `docs/universe-motion.md`。

- Issue #260: Web（Universe / Legacy）とDesktop小型会話に共通のメッセージ出現・押下・入力フォーカス・パネル表示アニメーション、Desktop設定の表示・操作反応と録音中の軌道表現を追加。Edgeの1280px / 390px幅と実Electronのfixture smokeで表示・操作・reduced-motionを確認済み。既存PWAからの更新、実iPhone / macOS、配布済みDesktopへの反映は未確認。設定画面CSSの配布にはDesktop更新が必要。

- Issue #255: 現行WebチャットのDOMと音声初期化の不一致を修正。録音→Whisper互換STT、入力方式選択、HTTPS・Mac権限・サービス設定の案内、失敗時の下書き復元を追加。実マイク・実STT・Safari・PWA更新受け入れは未確認。

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- Proactive openerの古い全体エピソード参照を停止し、同一sessionのユーザー発話と現在の作業だけを候補に変更。誤ったepisode_id=2（「全10件のタスクがキャンセル済み」）をSQLite/Chromaから削除し、DBバックアップを保存。関連テスト成功、実アプリ起動・実LLM表示は未確認。

- Issue #258: `scripts/wakeword/` にWindows/Python 3.13の独立したopenWakeWord学習環境を追加。日本語SAPI合成624クリップを話者分離して学習し、`storage/wakeword/models/v0.1/hey_petit.onnx` を生成済み。ONNX構造・出力一致・openWakeWord実推論・関連2テスト・依存整合・構文を確認。しきい値0.45でtest正例12/12検出、負例11/144誤検出。合成音声のみの実験モデルで、常時待機の実用精度は未達。実声・長時間負例・実マイク評価とDesktop統合が次の作業。詳細は `docs/openwakeword.md`。Desktop実行経路はopenWakeWordへ移行済み。

- Issue #253: Windows/macOS向けElectron Desktopの初期実装。既存Webの会話・確認・TTSを共有する小型UI、トレイ・ショートカット、openWakeWordウェイク、Whisper互換STT、GitHub Releases更新通知を追加。macOSの実Electronと生成音声の操作テスト済み。実マイク/モデル/LLM/TTS、Windows実機、署名・公証・実更新は未確認。iPhoneはPWAを継続。Desktop配布はPR=テストのみ、手動Actions=macOS arm64/Windows x64開発Artifact、main上のversion一致`v*`タグ=両OSビルド＋GitHub Release自動添付へ整理。未署名中は手動Artifactで検証し、公開タグは切らない。

- Issue #249 / #245: Web中心のJARVIS設計を `docs/jarvis-agent.md` に整理。BrokerへMemory/BRAIN/Work/Reminders/Handoff、待ち時間・同時実行・Context量の上限、2回目Brainへの状況継続を追加。PC観測は既定無効の任意Module。作業ブランチで関連58テスト・Python構文・diff確認済み。実LLM・外部サービス・PWA E2E、Conversation State統合、永続提案・自律実行は未完了。

- プロダクトの軸は `PETIT_AS_JARVIS`。FastAPIとPWAを基盤に、タスク・予定・会話・知識・開発状況を継続支援する個人用アシスタントとして開発中。
- バージョン管理: v0.17.0。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する。
- Univ UI 刷新: 大きなカード矩形を全廃し、Core＝中心惑星、親タスク＝惑星、子タスク＝衛星、関係性＝軌道・接続線からなる天体UIへ根本刷新。詳細情報は天体選択時に右側詳細パネルで確認・操作する。
- Univ描画: WebGL依存を追加せず、CSS 3D・radial-gradient・既存SVG接続線で軽量な球体表現を実装。レイヤーは前面HUD、選択対象の説明、惑星・衛星、接続線、背景の順で固定する。
- Issue #215対応: Univ表示時だけページを固定し、100dvhとsafe-area内のThree.js viewportへ切り替える。WebGL成功時はCSS宇宙背景を隠し、Canvasを単一の背景描画面として扱う。星の初回クリックでカメラFocusとHUD選択を同期し、2回目で詳細を開く（PC・390x844ブラウザ確認済み、実iPhone未確認）。
- バージョン管理: v0.18.1。Univの常時WebGL描画を必要時描画へ変更し、PWA全体のメインスレッド負荷を軽減。
- バージョン管理: v0.18.2。四隅型App Shellで非表示になった旧左レールの予約幅を解除し、デスクトップUnivを全幅表示へ復旧。
- バージョン管理: v0.18.3。FastAPIのstartup/shutdownとChroma初期同期を `backend/lifecycle.py` へ分離し、`main.py` はlifecycle登録のみを担当。
- バージョン管理: v0.18.4。Pending Actionの状態管理・確認API・Sona Core分岐・Tool dispatchを `backend/pending_actions.py` へ分離し、Chat/確認APIモデルを `backend/chat_models.py` へ共通化。
- バージョン管理: v0.18.5。`POST /api/chat`、Agent実行、observability、会話保存・artifact保存を `backend/chat.py` へ分離し、`main.py` はChat Router登録のみを担当。iOS Vocal ShortcutもChat moduleへ直接接続。
- バージョン管理: v0.18.6。Issue #227 Phase 2を完了。補助API群とStatic Frontend配線まで `main.py` から分離し、`main.py` はFastAPI生成・Router登録・lifecycle/frontend登録・起動のみを担当するComposition Rootになった。
- バージョン管理: v0.19.0。Issue #227 Phase 3を開始。`ModuleDefinition` / `ModuleRegistry` と `create_app()` を追加し、Router・registrar・依存関係を明示的に組み立てる土台へ移行。`main.py` は `create_app()` を呼ぶ起動shimへ縮小。
- バージョン管理: v0.19.1。Issue #227 Phase 3を完了。`backend.tools` のimport副作用登録を廃止し、built-in Tool catalogを `builtin-tools` Moduleとして明示登録。Chat / Pending ActionはTool bootstrapへの依存を宣言し、Module Registryが起動順を保証する。
- Univ UI 刷新: 大きなカード矩形UIを全廃し、Core＝中心惑星、親タスク＝惑星、子タスク＝衛星、関係性＝軌道・接続線からなる天体UIへ根本刷新。詳細情報は天体選択時に右側詳細パネルで確認・操作する。
- Univ描画: Three.js WebGLを主描画としてCore・親Task・子Task・接続線・星背景を描画し、DOMはラベル・HUD・詳細・操作UIに限定。WebGL利用不可時のみ既存CSS 3D表示へフォールバックする。
- Univ表示領域: Univ表示中はページスクロールを止め、Canvasを100dvhの固定空間として表示。WebGL準備後は外側のCSS宇宙背景を無効化し、スマホHUDはsafe-areaと下部ナビを避ける。
- Univ Focus: 親タスク惑星または子タスク衛星を選ぶと、同じUniv内でカメラが対象系へ寄り、所属する衛星を見やすくする。他の惑星と接続線は暗くし、旧Focusパネルへ自動遷移しない。
- Front UI: 左上に現在領域・同期状態・バージョン、右上にUniv／Tasks／PETITの3アイコン、左下にReminders／Settingsを置く四隅型App Shellへ更新。スマホでは主要タブをアイコンだけにし、safe-areaを考慮する。
- 補助導線: Settingsから詳細設定を備えた旧UIへ直接移動できる。旧UIは廃止せず、移行中の保険・全機能への導線として残す。
- ナビゲーション: 対象パネルの`hidden`・ARIA・active状態を直接同期する。`home`、`focus`、`universe`、`projects`の旧URL／内部呼び出しはUnivへ互換転送する。
- モーション: View間は既存の短いフェードを維持し、Univ内部だけCSS 3Dカメラを利用する。`prefers-reduced-motion`では空間アニメーションとパネル遷移を停止する。
- 制作伴走 / Today: 作業セッションをNotion Task DBの変更なしでPETIT内部Task IDへ紐づけ、状態遷移イベントをSQLiteへ永続化する。20分ごとの継続確認と無応答時の自動停止、タスク別・プロジェクト別・直近1〜90日集計、チャットからの開始・一時停止・再開・終了・実績参照に対応。Today機能自体は残し、トップレベルタブからは外す。
- Issue #223対応: active / paused Work Sessionを通常会話の小さい状況文脈へ追加し、Tool routeを増やさず脱線後も現在作業を認識可能にする。proactive openerは古いproject memoryより実セッションを優先（関連自動テスト済み、実LM Studio未確認）。
- Issue #235対応中: PETIT人格をCore Promptへ一本化し、通常会話1 Call、Tasks / CalendarのReadを `Brain -> Context Broker -> Brain` の原則2 Callで処理する最小縦切りを実装。Read sourceは並列取得し、AI向けfactsへ正規化する。実LM Studio・実Notion/Calendar・latency/token比較は未確認。
- 会話 / Agent Runtime: Tool不要の会話はPETIT Brainの最初のLLM回答で終了し、Tasks / CalendarのReadだけ不足する場合はContext Brokerへ進む。書き込み・複雑処理は既存Agent Tool Loopを維持する。
- Prompt / 時刻: PETITの人格・会話原則を共通Core Promptへ統合。動的日時はsystem promptへ常時結合せず、相対日付・時刻を含むターンだけuser側へ必要な精度で注入する。
- 音声: AivisSpeech Engine経由のWAV再生、ブラウザTTS fallback、再試行、直列化、モバイル音声アンロックを実装。実PC／iPhone E2Eは未確認。
- Notionタスク復旧: Tasks画面の明示Notion同期、失敗同期の再試行、競合時の再編集案内を追加。実Notion接続・実ブラウザ操作は未確認。
- へいプティ音声入口（仮実装）: Issue #218 / `feat/petit-vocal-shortcut-prototype` で、iOS Vocal Shortcuts + Appleショートカットから `POST /api/voice` へ音声認識済みテキストを渡し、既存 `/api/chat` へ委譲する導線を追加。PWA自身では常時マイク監視せず、書き込み確認は既存フローを維持する。実iPhone E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in、通知履歴を実装。cache名をv0.14.1へ更新し、Univ空間と四隅App Shellの資産をprecacheへ追加。
- タスク管理: Notionを外部正本、SQLiteをPETITの即時統合ビューとして扱う。通常取得はHigh優先。作成・完了・親子変更は確認付きでNotion同期する。
- Project Continuity: 内部project台帳、alias、source link、checkpoint、handoff、cache-first resumeを統合済み。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、実環境設定と会話E2Eは継続確認が必要。
- Windows起動導線: `scripts/start-petit-tailscale.ps1` で起動モード選択、Tailscale接続、`.venv` のPETIT起動、`/api/health`確認、管理者権限付きTailscale Serve、ブラウザ起動まで実行する。LM Studioは事前起動が必要。
- 今回の検証: Context Broker単体・Brain routeの回帰テストを追加。GitHub Actions / pytest / 実LM Studio E2Eは未確認。
- 次にやること: Issue #235の最小縦切りを実LM Studioで検証し、`今日何やる？` / `明日大丈夫？` のCall数・応答時間・Context量を現行と比較する。その後にIssue #227 Phase 4を再開する。

## 履歴

変更を加えるたびに1行追記する（追記専用・既存行は触らない）。時刻は UTC。

| 日付 | 時間 | 回数 | 変更内容 |
|------|------|------|----------|
| 2026-09-10 | 16:42 | #conflict-resolution | origin/mainへfast-forward後、未コミット変更を復帰。競合マーカーなし。対象テストはvenvにpytestがなく未実行。 |
| 2026-08-02 | 08:54 | #1 | v0.1.0としてバージョン管理ルール、PROGRESS表記、Web UI表示を追加 |
| 2026-08-02 | 09:12 | #2 | v0.1.1としてAgent Runtimeと会話ToolフローのMermaid図、AGENTS同期ルールを追加 |
| 2026-08-02 | 09:40 | #3 | v0.2.0としてToday画面、今日の作業時間集計、作業セッション復元APIを追加 |
| 2026-08-02 | 13:22 | #4 | v0.3.0としてLife星座マップとFocusへのProject・Task導線を追加 |
| 2026-08-02 | 14:25 | #5 | v0.3.1として親子タスク変更のTool選択、承認前引数検証、重複確認防止を追加 |
| 2026-08-02 | 14:29 | #6 | v0.4.0としてLifeホーム化、Focusズーム遷移、Today改善、親Task内の小タスク追加を実装 |
| 2026-08-02 | 16:07 | #7 | v0.5.0として全子タスク周回Focus、CSS球体、親移動処理一本化と冪等化を実装（PC・390x844ブラウザ動作確認済み、実Notion書込・実iPhone PWA未確認） |
| 2026-08-02 | 16:32 | #8 | 詳細表示と親子移動のタスクIDを同期し、別タスク操作時に「LiTのデザイン実装」が移動する取り違えを修正（実Notion書込未確認） |
| 2026-08-02 | 18:41 | #9 | v0.5.1としてTaskの2段階Focus、親変更の明示適用、モバイルLife間隔を改善（PC・390x844ブラウザ動作確認済み、実Notion書込未確認） |
| 2026-08-02 | 18:45 | #10 | 関連72テストは成功。全体394テストは既存Backend・旧UI・外部依存範囲で30失敗・8エラーのため未解決として記録 |
| 2026-08-02 | 19:29 | #11 | Issue #174: Focusノード再利用と継続軌道更新で演出の都度再生・移動停止を修正（動作確認済み） |
| 2026-08-02 | 19:51 | #12 | v0.6.0として大改造を完了。PWAスマホ通知のタップ同頭権限要求・SW一本化、Focus OrbitのGPUトランスフォーム化、Cosmic Glass UI全面刷新を実装 |
| 2026-08-02 | 20:03 | #14 | Notion同期失敗（`親タスク`プロパティ欠落および`done_date`引数不一致）の安全ガード・フォールバック修正と失敗キューの修復 |
| 2026-08-03 | 20:13 | #15 | task_sync_queue: createキュー再試行時のNotionページ重複作成を修正。external_id中間保存で冪等性を確保 |
| 2026-08-02 | 20:45 | #16 | Issue #177: v0.7.0共通UIシステム、状態バー、テーマ切替、モバイル下部ナビ、CSS 3D、モーション統一と回帰テストを追加 |
| 2026-08-03 | 04:17 | #17 | Issue #180: v0.8.0としてLife・Focus・Tasksの共有要素遷移、キャンセル可能なTransition Coordinator、タブ指標、スマホTaskカード、Chatシート、PWAキャッシュ統一を実装 |
| 2026-08-03 | 05:12 | #18 | Issue #182: v0.9.0として共有要素遷移を通常フェードへ戻し、全Viewの銀河空間デザイン、Life星系カード、PC・スマホレイアウトを刷新 |
| 2026-08-03 | 09:32 | #19 | v0.12.0としてHomeとFocusをUnivへ統合し、Core中心の操作可能な3D空間、前面HUD、同一空間内のTask Focus・詳細管理、3領域ナビを追加 |
| 2026-08-03 | 19:25 | #20 | Issue #189: v0.13.0としてCore／親タスク惑星／子タスク衛星へ意味構造を統一し、軽量3D球体、同一空間Focus、タブ直接同期を実装 |
| 2026-08-03 | 20:23 | #21 | Issue #189: v0.14.0として四隅型App Shell、右上3アイコン、左上状態表示、左下補助ドック、旧UI設定導線、PWA cache同期を追加 |
| 2026-08-04 | 07:12 | #22 | v0.14.1として静的資産とPWA cacheの版を統一し、App Shell系の二重読込・初期化と初回タスクAPI重複取得を修正（静的回帰・構文確認済み、PC／スマホ実ブラウザ未確認） |
| 2026-08-04 | 07:57 | #23 | Notionプロパティ解析に英語名・日英フォールバック検索（`Parent item`/`親タスク`, `DoneDate`/`Done`等）を追加し、新規端末初期同期時のプロパティ名不一致エラーを自動修正（単体テスト追加・全件通過確認） |
| 2026-08-04 | 08:34 | #24 | 全画面共通UIの再初期化・Service Worker登録共有・Legacy Jobポーリング重複・Corner Shell Observerの自己誘発監視を抑止（関連回帰37件成功、実ブラウザ未完了） |
| 2026-08-04 | 08:34 | #25 | Service WorkerをPush有効化操作まで遅延登録し、通常のUniverse／Legacy起動時の登録・precache待ちを除去（Node構文・関連回帰37件成功、実ブラウザ未完了） |
| 2026-08-04 | 08:54 | #26 | universe-next.jsの更新中Observer一時切断と重複軽減・petit-ui-system/app_shellの監視責務分離および差分DOM更新を実装（関連回帰34件全件成功） |
| 2026-08-04 | 09:10 | #27 | v0.15.0としてUniverse UIを根本刷新。カード矩形UIを全廃し、Core＝中心惑星、親タスク＝惑星、子タスク＝衛星、軌道・接続線からなる純粋な天体システムを実装 |
| 2026-08-05 | 09:26 | #28 | `origin/main`を先に取り込み、`refactor/universe-render-scheduler`を競合解消付きでmainへ統合。関連66テスト、Node/Python構文、差分検査に成功（実ブラウザ・実サービスE2E未確認） |
| 2026-08-05 | 10:50 | #29 | `app.js` と `universe-app.js` のチャット入力キーハンドラーを修正し、Enterキー単体での即時送信を防止、Ctrl/Cmd+Enterのみ送信に統一（関連テスト全件通過） |
| 2026-08-05 | 10:54 | #30 | `chat_input.js`, `chat_keyboard.js`, `app.js`, `universe-app.js` を更新し、IME変換確定のEnter保護・タイマーガード、変換終了後のEnter送信、Shift+Enter改行を実装（関連テスト全件通過） |
| 2026-08-05 | 10:59 | #31 | `univ-space.js`, `univ-space.css`, `universe-webgl-scene.js` を更新し、スマホでのタッチドラッグ宇宙操作対応および2段階タスククリック（1回目フォーカス、2回目詳細表示）を実装（関連テスト全件通過） |
| 2026-08-05 | 11:09 | #32 | `universe-app.js` を更新し、初期化時の過去会話履歴の自動取得・復元機能（restoreHistory）を追加（関連テスト全件通過） |
| 2026-08-05 | 11:18 | #33 | `universe.html` および `universe-app.js` を更新し、2時間アイドル時の自動セッション分割モジュール（session.js）を統合（関連テスト全件通過） |
| 2026-08-05 | 11:30 | #34 | v0.16.0として旧UI（音声音答・モデル切替・通知設定・声かけ頻度・クイック質問等）を新UIへ完全移植。タスク詳細画面での属性フル編集フォームを追加（関連テスト全件通過） |
| 2026-08-05 | 11:35 | #35 | `petit-ui-system.css` および `universe-actions.css` を修正し、スマホ画面でのヘッダー埋もれ・トップバーアクション見切れ・吸着オフセットを改善（テスト49件成功） |
| 2026-08-05 | 12:12 | #36 | `petit-ui-system.js` の `installSpatialMotion` 内のマウス移動による常時チルト・視点追尾 (`pointermove`) を削除し、ドラッグなしの追尾現象を解消（テスト49件成功） |
| 2026-08-05 | 13:45 | #37 | Univ WebGLの入力をOrbitControlsへ明示統合し、PCホイール、1本指回転、2本指ピンチ、複数ポインター時のraycast誤選択、ドラッグ後の慣性回転を修正（関連テスト確認済み、実iPhone未確認） |
| 2026-08-05 | 14:14 | #38 | v0.17.0としてTool不要会話を1回のLLMで完了するOne-pass Conversation Entry、安全な読取fallback、動的時刻のuser側注入、Agent prompt圧縮とMarkdown緩和を実装（Python構文確認・回帰テスト追加、実LM Studio比較未確認） |
| 2026-08-07 | 00:00 | #39 | UIテーマをライト／ダーク／システム選択に対応し、OSのカラースキーム変更へ追従。Three.js Univ空間は暗色を維持し、外側の詳細UIだけライトテーマへ切替 |
| 2026-08-07 | 00:00 | #40 | Univ WebGLの星名ラベルをクリック可能にし、OrbitControlsの空間操作と星名選択を併用可能に変更（関連回帰テスト成功） |
| 2026-08-06 | 17:15 | #41 | Univのラベル選択で元DOMクリックによる全体再描画を避け、Universe選択APIへ統合。再選択時のフォーカス再実行も抑止 |
| 2026-08-12 | 00:00 | #42 | スマホ版でFocusのタスク詳細パネルを非表示化し、ノッチ用safe-areaとチャット入力欄の縦位置を修正（静的確認済み、実iPhone未確認） |
| 2026-08-12 | 00:00 | #43 | 新UIのSettingsへ通知センターを統合し、モデル・Push通知設定を集約。新UIから旧UIへ戻る導線を削除（静的確認済み） |
| 2026-08-13 | 00:00 | #44 | `start-petit-tailscale.bat` と `scripts/start-petit-tailscale.ps1` を追加し、PETIT起動・ヘルスチェック・管理者権限付きTailscale Serve起動を自動化（初版BATはcmdの文字コード・記号解釈問題があり修正、実機UAC・外部Tailnet接続は未確認） |
| 2026-08-13 | 00:00 | #45 | BATを廃止し、`scripts/start-petit-tailscale.ps1` に起動モード選択、Tailscale接続、PETIT起動、ブラウザ起動を統合（PowerShell構文確認済み、実機UAC・外部Tailnet接続は未確認） |
| 2026-08-13 | 00:00 | #46 | デスクトップに `PETIT Launcher.lnk` を作成し、ダブルクリックでPowerShellランチャーを起動できるように設定（ショートカット設定確認済み、実機UAC・外部Tailnet接続は未確認） |
| 2026-08-22 | 16:43 | #47 | Issue #168: Task ID付き作業履歴、状態遷移イベント、今日・期間集計、チャットTool、Universeのサーバーactive同期を実装（関連自動テスト・構文確認済み、実LM Studio・PC／iPhone E2E未確認） |
| 2026-08-17 | 00:00 | #47 | Git整理の中間対応として、`c26db2b` から `feat/chat-work-session` を作成し、整理前の `agent/univ-three-work-chat` を `backup-before-branch-cleanup-20260817` タグへ保存（リモート削除・履歴書き換えは未実施） |
| 2026-08-17 | 00:00 | #48 | GitHub上のリモートブランチを `main` と `feat/chat-work-session` に整理し、重複リモート `PETIT` と旧ローカルブランチ `agent/univ-three-work-chat` を削除（作業ブランチはPush済み、PROGRESS変更は未コミット） |
| 2026-08-17 | 00:00 | #49 | Issue #215: Univ表示時のhtml/body・メイン領域を固定し、safe-area対応の100dvh viewportとWebGL単一背景を実装（関連回帰26件成功、実ブラウザ・実iPhone未確認） |
| 2026-08-16 | 16:36 | #50 | Issue #215: URL直開き時のWebGL未読込と詳細初期化例外を修正し、星の1クリックFocus・HUD同期、全画面Canvas、PC／390x844のHUD・詳細配置を再調整（関連57件・実ブラウザ成功、実iPhone未確認） |
| 2026-08-16 | 23:04 | #47 | Issue #215: v0.18.0としてUnivを100dvh固定Three.js空間へ統一し、WebGL時のCSS背景重複を廃止、mobile safe-area内へHUDを固定（静的回帰テスト追加、実PC／iPhone操作感は未確認） |
| 2026-08-18 | 11:53 | #48 | Issue #218: 「へいプティ」Vocal Shortcut向け `POST /api/voice` を追加し、既存 `/api/chat` へ委譲。最新mainへ競合解消し、確認付き書き込み・回帰テスト・iPhone設定手順を維持（実iPhone E2E未確認） |
| 2026-08-22 | 17:07 | #49 | v0.18.1としてUniv WebGLを必要時描画へ変更し、ラベルDOMの毎フレーム更新・選択時の重複再描画・軽量設定のWebGL無視を修正 |
| 2026-08-22 | 17:21 | #50 | v0.18.2として旧左レールの228px予約幅を解除し、デスクトップUnivの左余白を修正 |
| 2026-08-23 | 05:11 | #51 | PR #222: Tasks画面へNotion明示同期・失敗同期の再試行・競合時の再編集案内を追加。mainのv0.18.2更新を維持して競合解消（実Notion・実ブラウザ未確認） |
| 2026-08-23 | 14:12 | #52 | Issue #223: active / paused Work SessionをOne-pass Conversation Entryへcompact注入し、proactive openerで実セッションを優先（関連48テスト・Python構文確認済み、実LM Studio未確認。旧`test_assistant_context.py`の既存失敗はorigin/mainでも再現） |
| 2026-09-02 | 06:49 | #53 | Issue #227 Phase 2: `/api/health` の実装を `backend/health.py` のAPIRouterへ分離し、`backend/main.py` はRouter登録だけを担当。path/response契約は維持し、Router所有権の回帰テストを追加（実サービスE2E未確認） |
| 2026-09-02 | 07:18 | #54 | Issue #227 Phase 2: `/api/tts` と `/api/tts/status` を `backend/voice.py` のAPIRouterへ分離し、`backend/main.py` はRouter登録だけを担当。path/response契約を維持し、Router所有権の回帰テストを追加（実AivisSpeech E2E未確認） |
| 2026-09-02 | 07:32 | #55 | Issue #227 Phase 2: `GET/POST /api/model-routing` を `backend/model_routing_api.py` のAPIRouterへ分離し、`backend/main.py` はRouter登録だけを担当。更新schema・health cacheクリアも専用Routerへ移動し、Router所有権の回帰テストを追加（実モデル切替E2E未確認） |
| 2026-09-06 | 04:09 | #56 | Issue #227 Phase 2: `POST /api/notion/webhook` を `backend/notion_webhook.py` のAPIRouterへ分離し、endpoint key・JSON・verification token・signature検証を移動。`backend/main.py` はRouter登録だけを担当し、Router所有権の回帰テストを追加（実Notion Webhook E2E未確認） |
| 2026-09-06 | 04:14 | #57 | v0.18.3 / Issue #227 Phase 2: startup/shutdown・Chroma初期同期を `backend/lifecycle.py` へ分離し、`backend/main.py` は `lifecycle.register(app)` のみ担当。lifecycle登録回帰テストを追加（実サービス起動E2E未確認） |
| 2026-09-06 | 12:13 | #58 | v0.18.4 / Issue #227 Phase 2: Pending Actionの10分TTL状態管理・`POST /api/actions/{approval_id}`・Sona Core互換分岐・承認後Tool dispatchを `backend/pending_actions.py` へ分離し、`backend/chat_models.py` に確認APIモデルを共通化。Runtime FlowとRouter所有権テストを更新（実承認E2E未確認） |
| 2026-09-06 | 13:16 | #59 | v0.18.5 / Issue #227 Phase 2: `POST /api/chat`・Agent実行・observability・SQLite会話保存・Chroma/Markdown artifact保存を `backend/chat.py` へ分離。`main.py` はRouter登録のみ担当し、Vocal ShortcutもChat moduleへ直接接続。Router所有権・空入力契約の回帰テストを追加（実LM Studio・実iPhone E2E未確認） |
| 2026-09-06 | 18:03 | #60 | v0.18.6 / Issue #227 Phase 2完了: 補助API群とStatic Frontend配線まで専用モジュールへ分離し、`backend/main.py` をFastAPI生成・Router登録・lifecycle/frontend登録・起動のみのComposition Rootへ縮小。次フェーズはModule Registry（pytest / 実サービスE2E未確認） |
| 2026-09-06 | 18:10 | #61 | v0.19.0 / Issue #227 Phase 3開始: `backend/kernel/modules.py` に `ModuleDefinition` / `ModuleRegistry` を追加し、Router・registrar・依存関係を明示登録。`backend/app.py` の `create_app()` がModule RegistryからFastAPIを構築し、`backend/main.py` は起動shimへ縮小。依存順・重複ID・未知依存・循環依存の回帰テストを追加（pytest / 実サービスE2E未確認） |
| 2026-09-06 | 18:16 | #62 | v0.19.1 / Issue #227 Phase 3完了: `backend.tools` package import時の全built-in Tool副作用登録を廃止し、`backend/tools/builtins.py` の明示catalogを `builtin-tools` Moduleとして登録。Pending Action / ChatのTool依存をModule Registryへ宣言し、単体import時0件・`create_app()`後登録のsubprocess回帰テストを追加（pytest / 実LM Studio E2E未確認） |
| 2026-09-06 | 18:30 | #63 | Issue #235: PETIT Core Promptを共通化し、Tasks / Calendar限定Context Broker、Read並列取得、`Brain -> Broker -> Brain` 2 Call経路、Call数/Context量observability、関連回帰テストとRuntime Mermaidを追加（pytest / 実LM Studio・外部サービスE2E未確認） |
| 2026-09-07 | 06:38 | #64 | Issue #249 / Refs #245: Web中心のJARVIS全体設計、個人Contextの横断Read・期限/最大4枠/サイズ上限・部分失敗、2回目Brainへの状況継続と生成失敗の非保存、任意PC観測Module、FastAPI lifecycle登録互換性を実装。Runtime Mermaid・関連回帰テストを更新（実LLM・外部サービス・PWA/Windows前面アプリE2E未確認） |
| 2026-09-07 | 11:10 | #65 | Issue #253: v0.20.0としてDesktop設計、Electron常駐シェル、小型共有UI、取消可能な音声入力、任意ウェイク、更新通知・手動配布workflowを追加。Desktop境界12テスト・既存関連19テストと31 subtest・macOS実Electronの仮サーバー/生成音声操作を確認。古いPrompt/Router回帰テストを現行構成へ追従（実マイク・Windows・署名済み配布は未確認） |
| 2026-09-08 | 14:16 | #66 | Issue #253: Desktop配布workflowをPRテスト、手動開発Artifact、main上のversion一致`v*`タグによるmacOS arm64/Windows x64ビルド＋GitHub Release自動添付へ整理。タグ/`package.json` version一致とmain履歴チェックを追加（実タグRelease・署名済み配布は未確認） |
| 2026-09-09 | 12:11 | #67 | Issue #255: Web音声入力の現行UI接続を修正し、録音STT・原因別案内・下書き保持を追加（関連Python24件、Web音声7件、Desktop12件成功。Braveの現行DOM＋模擬認識で送信確認、実マイク・実STT未確認） |
| 2026-09-09 | 12:23 | #68 | Issue #256: Desktopにウェイクモデル自動取得・生成、OS暗号化保存、マイク実検出テスト、原因別表示と詳細手動設定を追加。関連21テスト・実Electron操作・Mac arm64展開ビルド成功。キー付きAPI・実マイク・Windows実機は未確認 |
| 2026-09-09 | 15:56 | #69 | Issue #258: openWakeWord独立学習環境・日本語SAPI合成・話者分離評価・WAV検証CLIを追加しhey_petit.onnx v0.1を生成（動作確認済み: ONNX/実推論・2テスト・構文・依存整合。test正例12/12、負例誤検出11/144。実声/長時間待機/Desktop統合は未確認、常時待機精度は未達） |
| 2026-09-09 | 17:38 | #70 | Issue #253 / #258調査: Windowsインストール版PETITの起動と保存設定を確認。STT URL未設定、wakeEnabled=false、Porcupineモデル・保存キー未設定のため音声入口は未構成。実装上ウェイクは小型画面非表示時のみ、openWakeWordはDesktop未統合。設定変更・実マイク検証は未実施 |
| 2026-09-09 | 17:51 | #71 | feat/petit-desktop へ origin/feat/petit-desktop、fix/desktop-wake-auto-setup、main の全最新アップデート・派生ブランチを競合解消して完全マージ統合 |
| 2026-09-10 | 04:11 | #73 | Windows環境におけるwake-settings.test.cjsのURL形式不一致を修正（全21テスト成功） |
| 2026-09-10 | 07:30 | #74 | Porcupine依存を削除し、DesktopをローカルopenWakeWord/ONNX＋Pythonマイクランタイムへ接続。実マイク評価は環境依存で未確認 |

| 2026-09-09 | 21:33 | #74 | Issue #260: Web/小型Desktopの共通モーション、Desktop設定・録音中の軌道表現、PWAキャッシュ更新を実装。動作確認済み: EdgeのUniverse/Legacy（1280px・390px）と実Electron fixture smoke、通常/reduced-motion、diff確認。既存PWA更新・実iPhone/macOS・配布版反映は未確認 |
| 2026-09-09 | 21:43 | #75 | Issue #260: Three.js天体の登場・選択拡大・発光パルスを追加し必要時描画を維持。実WebGL fixture確認・関連13テスト・構文成功。古いSWキャッシュ名のテスト期待値を更新。大量実データ・実iPhone/macOS性能は未確認 |
| 2026-09-10 | 06:50 | #76 | Proactive openerのセッション外エピソード参照を停止し、誤ったepisode_id=2をSQLite/Chromaから削除（関連10テスト成功、実アプリ・実LLM未確認） |
| 2026-09-12 | 10:10 | #77 | Issue #270 Step 1: Desktop Wake設定をopenWakeWordへ一本化し、旧Picovoice/Porcupine AccessKey・PPN・自動設定IPC・暗号化キー保存を撤去。旧設定読込時の秘密情報/metadata除去とopenWakeWordエラー分類の回帰テストを追加（実マイク・installerはStep 3で確認） |
| 2026-09-12 | 10:24 | #78 | Issue #270 Step 2: Desktop設定からopenWakeWord環境を一括準備できる導線を追加。Python検出、専用venv、依存、backbone、既存/生成済みWakeモデルの管理領域化、マイクなしdiagnostic、進捗/中止、managed runtimeパス保存を実装し、Desktop CI成功。packagedモデル同梱・実マイク`ready`・実声はStep 3へ残す。 |
| 2026-09-12 | 10:53 | #79 | Issue #270 Step 3: Wakeモデルのinstaller注入経路（ローカル生成物またはHTTPS URL＋SHA-256）、manifest同梱、packaged resources検証を実装。Run #76でmacOS arm64 DMG / Windows x64 EXEを実生成しSmoke・resource検証成功。実モデル配布元を使った同梱build、インストール版自動設定→diagnostic、実マイク`ready`、実声検出・誤起動評価は未完了。PR #272 Draft継続。 |
