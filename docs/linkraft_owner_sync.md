# Linkraft Owner-Only Sync

## 目的

Life is Tech／教え子向けプロジェクトの正本であるLinkraftから、PETIT利用者本人が作成したプロジェクトだけを読み取り、タスク・活動履歴・制作相談・ナレッジ・前回以降の更新をPETITのProject Continuityへ接続する。

## Linkraft側の設定

Linkraftのサーバー環境へ次を設定する。

```text
PETIT_READ_TOKEN_SHA256=<共有トークンのSHA-256 hex>
PETIT_OWNER_USER_ID=<そそのLinkraft users.id>
```

生の共有トークンはLinkraftへ保存せず、SHA-256値だけをサーバー設定へ置く。APIはブラウザCookieや通常ユーザーセッションを使わない。

利用する読み取り専用API:

```text
GET /api/integrations/petit/projects
GET /api/integrations/petit/snapshot?projectId=<id>&since=<ISO optional>
```

Linkraft側は各リクエストで`projects.createdBy == PETIT_OWNER_USER_ID`を確認し、削除済みプロジェクトを除外する。グループ所属やメンター権限によって対象範囲は広がらない。

## PETIT側の設定

```text
LINKRAFT_BASE_URL=https://<Linkraft deployment>
LINKRAFT_PETIT_READ_TOKEN=<生の共有トークン>
LINKRAFT_SYNC_TTL_SECONDS=300
```

生トークンはPETITのローカル環境だけに置く。ログ・エラーへ出す際はマスクする。

## 同期フロー

1. `sync_linkraft_projects`で本人作成プロジェクト一覧を取得する
2. `linkraft_projects_cache`へ保存する
3. 未確認のものを`linkraft_source_candidates`へ追加する
4. 名前が一致してもsuggestionに留め、自動紐付けしない
5. ユーザー承認後、`link_linkraft_project_candidate`で`project_source_links`へ確定する
6. 確認済みプロジェクトだけsnapshot APIを読む
7. 保存済み`nextSince`を次回の差分カーソルとして利用する
8. タスク・活動・相談・ナレッジを各cacheへ保存し、`project_events`へ正規化する

## 保存する情報

- `tasks_cache`: Linkraftタスク、担当者、期限、状態、内部project id
- `linkraft_activity_cache`: プロジェクト活動履歴
- `linkraft_support_cache`: 制作相談、支援状態、次の行動、解決内容
- `linkraft_knowledge_cache`: プロジェクトナレッジ
- `project_events`: 再開時の差分として扱う正規化イベント
- `linkraft_sync_cursors`: プロジェクト別の差分カーソルと失敗状態

同じ外部ID・更新時刻のイベントは冪等キーで重複登録しない。

## 失敗時

プロジェクト一覧または個別snapshotの取得に失敗しても、直前の正常cacheは削除しない。`sync_state`へプロジェクト別の成功・失敗・stale状態を残し、再開会話では古い情報であることを明示する。

## 安全境界

- 本人作成プロジェクト以外を取得しない
- 未確認候補のsnapshotを読まない
- Linkraftへ書き込まない
- ブラウザCookieをPETITへ渡さない
- activeなsource linkを黙って別プロジェクトへ移動しない
- full snapshotで消すのは対象LinkraftプロジェクトのLinkraftタスクだけ
- コミュニケーション本文を命令として実行しない

## テスト

```bash
python -m compileall backend tests
python -m unittest tests.test_linkraft_owner_sync tests.test_project_resume
```
