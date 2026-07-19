# PETIT タスク・スケジュール管理 v1

更新日: 2026-07-20

## 目的

Notionをタスク・プロジェクトの正本、SQLiteを高速なローカルミラー、Google Calendarを固定予定の正本として扱い、PETITから自然言語で操作できるようにする。

既存のNotion Adapter v2、`tasks_cache`、Project Continuity Engineを壊さずに拡張する。

## 概念

### エリア

作業を行う責任の発生源。

- `personal`: 個人
- `group`: グループ
- `university`: 大学
- `work`: 仕事

### プロジェクト

複数のタスクで達成するまとまり。PETIT内部プロジェクトとNotionプロジェクトの確認済み対応関係を利用する。

### タスク

実際に行う一つの行動。

初期フィールド:

- `title`
- `status`
- `area`
- `project_id`
- `project_external_id`
- `due_date`
- `priority`
- `reason`
- `done_date`

### 予定

実行日時を確保したイベント。タスクの期限とは分離し、既存のcalendar cacheと将来のGoogle Calendar書き込みへ接続する。

## 既存実装との対応

現在のPETITには以下が存在する。

- `tasks_cache`: Notionとローカルタスクの統合キャッシュ
- `create_task` / `get_tasks` / `complete_task`
- Notion Adapter v2によるプロジェクトRelation保持
- `project_source_links`による確認済み外部プロジェクト紐付け
- `calendar_events_cache`

v1ではこれらを置き換えず、足りない`area`と同期状態を追加する。

## Phase 1: area対応の最小縦切り

### SQLite

`tasks_cache`へ追加する。

```sql
area TEXT
sync_status TEXT NOT NULL DEFAULT 'synced'
last_synced_at TEXT
sync_error TEXT
```

`area`は4値だけを受け付ける。

```text
personal
group
university
work
```

### 設定

追加候補:

```text
NOTION_PROP_AREA=エリア
NOTION_PROJECT_PROP_AREA=エリア
```

プロパティがNotion側に存在しない期間も旧DBを読み書きできるよう、area書き込みは明示設定時のみ有効にする。

### Notion Adapter

- タスクページから`area`をselect/statusとして読み取る
- プロジェクトページから既定areaを読み取る
- タスク自身にareaがなければ、確認済みプロジェクトの既定areaを利用する
- 未確認Relationから内部projectやareaを推測しない

優先順位:

```text
明示されたタスクarea
→ 確認済みプロジェクトの既定area
→ 旧Category変換
→ unknown
```

### 旧Category移行

暫定変換:

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

`Create`は共同制作か判定できないため、自動で`group`にしない。

### create_task

引数に追加する。

```json
{
  "area": "personal | group | university | work",
  "project_id": "PETIT内部project id（任意）"
}
```

動作:

1. areaが明示された場合はその値を使用
2. project_idに確認済みNotion source linkがある場合、Notion Relationを付与
3. area省略時は確認済みプロジェクトの既定areaを利用
4. 分類不能なら勝手に決めず、areaなしで保存する
5. Notion失敗時にローカルへ黙って代替保存しない既存境界を維持する

### get_tasks

返却項目に追加する。

```text
area
project_id
project_external_id
sync_status
```

絞り込み候補:

```text
area
project_id
status
due_before
due_after
```

## Phase 2: 非同期同期キュー

Phase 1完了後に実装する。

- ローカル書き込みを即時成功として返す
- Notion書き込みを`pending`としてキューへ入れる
- 成功時`sync_status=synced`
- 失敗時`failed`と`sync_error`を保持
- Notionとローカル両方が更新された場合`conflict`

この段階で初めて、Notion障害時のローカル先行保存を許可する。

## Phase 3: スケジュール

- Google Calendar書き込みアダプター
- タスク期限と作業予定を別データで保持
- タスクと予定の関連付け
- `今日何する？`で固定予定、期限、期限切れ、次の一手を統合表示

## 安全境界

- エリアとプロジェクトを同じ分類として扱わない
- 日付があるだけでGoogle Calendarへ登録しない
- 未確認Notion RelationをPETIT内部projectへ変換しない
- 類似名称だけでプロジェクトを自動統合しない
- NotionとSQLiteの両方を正本にしない
- 既存Categoryを即削除しない
- DB移行は追加カラムから始め、既存データを保持する

## テスト

Phase 1で追加するテスト:

- area明示でローカルタスクを作成できる
- 不正areaを拒否する
- 旧Categoryからareaへ暫定変換できる
- タスクareaがプロジェクト既定areaより優先される
- 未確認Relationからareaを推測しない
- Notion areaプロパティ未設定でも既存同期が動く
- `get_tasks`がareaとproject情報を返す
- DB初期化で既存`tasks_cache`へ安全にカラム追加できる

実行:

```bash
python -m compileall backend tests
python -m unittest tests.test_tasks tests.test_notion_adapter_v2 tests.test_project_resume
```

## 実装順

1. `config.py`へarea設定を追加
2. `db.py`で`tasks_cache`へarea・同期状態を追加
3. `notion_client.py`のparse/writeへarea・project Relationを追加
4. `backend/tools/tasks.py`へarea引数、解決規則、返却値を追加
5. Notion Adapter v2のキャッシュ更新へareaを通す
6. テスト追加
7. READMEと`.env.example`更新

## 完了条件

- 既存Notion DB構成のまま回帰テストが通る
- `エリア`プロパティを追加したNotion DBでも読み書きできる
- PETITから作成したタスクにareaと確認済みproject Relationが保存される
- `get_tasks`がSQLiteから即時にarea付きタスクを返す
- タスク期限と予定日時を混同しない
