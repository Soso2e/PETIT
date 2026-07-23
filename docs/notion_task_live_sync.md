# Notionタスクのローカルファースト双方向同期

## 目的

PETITの会話をNotion API待ちで止めず、NotionをスマートフォンやPCから直接編集できる状態を両立する。

- Notion: 人間が編集する外部正本
- SQLite: PETITが即時に読む統合済み実行状態
- `task_sync_queue`: PETITからNotionへ送るOutbox
- `notion_task_inbox`: Notion Webhookを受けるInbox
- 定期差分同期: Webhook未設定・停止・取りこぼしの補修
- 日次全件同期: 削除や長期的な不整合の補修

通常の`get_tasks`はSQLiteだけを読み、LLMもNotion APIを直接待たない。

## データフロー

### PETITから変更

```text
承認
  → tasks_cacheを即時更新
  → task_sync_queueへ同一操作を保存
  → 会話へ即時応答
  → WorkerがNotionへ送信
  → synced / failed / conflictを記録
```

### Notionから変更

```text
Notionで変更
  → POST /api/notion/webhook
  → HMAC-SHA256署名検証
  → notion_task_inboxへ冪等保存
  → Workerが対象ページだけ再取得
  → remote snapshotとローカル変更を三者比較
  → SQLiteの統合ビューを更新
```

Webhookイベントは変更内容そのものではなく変更通知として扱い、対象ページをNotion APIから再取得する。

### 補修同期

```text
起動時: 初回は全件、以後は差分同期
5分ごと: last_edited_timeによる差分同期
1日ごと: 全件同期と削除確認
```

Webhookを設定していない環境でも、定期同期だけで利用できる。

## マージと競合

`notion_task_remote_snapshots`へ最後に確認したNotion状態を保存し、次の3状態を比較する。

```text
base   = 最後に同期したNotion状態
local  = PETITが現在見ている状態
remote = 今回取得したNotion状態
```

- PETITだけが変えた項目: OutboxでNotionへ送る
- Notionだけが変えた項目: SQLiteへ自動反映する
- 別々の項目を両方が変更: 自動マージする
- 同じ項目を異なる値へ変更: `conflict`にしてローカル値を保持し、Notion値を`remote_snapshot_json`へ保存する
- Notion削除とローカル未同期変更が競合: 削除せず`conflict`にする

同期中のデータ損失を避けるため、競合は自動で最終更新勝ちにしない。

## Webhook設定

Notion WebhookはSSL対応の公開URLが必要で、localhostへ直接配送できない。ローカルPETITを使う場合はCloudflare Tunnelなどで次のエンドポイントだけを公開する。

```text
https://<public-host>/api/notion/webhook?key=<NOTION_WEBHOOK_ENDPOINT_SECRET>
```

推奨イベント:

```text
page.created
page.properties_updated
page.content_updated
page.moved
page.deleted
page.undeleted
data_source.content_updated
data_source.schema_updated
```

旧Webhook APIバージョンでは次も受け付ける。

```text
database.content_updated
database.schema_updated
```

### 検証トークン

購読作成時、Notionは`verification_token`を一度POSTする。PETITはこれをSQLiteへ保存し、サーバーログへ表示する。その値をNotionの購読確認画面へ貼り付ける。

`.env`へ固定する場合:

```env
NOTION_WEBHOOK_ENDPOINT_SECRET=<十分に長いランダム値>
NOTION_WEBHOOK_VERIFICATION_TOKEN=secret_xxx
```

以降のイベントは`X-Notion-Signature`を、受信した生のリクエスト本文と検証トークンから計算したHMAC-SHA256と比較する。

### Database IDとData Source ID

既存の2022-06-28 REST APIでは`NOTION_TASKS_DB_ID`を使う。新しいWebhook APIバージョンの`data_source.*`イベントも全件同期のトリガーにする場合は、対応するData Source IDも設定する。

```env
NOTION_TASKS_DB_ID=
NOTION_TASKS_DATA_SOURCE_ID=
```

Data Source IDを省略しても、ページイベントと定期補修同期は動作する。

## 設定

```env
NOTION_TASK_BACKGROUND_SYNC_ENABLED=1
NOTION_TASK_SYNC_ON_STARTUP=1
NOTION_TASK_PULL_INTERVAL_SECONDS=300
NOTION_TASK_FULL_SYNC_INTERVAL_SECONDS=86400
NOTION_TASK_SYNC_OVERLAP_SECONDS=120
NOTION_WEBHOOK_ENDPOINT_SECRET=
NOTION_WEBHOOK_VERIFICATION_TOKEN=
NOTION_WEBHOOK_REQUIRE_SIGNATURE=1
NOTION_WEBHOOK_ALLOW_TOKEN_ROTATION=0
```

- `PULL_INTERVAL`: 差分補修の間隔。既定5分
- `FULL_SYNC_INTERVAL`: 全件整合性確認。既定1日
- `OVERLAP`: 境界時刻の取りこぼしを防ぐ再取得幅
- `ENDPOINT_SECRET`: 初回検証リクエストを含むWebhook URL自体を守る共有secret
- `ALLOW_TOKEN_ROTATION`: Webhookを再作成して検証トークンを変更する時だけ一時的に有効化する

## 明示同期

```text
sync_notion_tasks(mode="incremental")
sync_notion_tasks(mode="full")
```

通常のタスク質問では呼ばず、ユーザーが「Notionの最新状態を確認して」「全件同期して」と明示した場合に使う。

## 観測

`/api/health`、`get_tasks`、チャットの観測情報に次を返す。

- Webhook検証トークン設定済みか
- Inboxのpending / failed件数
- 差分同期・全件同期の最終成功時刻
- Outboxのpending / failed件数
- conflict件数
- 最終エラー

正常時は同期を会話へ露出せず、失敗・競合・古い状態のときだけ説明する。

## セキュリティ

- Notion APIキーとWebhook検証トークンをGitへ保存しない
- Webhook署名検証を本番で無効にしない
- 公開URLはWebhookエンドポイントだけに限定する
- トンネルやリバースプロキシ側でもHTTPS・レート制限・アクセスログを有効にする
- 検証トークンを含む初回ログを共有しない

## 未対応

- conflictを選択解決する専用UI
- Notion API自体の2025-09-03 / 2026-03-11 Data Source API移行
- 公開Webhook Relayのホスティング

これらがなくても、競合を保存してデータを失わず、Webhookと定期補修を併用した双方向同期は成立する。
