# Progress Log

---

## 2026-06-25 / 第0回実行（初期状態）

### 目的
- プロジェクト PETIT の設計・方針を整理する

### 実施内容
- Concept.md を作成し、Personal AI Assistant の開発方針を定義した
- 目的・基本方針・中核設計・MVP・技術構成・データ設計・開発フェーズを記述
- TimeTree は公式 API 終了・外部連携弱・スクレイピング不安定のため MVP では直接連携しないと決定

### 変更ファイル
- `Concept.md`（新規）

### 確認・テスト
- 未実施

### 問題・保留
- TimeTree 連携は「後回し」として Concept.md に明記されている
- Apple Reminders 取得の最小検証（Mac）が未着手
- Notion DB 構造の確認が未着手
- Tool Router の最小実装が未着手

### 次回
- 特になし（第1回で TimeTree バックアップを着手）

---

## 2026-06-25 / 第1回実行

### 目的
- TimeTree のスケジュールを毎日どこかに自動保存する仕組みを作る

### 実施内容
- TimeTree に iCal 購読 URL があると仮定して最初の実装を行ったが、誤りだと判明
- TimeTree-Exporter（[eoleedi/TimeTree-Exporter](https://github.com/eoleedi/TimeTree-exporter)）を調査
  - 非公式 Web API をリバースエンジニアリングした OSS
  - `pip install timetree-exporter` でインストール可能
  - `TIMETREE_EMAIL` / `TIMETREE_PASSWORD` の環境変数で非対話実行可能
  - `-c CALENDAR_CODE` でカレンダーを指定、`-o` で .ics ファイル出力
- `tools/timetree_backup.py` を実装
  - `timetree-exporter` を subprocess で呼び出して .ics を取得
  - `icalendar` ライブラリでパース
  - SQLite（`storage/app.db` → `calendar_events_cache` テーブル）に全イベントを upsert
  - Markdown（`storage/logs/YYYY-MM-DD.md`）に今日 ±7 日分を出力
- `scripts/setup_daily_backup.sh` を実装
  - Mac: launchd（`~/Library/LaunchAgents/com.petit.timetree-backup.plist`）で毎朝 6:00 自動実行
  - Linux: cron に登録
- `.env.example` を作成（`TIMETREE_EMAIL` / `TIMETREE_PASSWORD` / `TIMETREE_CALENDAR_CODE`）
- `.gitignore` を作成（`.env` / `storage/app.db` / `storage/logs/` を除外）
- `CLAUDE.md` を作成（Progress Log ルールを記載）

### 変更ファイル
- `tools/timetree_backup.py`（新規）
- `scripts/setup_daily_backup.sh`（新規）
- `.env.example`（新規）
- `.gitignore`（新規）
- `CLAUDE.md`（新規）

### 確認・テスト
- 環境変数未設定時のエラーメッセージを手動確認 → 正常に ValueError が出ることを確認
- TimeTree への実際のログイン・イベント取得は未実施（認証情報なし）

### 問題・保留
- timetree-exporter は非公式 OSS のため、TimeTree 側の仕様変更で突然動かなくなるリスクがある
- カレンダーコードの確認は初回だけ対話実行が必要（`timetree-exporter -e your@email.com`）
- 実際の .ics パース・保存フローは本番環境での動作未確認

### 次回
- 実際の `TIMETREE_EMAIL` / `TIMETREE_PASSWORD` / `TIMETREE_CALENDAR_CODE` を設定してエンドツーエンドで動作確認する
- 動作確認後、Mac の launchd か cron に登録して毎日自動実行を有効化する

---

## 2026-06-25 18:17 / 第2回実行

### 目的
- 会話を通じてユーザーのデータ（好み・作業中の内容・タスク）を自動で蓄積し、N時間おき/日次で要約して長期記憶に貯めていく「自律的な記憶蓄積」を実装する
- 蓄積データの後利用のため、Obsidian 形式の Markdown 副本を出力する

### 実施内容
- 設計判断: 役割分担を「SQLite=正本 / Chroma=意味検索 / Markdown(Obsidian)=人が読む副本」に明確化。md は AI の検索正本にはしない。
- `backend/markdown_export.py`（新規）: Obsidian 形式で追記専用出力。`AI_Daily/YYYY-MM-DD.md`（YAMLフロントマター + 会話ログ + まとめ）と `AI_Memory/<type>.md`（ウィキリンク付き）。書き込み失敗してもサーバーを落とさない best-effort。
- `backend/summarizer.py`（新規）: 未要約の会話を集め、LLM に要約 + facts + work_in_progress を JSON で出させて SQLite(summaries) / Chroma(petit_summaries) / Markdown に蓄積。抽出した事実は memory テーブルへ自動保存（会話からデータが育つ）。LM Studio 不在時は例外で止めず status を返す。JSON はコードフェンス/前置き文ありでも抽出できる。
- `backend/scheduler.py`（新規）: 標準ライブラリ threading の daemon ループで N時間おきに summarize。1日の最初のティックは kind="daily"。例外はループを殺さない。
- `backend/db.py`: `summaries` テーブル追加 + ヘルパー（last_summarized_conv_id / conversations_after / save_summary / recent_summaries）。
- `backend/config.py`: AI_DAILY_DIR / AI_MEMORY_DIR / AUTO_SUMMARY_ENABLED / SUMMARY_INTERVAL_HOURS / SUMMARY_MIN_CONVERSATIONS を追加（全て環境変数で上書き可）。
- `backend/main.py`: 起動時にスケジューラ開始・終了時に停止、各会話ターンを Obsidian md に追記、`/api/summarize`（手動トリガー）と `/api/summaries` を追加、/api/health に auto_summary / markdown 情報を追加。
- `backend/tools/memory.py`: `summarize_now` ツール追加、search_memory が要約(summaries)も検索対象に（セマンティック・キーワード両方）。
- `backend/agent.py`: システムプロンプトに「会話を通じて記憶を蓄積し、自動でまとまる」旨を追記。

### 変更ファイル
- `backend/markdown_export.py`（新規）
- `backend/summarizer.py`（新規）
- `backend/scheduler.py`（新規）
- `backend/db.py` / `backend/config.py` / `backend/main.py` / `backend/agent.py` / `backend/tools/memory.py`
- `PROGRESS.md`

### 確認・テスト
- スモークテスト実施（LM Studio はスタブ）: init_db で summaries 作成、会話シード→要約→SQLite/Markdown 永続化、facts/work_in_progress が memory に自動保存、2回目は未処理ゼロでスキップ（冪等）を確認。
- JSON 抽出のロバスト性（コードフェンス/前置き文あり）を確認。
- FastAPI アプリの import とツール登録（summarize_now を含む）を確認。
- LM Studio 不在時に summarizer が例外を投げず status を返すこと、スケジューラのティックが例外を握りつぶすこと、kind の interval→daily ローテーションを確認。
- 実 LM Studio・実 embedding での E2E は未実施（この環境にローカル LLM がないため未確認）。

### 問題・保留
- 実 LM Studio での要約品質・JSON 安定性は未確認（モデル依存）。temperature=0.2 で安定化を狙っている。
- スケジューラはプロセス内 threading のため、サーバー停止中は要約が走らない。常駐前提でない運用では将来 cron/launchd 化を検討。
- 自動抽出した記憶の重複排除は未実装（同じ事実が複数回保存されうる）。

### 次回
- 実 LM Studio 接続での要約 E2E と JSON 安定性の確認
- 記憶の重複排除 / 古い要約のロールアップ（日次→週次）の検討
- フロントエンドに要約タイムライン表示を追加するか検討
