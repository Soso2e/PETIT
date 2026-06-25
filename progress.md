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
