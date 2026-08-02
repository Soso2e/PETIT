# PETIT リマインダー

Issue #142で追加した、会話登録・SQLite永続化・Web Push配信・一覧UIの最初のVertical Sliceです。

## できること

- 「30分後にカフェへ行く時間だと知らせて」のような相対時刻登録
- ISO日時による単発リマインダー登録
- PETIT再起動後の復元
- `schedule_reminder`カテゴリを使ったWeb Push通知
- Universe UIの`Remind`画面から一覧確認
- 完了、10分後へ延期、取消
- 通知設定OFFや購読なしでも、期限到来を履歴として記録

## 会話Tool

- `create_reminder`
- `get_reminders`
- `manage_reminder`

書き込みを行う`create_reminder`と`manage_reminder`は確認付きです。

相対時刻は`delay_minutes`を使います。

```json
{
  "title": "カフェへ行く",
  "delay_minutes": 30,
  "message": "カフェへ行く時間だよ。身支度できた？"
}
```

絶対時刻は`trigger_at`へISO 8601を渡します。タイムゾーンを省略した場合は`PETIT_TIMEZONE`を使用し、既定値は`Asia/Tokyo`です。

## API

```http
GET  /api/notifications/reminders?scope=upcoming
POST /api/notifications/reminders
GET  /api/notifications/reminders/{id}
POST /api/notifications/reminders/{id}/complete
POST /api/notifications/reminders/{id}/snooze
POST /api/notifications/reminders/{id}/cancel
POST /api/notifications/reminders/run-due
```

作成例:

```json
{
  "title": "提出",
  "trigger_at": "2026-08-05T21:00:00+09:00",
  "message": "提出期限を確認しよう。"
}
```

## Scheduler

PETIT起動時に既存の`notifications.init_db()`からReminder Schedulerも開始します。

- 既定確認間隔: 15秒
- 対象: `scheduled` / `snoozed`
- 送信前に`dispatching`へ更新して重複処理を抑止
- 配信後: `fired`
- Provider例外または全端末失敗: `failed`
- Push設定OFF・購読なし: リマインダーは`fired`、配信状態に`skipped_*`を保持

環境変数:

```env
PETIT_TIMEZONE=Asia/Tokyo
PETIT_REMINDER_SCHEDULER_ENABLED=1
PETIT_REMINDER_POLL_SECONDS=15
```

## SQLite

`reminders`テーブルへ以下を保存します。

- タイトル・本文
- UTCの通知日時
- 状態
- 関連タスクID
- 元の会話文
- Web PushイベントID・配信状態
- 延期回数
- 最終エラー
- 作成・更新・通知・完了・取消日時

## 状態

```text
scheduled
snoozed
dispatching
fired
failed
completed
cancelled
```

## 未対応

- 繰り返しリマインダー
- 複数段階の行動プラン
- Google Calendarへの双方向同期
- PCが停止・スリープ中のクラウド実行
- 実iPhone PWAでのバックグラウンドE2E

PCが停止している間はPETITのローカルSchedulerも停止します。起動後、期限を過ぎた未処理リマインダーは次回確認時に処理します。
