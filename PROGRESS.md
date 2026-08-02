# PROGRESS — 変更履歴

**Current Version: v0.4.0**  
**Last Updated: 2026-08-02**

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- プロダクトの軸は `PETIT_AS_JARVIS`。現状はFastAPI + ブラウザのテキストチャットMVPで、最終形はスマホとPCの音声中心常駐アシスタント。
- バージョン管理: v0.4.0。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する。
- Life / Focus UI: LifeをPETITのホーム画面として扱い、主要ナビをLife・Focus・Tasks・Chatへ整理した。Life全体は中央のLIFEと親Task星・子Task星が接続された星座マップとして表示し、星を選ぶと拡大しながらFocusへ潜る。reduced-motionでは即時遷移する。既存タスクを親Taskへ移した後は対象の親Taskへ自動移動し、親Task詳細から小タスクを直接追加できる。実データを用いたブラウザ・iPhone PWA E2Eは未確認。
- 制作伴走 / Today: 作業セッションをSQLiteで永続化し、20分ごとの継続確認と無応答時の自動停止をバックグラウンドWorkerで実行する。Todayは今日の合計、作業中状態、セッション数、取り組み数、最長Focus、タイムライン、取り組み別配分とLife・Focusへの行動導線を表示する。実ブラウザ・実Push・iPhone PWA E2Eは未確認。
- 会話 / Agent Runtime: Project Continuity・挨拶・正確な現在時刻だけを決定論的な安全ゲートで処理し、通常会話はChatモデルのCapability Routerが最大4領域を選ぶ。Agentには選択領域内の登録済みToolだけを公開し、既定3ラウンド・Tool総数6・同一Tool同一引数1回の上限、結果圧縮、書き込み承認、30分以内のAgent状態再開、履歴へ残さない進捗表示を実装。確認対象Toolは承認前にschema検証し、親子タスク変更は`set_task_parent`へ集約、Runtime外の重複確認はTool callへ戻す。実装準拠フローは`docs/runtime-flows.md`を正とする。
- 音声: AivisSpeech Engine経由のWAV再生、ブラウザTTS fallback、再試行、直列化、モバイル音声アンロックを実装。実PC／iPhone E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in、通知履歴を実装。実VAPID／HTTPS／バックグラウンド受信は未確認。
- タスク管理: Notionを外部正本、SQLiteをPETITの即時統合ビューとして扱う。通常取得はHigh優先。作成・完了は確認付きでNotion同期する。親子関係と名前の同時変更は1回の`set_task_parent`確認で扱う。Life直下Taskを親として2階層まで扱い、親Task詳細から作成した小タスクは親Relationへ接続する。Notion同期有効時は同期済み親Taskだけを対象にする。実Notionでの作成・Relation反映E2Eは未確認。
- Project Continuity: 内部project台帳、alias、source link、checkpoint、handoff、cache-first resumeを統合済み。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、実環境設定と会話E2Eは継続確認が必要。
- 次にやること: Lifeホームを実データ入りPCブラウザとiPhone PWAで開き、星からFocusへのズーム、親変更後の移動、小タスク追加、Todayの縦幅とタップ領域を確認する。続けて実Notionで親Relation同期を確認する。

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
