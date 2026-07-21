# PETIT タスク・スケジュール管理 v1

更新日: 2026-07-21

## 目的

- Notion: 個人タスク・プロジェクトの正本
- SQLite: 高速表示と承認済み変更のローカルミラー
- Google Calendar: 固定予定の正本（Phase 3）

タスクの期限と、実際に時間を確保する予定は別データとして扱う。

## 概念

### エリア

責任の発生源を表す。

- `personal`: 個人
- `group`: グループ
- `university`: 大学
- `work`: 仕事

### プロジェクト

複数タスクで達成するまとまり。PETIT内部プロジェクトと、確認済みNotion Project Relationを利用する。

### タスク

主なフィールド:

- `title`
- `status`
- `area`
- `project_id`
- `project_external_id`
- `due_date`
- `priority`
- `reason`
- `done_date`
- `sync_status`

### 予定

実行日時を確保したイベント。タスク期限とは分離する。

## Phase 1 — エリア・プロジェクト分類（完了）

- `tasks_cache.area`
- Notionタスク・プロジェクトの`エリア`
- 旧Categoryからの保守的なarea変換
- `create_task`のarea・確認済みproject Relation
- `get_tasks`のarea・project絞り込み
- 既存DBとの後方互換

旧Categoryは削除せず、次の暫定変換だけを行う。

```text
Sch      → university
Work     → work
LiT      → work
Life     → personal
Hobby    → personal
Create   → personal
JobHunt  → personal
Event    → unknown
```

`Create`を共同制作と決めつけて`group`へ変換しない。

## Phase 2 — ローカル即時保存とNotion非同期同期（実装済み）

### 基本フロー

```text
ユーザーが変更内容を確認
→ SQLiteへ即時反映
→ sync_status=pending
→ Notion書き込みキュー
→ 成功: synced
→ 通信失敗: failed
→ Notion側にも変更: conflict
```

承認前にはSQLite・Notionのどちらも変更しない。

### 同期状態

| 状態 | 意味 |
|---|---|
| `pending` | ローカル反映済み、Notion同期待ち |
| `synced` | Notionと同期済み |
| `failed` | 通信・API失敗。ローカル内容とエラーを保持 |
| `conflict` | ローカル編集中にNotion側も更新。自動上書きを停止 |

`tasks_cache`には次を保持する。

- `sync_status`
- `sync_error`
- `sync_operation_id`
- `sync_attempts`
- `last_synced_at`
- `remote_snapshot_json`

### 書き込みキュー

`task_sync_queue`へ次を保存する。

- 対象タスク
- `create` / `update`
- 承認済みpayload
- 編集開始時のNotion更新時刻
- 試行回数
- 次回再試行時刻
- エラー
- 同期完了時刻

失敗時は指数バックオフで最大5回まで再試行する。手動再試行では試行回数をリセットする。

### 作成

Notion設定時の`create_task`:

1. SQLiteへ`source=notion`、`sync_status=pending`で作成
2. 確認済みProject Relationだけをpayloadへ含める
3. Notion作成成功後、同じSQLite行へpage ID・URL・source更新時刻を反映

Notion未設定時は従来どおり`source=local`で保存する。

### 編集・完了

- `update_task`: 名前、状態、期限、優先度、エリア、プロジェクト、Category、理由、完了日を編集
- `complete_task`: ローカルへ即時完了反映し、Notion更新をキューへ追加
- Notionへ未送信のcreateがある場合、後続編集を同じcreate payloadへ統合
- ローカルタスクはNotionキューを作らない

### 失敗・再試行

- `get_task_sync_status`: 状態、失敗理由、試行回数、競合時のNotion側スナップショットを取得
- `retry_task_sync`: `failed`操作を確認付きで再試行
- `conflict`は自動再試行しない

### 競合

Notion読取同期でsource更新時刻が変わっており、ローカルに未同期変更がある場合:

1. ローカル編集内容を維持
2. Notion側の最新値を`remote_snapshot_json`へ保存
3. `sync_status=conflict`
4. キューを停止
5. ユーザーが両方を確認して`update_task`を再実行

Notion側の新しい内容を無言で上書きしない。

### 表示

`get_tasks`は外部同期を待たずSQLiteから返し、各タスクへ同期状態を含める。明示的なNotion同期は`sync_notion_tasks`で実行する。

## Phase 3 — Google Calendar連携（未実装）

- Google Calendar OAuth書き込み
- タスク期限と作業予定の関連付け
- 固定予定・期限・期限切れ・次の一手の統合表示

日付があるだけでCalendarへ予定を作成しない。

## 安全境界

- NotionとSQLiteを両方正本にしない
- 未確認Relationを内部projectへ変換しない
- 名称類似だけでプロジェクトを統合しない
- 既存Categoryを削除しない
- Notion側の更新を無言で上書きしない
- conflictを自動解決しない
- タスク期限とCalendar予定を混同しない
- DB移行は追加テーブル・追加カラムで行う

## テスト

```bash
python -m compileall backend tests
python -m unittest \
  tests.test_notion_adapter_v2 \
  tests.test_project_resume \
  tests.test_task_write_queue -v
```

主な回帰項目:

- 作成直後にSQLiteから取得できる
- 成功時に同じ行が`synced`になる
- 失敗時にタスクとエラーが失われない
- 手動再試行できる
- 編集・完了がpendingキューへ入る
- 未送信createへ編集を統合できる
- Notion側変更を`conflict`として検出する
- conflict時にローカル内容を維持する
- ローカルタスクはNotionへ送らない
