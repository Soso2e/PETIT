# PETIT v0.41.0 — Chat-first UI / Dashboard

## 今回決めた体験

- **Chat / Univ / Develop / Dashboard** の4領域が主ナビ。 `/?view=chat` を初期画面とし、 `/?view=dashboard` は既存 `today` パネルの別名。過去の `?view=univ`、`?view=tasks`、`?view=today` と直接リンクは維持。
- Desktopでは常駐ElectronのワークスペースがWeb配信の同じUIを使用するため、Electron本体の変更・再配布なしで4領域が反映される。小型会話画面から「メイン画面」に開く入口を継続。
- iPhone/PWAは下部固定の4タブ。通知/設定は右上の補助導線。タスク一覧とリマインダーは補助機能として残す。
- UnivのThree.js 3D（既存WebGL描画、ラベル、fallback）は変更しない。
- DevelopのCLI Coding Jobs、承認・取消・レビューは既存API/画面を保持。Developは将来的にPETIT司令塔のプロジェクト別スレッドへ拡張する。

## Dashboardで再利用する正本

- `backend/work_sessions.py`: `work_sessions` と `work_session_events` が作業時間の正本。pause/stopイベントを考慮し、JSTの日境界で日ごとの経過秒数を計算。
- `GET /api/work-sessions/today`: 本日の合計、タスク、プロジェクト、セッション、活動中のセッション。既存UIのまま。
- `GET /api/work-sessions/summary?days=7`: 既存7日間の棒グラフの正本。
- `GET /api/work-sessions/summary?days=90`: **新規APIではない**。今回の90日カレンダーに使用。最後の7日/30日の秒数と30日内の活動日数をクライアント側で算出。
- `GET /api/work-sessions/days/YYYY-MM-DD`: カレンダーセル選択時に既存の日付入力へchangeを送ってその日のセッションと振り返りを表示。
- 記録されていない日は「0分」、通信や形式に失敗した場合は「取得できませんでした」。架空の作業時間で埋めない。
- Coding JobのCPU/経過時間は**自分の作業時間**に混ぜない。

## 既知の非対応・次の段階

- 現在のDevelopの詳細画面はジョブ中心で、会話Threadから繰り返し開発を頼む状態はまだない。
- Electron小型会話とワークスペース間の入力・会話状態の完全な同期は別実装が必要（現行のCore Thread/Turnをそのまま利用したい）。
- Calendar独立タブ、PC操作の自動時間計測、AI Coding Jobの稼働時間と自分の作業時間の比較は今回含めない。
- 現行の非UI基盤（DBや承認・CLI・通知・Three.js）に破壊的変更をしない。
- Windows/macOS/iPhone実機表示・実Codex/agyジョブは要受入。GitHubのJS/CI通過と実端末動作は同一ではない。

## 受入確認

1. `/` または `/static/universe.html` を開くとChat。ページリロードと `?view=univ`、`?view=dashboard` の遷移ができる。
2. Desktop ElectronメインウィンドウからChat / Univ / Develop / Dashboardに切り替えられる。小型会話を開いても新しいWeb画面の変更がサーバー経由で反映される。
3. iPhoneの390pxと320pxで下部4タブが表示され、通知・設定と重ならない。
4. Dashboardの90日カレンダー、7日・30日合計・活動日数を既存`/api/work-sessions/summary?days=90`と照合する。日を選ぶと正しい日別記録が開く。pause/日跨ぎデータでも過大計上しない。
5. ネットワーク不通、管理者認証、WebGL失敗時に誤った成功・作業時間を表示しない。

## v0.46.0 — スマホの共通ヘッダーとシンプルなChat

Status: 現行（iPhone実機は未確認）

- 959px以下では4領域とReminders / Settingsが同じヘッダーを使う。左に画面名と同期状態・バージョン、右に作業タイマー・通知・設定を固定し、タブを移っても位置が変わらない。
- 以前はChatだけ `petit-ui-polish.css` の専用ルールで通知/設定ボタンが「作業なし」バーの下に移っていた。このルールは撤去した。
- ワークセッションの全幅バーは、ヘッダーのタイマーボタンに畳んだ。作業中は「作業中：タスク名」のピルになり、押すと従来と同じ詳細（開始・一時停止・終了・タスク詳細）が開く。
- 下部タブは画面端に接するバーにした。選択中はアイコン背景で示す。
- Chatはヘッダーと下部タブの間に収め、入力欄が下部タブに隠れていた不具合を直した。会話切替・新しい会話・ローカル専用・最新の依頼・音声入力方式は「会話」メニューにまとめた。依頼結果の再取得やエラーがあるときはメニューに点を付ける。画像添付は入力欄左の＋にし、説明文はボタンのtitleに移した。進捗やエラーのときだけ表示する。
- iOSの自動ズームを避けるため、入力欄は16px。
- 実装: `frontend/petit-mobile-chrome.css`（最後に読み込む見た目の層）、`frontend/chat-tidy.js`（既存のChat部品をメニューと入力欄へ付け替えるだけ。APIは呼ばない）。
- 受入: iPhoneのSafari / PWAで、4タブを行き来しても通知・設定の位置が変わらないこと。キーボード表示中も入力欄が隠れないこと。「会話」メニューから会話を切り替えられること。
