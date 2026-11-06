# PETIT Notion Daily Sync (Renaissance)

PETITのタスク操作は**SQLiteで即時完結**させ、Notionとは毎日 **02:00 Asia/Tokyo** にまとめて同期する。
既存の `task_sync_queue` (Outbox)、`notion_task_remote_snapshots`、三者比較を再利用し、別の同期DBは追加しない。

## モード

```env
NOTION_TASK_SYNC_MODE=daily  # daily (default) / legacy / off
NOTION_TASK_BACKGROUND_SYNC_ENABLED=1
NOTION_TASK_DAILY_MAX_WRITES=100
NOTION_TASK_DAILY_WRITE_INTERVAL_SECONDS=0.85
```

- **daily**（推奨・既定）: 通常のタスク追加/編集/完了はローカル反映＋Outbox保存のみ。Workerは午前2時の同期枠まで自動Push/Pull/Webhook inbox処理を行わない。
- **off**: WorkerによるNotion Pull、Outbox Push、Webhook inbox処理をすべて停止。ローカル編集と保留キューは残る。明示的な手動API呼び出しは別途可能。
- **legacy**: 従来の逐次Outbox Push、Webhook inbox、起動時/5分Pull/定期全件Pullへ戻す緊急互換モード。

## 02:00 JSTの手順

1. **最新のNotion全件をPull**（削除確認も含む）。既存キャッシュがあるのに結果が空なら誤削除を避けるため**失敗扱い**。
2. 前回のremote snapshot、PETITローカル、今回Notionの3方向比較。異なるフィールドは統合。同じフィールドの競合、Notion側削除とローカル未同期変更は競合として保留する。
3. 成功したPullの後だけ、競合しなかったOutboxを書き出す。処理数は `NOTION_TASK_DAILY_MAX_WRITES` 上限、Notion API過負荷防止で操作間隔を設ける。
4. **差分Pullで再確認**。Pullが失敗したり未同期/競合が残る場合、`daily_status=failed/partial` として報告する。成功扱いに偽装しない。

`notion_task_sync_state.daily_slot` は直近で到来したJSTの02:00同期枠（YYYY-MM-DD）。
**1枠につき自動実行1回**。PCがスリープ/停止していたら、次回起動後に最新の未実行枠を処理する。失敗した日の自動無限再試行はしない（手動の修復または次の枠を待つ）。

ローカル変更はNotion API失敗でも消去しない。Notionの同期済みと、ローカル編集の保存済みは異なる状態。

## 状況の見方

`notion_task_sync.status()` には以下を出す。

- `mode` と `daily.due_slot`, `daily.last_slot`, `daily.status`, `daily.finished_at`, `daily.error`
- `tasks.pending_writes`, `tasks.failed_writes`, `tasks.conflicts`
- `pull.last_success_at`, `pull.last_error`

`daily.status` は `success`、`partial`、`failed`、実行途中の `running` を区別する。
競合は自動最終更新勝ちとしない。ユーザーが選んだ値で明示解決する。
実データの同期前に既存SQLite DBの整合したバックアップを取る。

## 既知の境界

- この変更は**同期頻度とPush/Pull順**の修正であり、Notionの現行 `2022-06-28` APIを全面更新するものではない。複数Data Source型DBや400/404などの実Notionエラーは別途ログで特定する必要がある。
- Notionが反映まで遅延する場合、差分Pullで最新値が即時読めるとは限らない。外部Writeのexactly-onceは主張しない。
- Notion APIが429・5xxなどで失敗した場合は、その夜の処理をpartial/failedで残し、無制限の即時リトライをしない。
- 手動 `sync_notion_tasks` はPull専用。Outboxの手動フラッシュは別途安全な確認導線を用意するまで自動化しない。
- 標準の`legacy`モードへ戻すとリアルタイム同期になる。利用中のDBはバックアップしてからモード変更すること。

Refs #345
