# タスク状態の取得と出力

## Notionの現行ステータス

現在使用中のNotion「たすく」DBは、次のStatusを持つ。

```text
Yet / Now / ready / Done / Chancel
```

`Done`と`Chancel`はNotion上で完了グループに属する。`Chancel`は既存DBで実際に使われている表記のため、PETITはキャンセル状態として互換対応する。

## 既定の取得

`get_tasks`をステータス指定なしで実行した場合、実行候補となるアクティブタスクだけを返す。

- 含める: `Yet`、`Now`、`ready`など
- 除外する: `Done`、`Chancel`、`Cancel`、`Canceled`、`Cancelled`、`キャンセル`など

キャンセル済みタスクを確認したい場合は`status=Chancel`などを指定する。完了・キャンセルを含む全状態が必要な場合は`status=all`を使う。

## 件数フィールド

- `returned_count`: 今回のレスポンスに含めた件数
- `total_count`: 指定条件に一致する総件数
- `has_more`: 取得上限により一部だけ返したか
- `count`: 後方互換用。`returned_count`と同じ値

Agentは`returned_count`や`count`だけを見て「全件」と断定しない。`has_more=true`の場合は一部取得と明記する。

## 状態サマリー

`status_summary`は、エリア・プロジェクトの範囲内にある状態を次のように集計する。

- `active`: 実行候補
- `completed`: 完了
- `cancelled`: キャンセル
- `cancelled_statuses`: 実際に検出したキャンセル表記
- `by_status`: 元のステータス別件数

キャンセルは進行中・未完了として数えず、必要な場合だけ別情報として説明する。

## プロンプト境界

このルールは毎回送る共通Agent promptへ追加せず、`get_tasks`のツール説明と`response_guidance`へ限定して渡す。タスクを取得したターンだけモデルへ伝えることで、通常会話の常時トークンを増やさずに出力を制御する。
