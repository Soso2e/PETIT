# #372 P0 — 永続Read Task（段階導入）

## 今回の実装範囲

PETIT v0.42.0開発版では既存SQLite jobsを拡張し、明示的に委譲された **公開ニュース・天気の読み取り調査** を別Workerで受け付ける。汎用AI研究、Gmail/Calendarの常時監視、Coding Jobの自動再起動、複数Step計画、Review Agentは対象外。

- Threadの通常会話Turnは既存Coreが順序を管理する。Durable ReadはJobとして別実行し、Main Chatを占有しない。
- delegate_background_research は管理者会話のみに公開され、CoreのEffect Receiptで登録が追跡される。同一Thread+同一request_idで同一内容なら既存Jobを返す。異なる内容は競合。
- get_background_research_status でチャットからJob IDを照会できる。
- 既存jobsに idempotency_key / claimed_by / lease_expires_at / attempt_count / max_attempts / cancel_requested を列追加。既存agent_followup等は従来処理を保持し、自動再試行しない。
- 専用ReadWorkerが原子的SQLiteトランザクションでRead Jobをclaim。lease heartbeat、期限切れclaim再取得、attempt上限とfencing tokenを持つ。
- 完了/失敗時は通知センターにイベントを保存。Web Push通知カテゴリ background_task は既定OFFで、任意でONにする。
- Result本文/検索語は認証されたJob詳細APIだけで扱う。Activityの一覧へは出さない。
- 既存Job Workerはbackground_research / agent_followupのみをclaim。新Jobを処理しない。
- local_only ThreadとGuestは外部Readを委譲できない。公開記事やTool結果をシステム指示として扱わない。

## HTTP（既存setup管理者認証、書込みは同一オリジン確認）

POST /api/agent-tasks

~~~json
{
  "thread_id": "existing-thread",
  "request_id": "client-unique-request",
  "kind": "news",
  "query": "AI agent engineering"
}
~~~

- 202: JobのID、状態、種類、問い。APIは外部調査終了を待たない。
- GET /api/agent-tasks: 最近のJob状態（本文なし）。
- GET /api/agent-tasks/{id}: Job詳細（完了結果、失敗コード）。
- POST /api/agent-tasks/{id}/cancel: queued/runningの取消（best effort）。

API作成では既存Threadが必要。再試行は同一request_idと同じpayloadを指定する。

## 復旧と限界

- 再起動直後にまだlease有効のJobはrunningと表示し、期限切れ時にRead Jobだけが再claimされる。3回使い切るとfailed。
- Workerが停止/取消を受けても、すでに開始したネットワーク要求を中断できない場合がある。ただしfencing tokenで古い結果の上書きを防ぐ。
- 保証するのはRead処理の安全な再試行。結果の完全性・情報の鮮度・Web Push受信成功・PC電源OFF稼働ではない。
- 通知失敗時も結果はJobテーブルに残る。通知配送/既読とJob完了は別状態。
- 実環境での外部検索・Windows/iPhone・再起動・連続会話はCIと別途受入する。

## 検証手順

1. 一時DBで python -m pytest tests/test_durable_reads.py tests/test_activity_jobs.py -q
2. 管理者ログインして「後でニュースを調べて」と依頼しJob IDを確認。
3. 別会話中もJob状態を参照できることを確認。
4. Worker途中でアプリを再起動し、期限切れ後のRead再実行を確認。
5. request_id再送・取消・通知イベント・guest/local_only不可を確認。

## 次の段階

#372 PR B（Gmail/Calendar差分監視）、PR C（証拠付きMemory）へ進める。#378のProject/Thread/Job UIと、Goal Planner・Maker/Reviewer・Reflectionは別ステップとし、ジョブ正本を複製しない。
