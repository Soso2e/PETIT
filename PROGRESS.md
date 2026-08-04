# PROGRESS — 変更履歴

**Current Version: v0.14.1**

**Last Updated: 2026-08-04**

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。FastAPIとPWAを基盤に、タスク・予定・会話・知識・開発状況を継続支援する個人用アシスタントとして開発中。
- バージョン管理: v0.14.1。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する。
- Univ UI: `Core = 中心惑星`、`親タスク = 惑星`、`子タスク = 衛星`として表現を統一。Project名は惑星の所属情報として扱い、Core overviewから親タスク惑星と子タスク衛星を見渡す。
- Univ描画: WebGL依存を追加せず、CSS 3D・radial-gradient・既存SVG接続線で軽量な球体表現を実装。レイヤーは前面HUD、選択対象の説明、惑星・衛星、接続線、背景の順で固定する。
- Univ Focus: 親タスク惑星または子タスク衛星を選ぶと、同じUniv内でカメラが対象系へ寄り、所属する衛星を見やすくする。他の惑星と接続線は暗くし、旧Focusパネルへ自動遷移しない。
- Front UI: 左上に現在領域・同期状態・バージョン、右上にUniv／Tasks／PETITの3アイコン、左下にReminders／Settingsを置く四隅型App Shellへ更新。スマホでは主要タブをアイコンだけにし、safe-areaを考慮する。
- 補助導線: Settingsから詳細設定を備えた旧UIへ直接移動できる。旧UIは廃止せず、移行中の保険・全機能への導線として残す。
- ナビゲーション: 対象パネルの`hidden`・ARIA・active状態を直接同期する。`home`、`focus`、`universe`、`projects`の旧URL／内部呼び出しはUnivへ互換転送する。
- モーション: View間は既存の短いフェードを維持し、Univ内部だけCSS 3Dカメラを利用する。`prefers-reduced-motion`では空間アニメーションとパネル遷移を停止する。
- 制作伴走 / Today: 作業セッションをSQLiteで永続化し、20分ごとの継続確認と無応答時の自動停止をバックグラウンドWorkerで実行する。Today機能自体は残し、トップレベルタブからは外す。
- 会話 / Agent Runtime: Project Continuity・Capability Router・Tool制限・書き込み承認・進捗表示を実装済み。実装準拠フローは`docs/runtime-flows.md`を正とする。
- 音声: AivisSpeech Engine経由のWAV再生、ブラウザTTS fallback、再試行、直列化、モバイル音声アンロックを実装。実PC／iPhone E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in、通知履歴を実装。cache名をv0.14.1へ更新し、Univ空間と四隅App Shellの資産をprecacheへ追加。
- タスク管理: Notionを外部正本、SQLiteをPETITの即時統合ビューとして扱う。通常取得はHigh優先。作成・完了・親子変更は確認付きでNotion同期する。
- Project Continuity: 内部project台帳、alias、source link、checkpoint、handoff、cache-first resumeを統合済み。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、実環境設定と会話E2Eは継続確認が必要。
- 今回の検証: 全画面共通の応答停止調査で、同一HTML内の優先スクリプト重複は確認できなかった。notifications／companionの再初期化、Service Workerの起動時自動登録、LegacyのJobポーリング重複、Corner Shell Observerの自己誘発DOM監視を抑止し、Node構文と関連回帰37件に成功。実ブラウザは初期化後のCDP応答が停止し、Service Worker削除後／有効時のUniverse・Legacy確認は未完了。
- 次にやること: FastAPIを実行中のPCブラウザで旧Service Worker cache削除後と有効時を分け、Universe／Legacy双方の操作、Long Task、Observer loop、CPU、Networkの初期化回数を確認する。残る高負荷があればPriority JSを1本ずつ無効化して二分探索する。

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
| 2026-08-02 | 16:07 | #7 | v0.5.0として全子タスク周回Focus、CSS球体、親移動処理一本化と冪等化を実装（PCブラウザ動作確認済み・実Notion書込未確認） |
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
