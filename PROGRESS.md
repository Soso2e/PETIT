# PROGRESS — 変更履歴

**Current Version: v0.9.0**

**Last Updated: 2026-08-03**

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。現状はFastAPI + ブラウザのテキストチャットMVPで、最終形はスマホとPCの音声中心常駐アシスタント。
- バージョン管理: v0.9.0。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する。
- Life / Focus / Tasks UI: v0.8.0の共有要素Ghost・奥行きズーム・Life専用遷移を撤去し、全View共通の220ms前後の短いフェードへ戻した。`petit-galaxy.css`を最終レイヤーとして追加し、深い青黒、静かな星明かり、薄い境界、統一した角丸・影・余白・文字階層でGalactic Spatial Designへ刷新した。Lifeは絶対配置の惑星群をCSS上で解除し、PCは3列、タブレットは2列、スマホは1列の星系カードへ変更。Focusは作業空間と詳細の司令室レイアウト、TasksはPC表／スマホカード、Chatは通信パネル、Today・Remindも同じ面構成へ統一した。実ブラウザと実iPhone PWAは未確認。
- 制作伴走 / Today: 作業セッションをSQLiteで永続化し、20分ごとの継続確認と無応答時の自動停止をバックグラウンドWorkerで実行する。Todayは今日の合計、作業中状態、セッション数、取り組み数、最長Focus、タイムライン、取り組み別配分とLife・Focusへの行動導線を表示する。実ブラウザ・実Push・iPhone PWA E2Eは未確認。
- 会話 / Agent Runtime: Project Continuity・挨拶・正確な現在時刻だけを決定論的な安全ゲートで処理し、通常会話はChatモデルのCapability Routerが最大4領域を選ぶ。Agentには選択領域内の登録済みToolだけを公開し、既定3ラウンド・Tool総数6・同一Tool同一引数1回の上限、結果圧縮、書き込み承認、30分以内のAgent状態再開、履歴へ残さない進捗表示を実装。確認対象Toolは承認前にschema検証し、親子タスク変更は`set_task_parent`へ集約、Runtime外の重複確認はTool callへ戻す。実装準拠フローは`docs/runtime-flows.md`を正とする。
- 音声: AivisSpeech Engine経由のWAV再生、ブラウザTTS fallback、再試行、直列化、モバイル音声アンロックを実装。実PC／iPhone E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in、通知履歴を実装。Service Workerのshell cacheをv0.9.0へ更新し、Galactic Spatial Design資産をprecache対象へ追加した。実VAPID／HTTPS／バックグラウンド受信は未確認。
- タスク管理: Notionを外部正本、SQLiteをPETITの即時統合ビューとして扱う。通常取得はHigh優先。作成・完了は確認付きでNotion同期する。親子移動のUI処理は`task-flow.js`へ一本化し、詳細パネルに表示中のタスクIDを更新対象として使い、移動後は同一タスクIDを再取得して新しい親のFocusへ移る。同じ親またはLife直下への重複要求はサーバーでno-opとし、Notion更新を二重登録しない。Life直下Taskを親として2階層まで扱い、親Task詳細から作成した小タスクは親Relationへ接続する。実Notionでの移動・Relation反映E2Eは未確認。
- Project Continuity: 内部project台帳、alias、source link、checkpoint、handoff、cache-first resumeを統合済み。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、実環境設定と会話E2Eは継続確認が必要。
- 今回の検証: `petit-motion.js`、`app_shell.js`、`chat_input.js`、`petit-version.js`、`service-worker.js`のNode構文チェック、CSS括弧対応、通常フェード・共有要素撤去・Lifeカード化・全View統一・スマホ1カラム・390px対応・light/reduced motionを確認する回帰テストを追加した。実データ入りPC、390x844、実iPhone PWA、長時間Orbit負荷は未確認。
- 次にやること: PCブラウザで全Viewの形・余白・情報階層を確認し、390x844でLifeカード、Focus Orbit、詳細パネル、Tasksカード、Chat入力と下部ナビの重なりを確認する。実iPhone PWAでsafe-area、キーボード表示時、低電力モードを確認する。テスト用Notionタスクで親変更とRelation同期もE2E確認する。

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
