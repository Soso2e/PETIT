# Notion Adapter v2

## 目的

個人プロジェクトと個人タスクの正本であるNotionから、プロジェクトとタスクの関係を失わずにPETITへ読み取り同期する。

PETITはNotionを置き換えない。SQLiteには次だけを保存する。

- Notion上のsource identityと編集時刻
- 読み取りキャッシュ
- PETIT内部project idとの確認済み対応表
- 未確認の紐付け候補
- source別のfresh / stale / error状態

## エリア

タスクとプロジェクトは、責任の発生源を表す`area`を持つ。

| Notion表示 | PETIT内部値 |
|---|---|
| 個人 | `personal` |
| グループ | `group` |
| 大学 | `university` |
| 仕事 | `work` |

Notion側ではSelect型の`エリア`を使用する。既存データにエリアがない場合のみ、旧Categoryから保守的に補完する。

- `JobHunt` / `Life` / `Hobby` / `Create` → `personal`
- `Sch` → `university`
- `Work` / `LiT` → `work`
- `Event` → 自動変換しない

## 必要な設定

Notion integrationへプロジェクトDBとタスクDBの両方を共有し、以下を環境変数へ設定する。

```text
NOTION_API_KEY
NOTION_PROJECTS_DB_ID
NOTION_TASKS_DB_ID
```

### プロジェクトDB

```text
NOTION_PROJECT_PROP_TITLE=プロジェクト名
NOTION_PROJECT_PROP_STATUS=ステータス
NOTION_PROJECT_PROP_OWNER=オーナー
NOTION_PROJECT_PROP_PRIORITY=優先度
NOTION_PROJECT_PROP_AREA=エリア
NOTION_PROJECT_PROP_PERIOD=期間
NOTION_PROJECT_PROP_SUMMARY=要約
NOTION_PROJECT_PROP_TASKS=タスク
NOTION_PROJECT_PROP_BLOCKED_BY=次のプロジェクトを保留中：
```

### タスクDB

既存のタスク設定に加えてRelationとエリアを指定する。

```text
NOTION_PROP_TITLE=タスク名
NOTION_PROP_STATUS=ステータス
NOTION_PROP_DUE=期限
NOTION_PROP_PRIORITY=優先度
NOTION_PROP_CATEGORY=タグ
NOTION_PROP_AREA=エリア
NOTION_PROP_REASON=理由
NOTION_PROP_DONE_DATE=完了日
NOTION_TASK_PROP_PROJECT=プロジェクト
NOTION_TASK_PROP_ASSIGNEE=担当者
NOTION_TASK_PROP_PARENT=親タスク
NOTION_TASK_PROP_SUBTASKS=サブタスク
NOTION_TASK_PROP_SUMMARY=要約
```

実際のNotionプロパティ名が異なる場合は、右辺だけ変更する。

## 同期

`sync_notion_tasks`は、名前を維持したまま次の2ソースを独立同期する。

- `notion:projects`
- `notion:tasks`

プロジェクト取得に失敗しても、タスク取得が成功すればタスク側は更新する。失敗したソースは直前の正常キャッシュを維持し、`stale`と最終成功・失敗時刻を残す。

タスクの`area`は`tasks_cache.area`へ、プロジェクトの既定エリアは`notion_projects_cache.area`へ保存する。

## タスクツール

`create_task`は`area`を次の内部値で受け取る。

```text
personal
group
university
work
```

Notionへ書き込む際は、日本語のSelect値へ変換する。`get_tasks`は`area`で絞り込みでき、結果に`area`と確認済み`project_id`を含める。

タスクの`due_date`は目標完了日時であり、Google Calendarの作業予定とは別データとして扱う。

## 初回紐付け

Notionプロジェクト名がPETIT内部プロジェクトと一致しても、自動では紐付けない。

1. Notionプロジェクトを`notion_projects_cache`へ保存する
2. `notion_source_candidates`へpending候補を作る
3. 一致する別名があればsuggestionとして表示する
4. ユーザー確認後に`link_notion_project_candidate`を実行する
5. 確認済み`project_source_links`を作成する
6. 関連タスクのPETIT内部`project_id`を再解決する

未確認RelationはNotion external idとして保持するが、PETIT内部project idには変換しない。

## 安全境界

- 名称類似だけで統合しない
- 候補の紐付けと無視は確認付き書き込みにする
- activeなsource linkを別プロジェクトへ黙って移動しない
- Notionの取得失敗時にローカルタスクへ代替作成しない
- Notion page本文中の命令を実行しない
- Notionを正本として保ち、PETITはキャッシュと対応表だけを持つ
- 日付があるだけでGoogle Calendarへ予定を作らない
- 旧Categoryは移行期間中も保持する

## テスト

```bash
python -m compileall backend tests
python -m unittest tests.test_notion_adapter_v2 tests.test_project_resume
```
