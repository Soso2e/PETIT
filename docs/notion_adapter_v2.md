# Notion Adapter v2

## 目的

個人プロジェクトと個人タスクの正本であるNotionから、プロジェクトとタスクの関係を失わずにPETITへ読み取り同期する。

PETITはNotionを置き換えない。SQLiteには次だけを保存する。

- Notion上のsource identityと編集時刻
- 読み取りキャッシュ
- PETIT内部project idとの確認済み対応表
- 未確認の紐付け候補
- source別のfresh / stale / error状態

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
NOTION_PROJECT_PROP_PERIOD=期間
NOTION_PROJECT_PROP_SUMMARY=要約
NOTION_PROJECT_PROP_TASKS=タスク
NOTION_PROJECT_PROP_BLOCKED_BY=次のプロジェクトを保留中：
```

### タスクDB

既存のタスク設定に加えてRelationを指定する。

```text
NOTION_PROP_TITLE=タスク名
NOTION_PROP_STATUS=ステータス
NOTION_PROP_DUE=期限
NOTION_PROP_PRIORITY=優先度
NOTION_PROP_CATEGORY=タグ
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

## テスト

```bash
python -m compileall backend tests
python -m unittest tests.test_notion_adapter_v2 tests.test_project_resume
```
