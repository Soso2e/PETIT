# PROGRESS — 変更履歴

**Current Version: v0.18.2**

**Last Updated: 2026-08-23**

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。FastAPIとPWAを基盤に、タスク・予定・会話・知識・開発状況を継続支援する個人用アシスタントとして開発中。
- バージョン管理: v0.17.0。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する。
- Univ UI 刷新: 大きなカード矩形を全廃し、Core＝中心惑星、親タスク＝惑星、子タスク＝衛星、関係性＝軌道・接続線からなる天体UIへ根本刷新。詳細情報は天体選択時に右側詳細パネルで確認・操作する。
- Univ描画: WebGL依存を追加せず、CSS 3D・radial-gradient・既存SVG接続線で軽量な球体表現を実装。レイヤーは前面HUD、選択対象の説明、惑星・衛星、接続線、背景の順で固定する。
- Issue #215対応: Univ表示時だけページを固定し、100dvhとsafe-area内のThree.js viewportへ切り替える。WebGL成功時はCSS宇宙背景を隠し、Canvasを単一の背景描画面として扱う。星の初回クリックでカメラFocusとHUD選択を同期し、2回目で詳細を開く（PC・390x844ブラウザ確認済み、実iPhone未確認）。
- バージョン管理: v0.18.1。Univの常時WebGL描画を必要時描画へ変更し、PWA全体のメインスレッド負荷を軽減。
- バージョン管理: v0.18.2。四隅型App Shellで非表示になった旧左レールの予約幅を解除し、デスクトップUnivを全幅表示へ復旧。
- Univ UI 刷新: 大きなカード矩形UIを全廃し、Core＝中心惑星、親タスク＝惑星、子タスク＝衛星、関係性＝軌道・接続線からなる天体UIへ根本刷新。詳細情報は天体選択時に右側詳細パネルで確認・操作する。
- Univ描画: Three.js WebGLを主描画としてCore・親Task・子Task・接続線・星背景を描画し、DOMはラベル・HUD・詳細・操作UIに限定。WebGL利用不可時のみ既存CSS 3D表示へフォールバックする。
- Univ表示領域: Univ表示中はページスクロールを止め、Canvasを100dvhの固定空間として表示。WebGL準備後は外側のCSS宇宙背景を無効化し、スマホHUDはsafe-areaと下部ナビを避ける。
- Univ Focus: 親タスク惑星または子タスク衛星を選ぶと、同じUniv内でカメラが対象系へ寄り、所属する衛星を見やすくする。他の惑星と接続線は暗くし、旧Focusパネルへ自動遷移しない。
- Front UI: 左上に現在領域・同期状態・バージョン、右上にUniv／Tasks／PETITの3アイコン、左下にReminders／Settingsを置く四隅型App Shellへ更新。スマホでは主要タブをアイコンだけにし、safe-areaを考慮する。
- 補助導線: Settingsから詳細設定を備えた旧UIへ直接移動できる。旧UIは廃止せず、移行中の保険・全機能への導線として残す。
- ナビゲーション: 対象パネルの`hidden`・ARIA・active状態を直接同期する。`home`、`focus`、`universe`、`projects`の旧URL／内部呼び出しはUnivへ互換転送する。
- モーション: View間は既存の短いフェードを維持し、Univ内部だけCSS 3Dカメラを利用する。`prefers-reduced-motion`では空間アニメーションとパネル遷移を停止する。
- 制作伴走 / Today: 作業セッションをNotion Task DBの変更なしでPETIT内部Task IDへ紐づけ、状態遷移イベントをSQLiteへ永続化する。20分ごとの継続確認と無応答時の自動停止、タスク別・プロジェクト別・直近1〜90日集計、チャットからの開始・一時停止・再開・終了・実績参照に対応。Today機能自体は残し、トップレベルタブからは外す。
- 会話 / Agent Runtime: Tool不要の会話はOne-pass Conversation Entryの最初のLLM回答で終了し、個人データ・現在情報・外部ソース・操作が必要な場合だけAgent Tool Loopへ進む。Router失敗時は内部`fallback_read`で明示した読取Toolだけを公開する。
- Prompt / 時刻: Agentの中核ルールを短く肯定形へ整理し、Markdown全面禁止を撤廃。動的日時はsystem promptへ常時結合せず、相対日付・時刻を含むターンだけuser側へ必要な精度で注入する。
- 音声: AivisSpeech Engine経由のWAV再生、ブラウザTTS fallback、再試行、直列化、モバイル音声アンロックを実装。実PC／iPhone E2Eは未確認。
- へいプティ音声入口（仮実装）: Issue #218 / `feat/petit-vocal-shortcut-prototype` で、iOS Vocal Shortcuts + Appleショートカットから `POST /api/voice` へ音声認識済みテキストを渡し、既存 `/api/chat` へ委譲する導線を追加。PWA自身では常時マイク監視せず、書き込み確認は既存フローを維持する。実iPhone E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in、通知履歴を実装。cache名をv0.14.1へ更新し、Univ空間と四隅App Shellの資産をprecacheへ追加。
- タスク管理: Notionを外部正本、SQLiteをPETITの即時統合ビューとして扱う。通常取得はHigh優先。作成・完了・親子変更は確認付きでNotion同期する。
- Project Continuity: 内部project台帳、alias、source link、checkpoint、handoff、cache-first resumeを統合済み。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、実環境設定と会話E2Eは継続確認が必要。
- Windows起動導線: `scripts/start-petit-tailscale.ps1` で起動モード選択、Tailscale接続、`.venv` のPETIT起動、`/api/health`確認、管理者権限付きTailscale Serve、ブラウザ起動まで実行する。LM Studioは事前起動が必要。
- 今回の検証: Univ固定viewport・WebGL時のCSS背景除去・mobile safe-area・Three.jsの既存選択／Focus契約を静的回帰テストで検証。実PC／実iPhoneでのカメラ操作感は未確認。
- 次にやること: 実PC／iPhone PWAでUnivを開き、スクロール不能、ドラッグ・ピンチ・ホイール、星選択、Focus、詳細表示、safe-areaを確認する。

