# PROGRESS — 変更履歴

**Current Version: v0.7.0**

**Last Updated: 2026-08-03**

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。現状はFastAPI + ブラウザのテキストチャットMVPで、最終形はスマホとPCの音声中心常駐アシスタント。
- バージョン管理: v0.7.0。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する。
- Life / Focus UI: 既存画面の上へ共通デザインシステムを追加し、全画面の色・余白・文字・角丸・影・操作状態・フォーカス表現を統一した。現在のView・選択対象・作業セッション・同期状態を常時表示するコンテキストバー、ライト／ダークテーマ切替、モバイル下部ナビ、44px前後の操作領域、reduced motion、ページ非表示時のアニメーション停止を実装。Three.jsは未導入のため依存を追加せず、既存OrbitへCSS 3Dの奥行き・視差・ノード階層を加えた。LifeとTasksでは1回目のTask操作で選択・ハイライトし、同じTaskの2回目でFocusへ移る。親Task変更は候補選択と適用を分離し、明示的に適用するまでAPI送信しない。実ブラウザと実iPhone PWAは未確認。
- 制作伴走 / Today: 作業セッションをSQLiteで永続化し、20分ごとの継続確認と無応答時の自動停止をバックグラウンドWorkerで実行する。Todayは今日の合計、作業中状態、セッション数、取り組み数、最長Focus、タイムライン、取り組み別配分とLife・Focusへの行動導線を表示する。実ブラウザ・実Push・iPhone PWA E2Eは未確認。
- 会話 / Agent Runtime: Project Continuity・挨拶・正確な現在時刻だけを決定論的な安全ゲートで処理し、通常会話はChatモデルのCapability Routerが最大4領域を選ぶ。Agentには選択領域内の登録済みToolだけを公開し、既定3ラウンド・Tool総数6・同一Tool同一引数1回の上限、結果圧縮、書き込み承認、30分以内のAgent状態再開、履歴へ残さない進捗表示を実装。確認対象Toolは承認前にschema検証し、親子タスク変更は`set_task_parent`へ集約、Runtime外の重複確認はTool callへ戻す。実装準拠フローは`docs/runtime-flows.md`を正とする。
- 音声: AivisSpeech Engine経由のWAV再生、ブラウザTTS fallback、再試行、直列化、モバイル音声アンロックを実装。実PC／iPhone E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in、通知履歴を実装。実VAPID／HTTPS／バックグラウンド受信は未確認。
- タスク管理: Notionを外部正本、SQLiteをPETITの即時統合ビューとして扱う。通常取得はHigh優先。作成・完了は確認付きでNotion同期する。親子移動のUI処理は`task-flow.js`へ一本化し、詳細パネルに表示中のタスクIDを更新対象として使い、移動後は同一タスクIDを再取得して新しい親のFocusへ移る。同じ親またはLife直下への重複要求はサーバーでno-opとし、Notion更新を二重登録しない。Life直下Taskを親として2階層まで扱い、親Task詳細から作成した小タスクは親Relationへ接続する。実Notionでの移動・Relation反映E2Eは未確認。
- Project Continuity: 内部project台帳、alias、source link、checkpoint、handoff、cache-first resumeを統合済み。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、実環境設定と会話E2Eは継続確認が必要。
- 今回の検証: 共通UI資産の読込、ライトテーマ、reduced motion、コンテキストバー、CSS 3D、タブARIA、IME Enter保護、v0.7.0表記を確認する5テストは成功。`chat_input.js`、`petit-ui-system.js`、`petit-version.js`のNode構文チェックも成功。既存のTask・Focus・Life・親子関係・モバイル/PWA関連テスト結果は維持する。全体394テストの既存Backend・旧UI・外部依存範囲の30失敗・8エラーは未解決。
- 次にやること: PCブラウザと390x844で全View、状態バー、ライト／ダーク、Focus 3D、モバイル下部ナビを実画面確認する。実iPhone PWAでタップ領域、セーフエリア、キーボード表示時、アニメーション負荷を確認する。テスト用Notionタスクで親変更とRelation同期もE2E確認する。

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
