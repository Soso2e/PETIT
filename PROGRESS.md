# PROGRESS — 変更履歴

**Current Version: v0.12.0**

**Last Updated: 2026-08-03**

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。FastAPIとPWAを基盤に、タスク・予定・会話・知識・開発状況を継続支援する個人用アシスタントとして開発中。
- バージョン管理: v0.12.0。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する。
- Univ UI: HomeとFocusの独立タブを廃止し、`Univ / Tasks / PETIT`の3領域へ再編。Univは中央のCoreからProject・Taskへ派生する同一空間で、ドラッグによる視点回転、ホイール／ボタンによるズーム、Task選択、Focus、詳細管理を行う。ProjectとTaskへZ方向の奥行きを与え、既存のタスク取得・選択・Notion同期・親子タスク管理処理は再利用する。
- Front UI: Univ空間の手前に、現在モード、選択Project・Task、Focus、管理、Core復帰、ズーム、視点リセットを常設する。既存の`#detail-panel`はPCでは右側パネル、スマホでは下部シートとして同じ空間上へ表示する。
- ナビゲーション: PCは左レール、スマホは下部3タブ。`home`、`focus`、`universe`、`projects`の旧URL／内部呼び出しはUnivへ互換転送する。
- モーション: View間は既存の短いフェードを維持し、Univ内部だけCSS 3Dカメラを利用する。`prefers-reduced-motion`では空間アニメーションとパネル遷移を停止する。
- 制作伴走 / Today: 作業セッションをSQLiteで永続化し、20分ごとの継続確認と無応答時の自動停止をバックグラウンドWorkerで実行する。Today機能自体は残し、トップレベルタブからは外す。
- 会話 / Agent Runtime: Project Continuity・Capability Router・Tool制限・書き込み承認・進捗表示を実装済み。実装準拠フローは`docs/runtime-flows.md`を正とする。
- 音声: AivisSpeech Engine経由のWAV再生、ブラウザTTS fallback、再試行、直列化、モバイル音声アンロックを実装。実PC／iPhone E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in、通知履歴を実装。Univ資産は動的ロード後に既存のnetwork-first Service Workerへキャッシュされる。precache一覧とcache名のv0.12.0同期は接続側の安全制限により未実施。
- タスク管理: Notionを外部正本、SQLiteをPETITの即時統合ビューとして扱う。通常取得はHigh優先。作成・完了・親子変更は確認付きでNotion同期する。
- Project Continuity: 内部project台帳、alias、source link、checkpoint、handoff、cache-first resumeを統合済み。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、実環境設定と会話E2Eは継続確認が必要。
- 今回の検証: `app_shell.js`と`univ-space.js`のNode構文確認、Univ CSSの括弧対応、3領域ナビ、3D視点、前面HUD、Focus、詳細管理、スマホ3列ナビ、reduced motion、v0.12.0表記を静的回帰テストへ追加。
- 次にやること: 実データ入りPCブラウザでドラッグ、ズーム、Task Focus、詳細管理を確認する。390x844と実iPhone PWAで下部3タブ、safe-area、HUD重なり、詳細シート、長時間操作時の負荷を確認する。Service Workerのprecache名とUniv資産をv0.12.0へ同期する。

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