## 履歴

変更を加えるたびに1行追記する（追記専用・既存行は触らない）。時刻は UTC。

| 日付 | 時間 | 回数 | 変更内容 |
|------|------|------|----------|
| 2026-08-02 | 08:54 | #1 | v0.1.0としてバージョン管理ルール、PROGRESS表記、Web UI表示を追加 |
| 2026-08-02 | 09:12 | #2 | v0.1.1としてAgent Runtimeと会話ToolフローのMermaid図、AGENTS同期ルールを追加 |
| 2026-08-02 | 09:40 | #3 | v0.2.0としてToday画面、今日の作業時間集計、作業セッション復元APIを追加 |
| 2026-08-02 | 13:22 | #4 | v0.3.0としてLife星座マップとFocusへのProject・Task導線を追加 |
| 2026-08-02 | 14:25 | #5 | v0.3.1として親子タスク変更のTool選択、承認前引数検証、重複確認防止を追加 |
| 2026-08-02 | 14:29 | #6 | v0.4.0としてLifeホーム化、Focusズーム遷移、Today改善、親Task内の小タスク追加を実装 |
| 2026-08-02 | 16:07 | #7 | v0.5.0として全子タスク周回Focus、CSS球体、親移動処理一本化と冪等化を実装（PC・390x844ブラウザ動作確認済み、実Notion書込・実iPhone PWA未確認） |
| 2026-08-02 | 16:32 | #8 | 詳細表示と親子移動のタスクIDを同期し、別タスク操作時に「LiTのデザイン実装」が移動する取り違えを修正（実Notion書込未確認） |
| 2026-08-02 | 18:41 | #9 | v0.5.1としてTaskの2段階Focus、親変更の明示適用、モバイルLife間隔を改善（PC・390x844ブラウザ動作確認済み、実Notion書込・実iPhone PWA未確認） |
| 2026-08-02 | 18:45 | #10 | 関連72テストは成功。全体394テストは既存Backend・旧UI・外部依存範囲で30失敗・8エラーのため未解決として記録 |
| 2026-08-02 | 19:29 | #11 | Issue #174: Focusノード再利用と継続軌道更新で演出の都度再生・移動停止を修正（動作確認済み） |
| 2026-08-02 | 19:51 | #12 | v0.6.0として大改造を完了。PWAスマホ通知のタップ同頭権限要求・SW一本化、Focus OrbitのGPUトランスフォーム化、Cosmic Glass UI全面刷新を実装 |
| 2026-08-02 | 20:03 | #14 | Notion同期失敗（`親タスク`プロパティ欠落および`done_date`引数不一致）の安全ガード・フォールバック修正と失敗キューの修復 |
| 2026-08-03 | 20:13 | #15 | task_sync_queue: createキュー再試行時のNotionページ重複作成を修正。external_id中間保存で冪等性を確保 |
| 2026-08-02 | 20:45 | #16 | Issue #177: v0.7.0共通UIシステム、状態バー、テーマ切替、モバイル下部ナビ、CSS 3D、モーション統一と回帰テストを追加 |
| 2026-08-03 | 04:17 | #17 | Issue #180: v0.8.0としてLife・Focus・Tasksの共有要素遷移、キャンセル可能なTransition Coordinator、タブ指標、スマホTaskカード、Chatシート、PWAキャッシュ統一を実装 |
| 2026-08-03 | 05:12 | #18 | Issue #182: v0.9.0として共有要素演出を通常フェードへ戻し、全Viewの銀河空間デザイン、Life星系カード、PC・スマホレイアウトを刷新 |
| 2026-08-03 | 09:32 | #19 | v0.12.0としてHomeとFocusをUnivへ統合し、Core中心の操作可能な3D空間、前面HUD、同一空間内のTask Focus・詳細管理、3領域ナビを追加 |
| 2026-08-03 | 19:25 | #20 | Issue #189: v0.13.0としてCore／親タスク惑星／子タスク衛星へ意味構造を統一し、軽量3D球体、同一空間Focus、タブ直接同期を実装 |
| 2026-08-03 | 20:23 | #21 | Issue #189: v0.14.0として四隅型App Shell、右上3アイコン、左上状態表示、左下補助ドック、旧UI設定導線、PWA cache同期を追加 |
| 2026-08-04 | 07:12 | #22 | v0.14.1として静的資産とPWA cacheの版を統一し、App Shell系の二重読込・初期化と初回タスクAPI重複取得を修正（静的回帰・構文確認済み、PC／スマホ実ブラウザ未確認） |
| 2026-08-04 | 07:57 | #23 | Notionプロパティ解析に英語名・日英フォールバック検索（`Parent item`/`親タスク`, `DoneDate`/`Done`等）を追加し、新規端末初期同期時のプロパティ名不一致エラーを自動修正（単体テスト追加・全件通過確認） |
| 2026-08-04 | 08:34 | #24 | 全画面共通UIの再初期化・Service Worker登録共有・Legacy Jobポーリング重複・Corner Shell Observerの自己誘発監視を抑止（Node構文・関連回帰37件成功、実ブラウザ未完了） |
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
