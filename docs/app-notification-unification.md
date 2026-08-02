# Webアプリ構造と通知・会話継続の統一

Issue #162の実装基準です。

## UI

主要導線は5つ以内にします。

```text
Today
Focus
Tasks
Chat
More
  ├─ Reminders
  ├─ Notifications
  ├─ Calendar (read-only)
  └─ Settings
```

Universeは見た目を担当し、チャット入力、履歴、音声、承認、作業セッション、通知は共通ロジックを利用します。

## カレンダーとリマインダー

TimeTreeを予定の原本として扱い、PETITのカレンダー連携は読み取り専用とします。

次の発話はカレンダー予定ではなくPETIT内部Reminderです。

```text
20:30になったら帰ろうかな
22時には寝ようかな
30分後にカフェへ行こう
```

予定の開始・終了・参加者を明示していない、未来時刻付きの単一行動はReminderを優先します。

## 通知

通知判断と配信を分離します。

```text
Reminder / Work Session / Task Follow-up
  -> Notification EventをSQLiteへ保存
  -> 購読・設定が有効ならWeb Push
  -> Push失敗・購読なしでも通知センターへ残す
```

初期カテゴリ:

- `schedule_reminder`: 明示的リマインダー
- `work_session`: 作業継続確認
- `task_follow_up`: タスク再開確認
- `chat_follow_up`: チャットへ戻す継続メッセージ

## 会話分割

会話は最後のユーザーメッセージから2時間を境界にします。

- 1時間59分: 同じconversation
- 2時間00分以上: 次のユーザーメッセージで新しいconversation
- 空のconversationは作らない
- 内部通知や伴走イベントはユーザー発話として表示しない

現状のフロント側2時間判定は互換用として残し、最終的にはバックエンドを正とします。

## Web Push実機検証

前提:

- HTTPSまたはlocalhost
- VAPID設定済み
- `pywebpush`導入済み
- iPhoneではSafariからホーム画面へ追加したPWAを使用

確認手順:

1. `GET /api/notifications/status`で`configured`と依存状態を確認
2. PWAの操作から通知許可を要求
3. 購読件数が1以上になることを確認
4. テスト通知を送信
5. PWAを閉じ、iPhoneをロックして受信確認
6. 通知タップで対象画面が開くことを確認
7. `20:30になったら帰ろうかな`を登録
8. Reminders一覧へ表示されることを確認
9. 指定時刻に通知イベントとPush配信結果が残ることを確認
10. 作業開始後の継続通知、一時停止・終了後の停止を確認

## 完了判定

自動テストだけでは実Web Push成功扱いにしません。実機結果は次を記録します。

```text
- OS / iOS:
- ブラウザ / PWA:
- HTTPS URL:
- PETIT commit:
- 通知許可:
- 購読保存:
- テスト通知:
- Reminder通知:
- Work Session通知:
- 通知タップ:
- 解除後に届かない:
```
