# Dialogue State #294 受入記録

2026-10-06、v0.24.0。外部サービスの成功とローカル会話の成功を区別する。

## Acceptance Criteria

| Case | 自動検証 |
|---|---|
| 1 直前作成Taskの子を追加 | `test_case1_child_of_last_created_without_project_or_llm` |
| 2 確認への名前回答 | `test_cases2_3_4_pending_answers_owned_by_tasks` |
| 3 前者 / 後者 | 上記と`test_single_candidate_pronoun_and_former` |
| 4 番号回答 | 上記と`test_duplicate_names_require_id_or_ordinal` |
| 5 focus Taskの期限更新 | `test_case5_due_date_uses_stable_id` |
| 6 Project Router名詞句/明示action | `tests.test_project_router_context_guard` |
| 7 曖昧なfocus | `test_case7_two_creates_in_same_turn_ask_without_writing` |
| 8 session分離 | `test_case8_no_cross_session_pending_or_focus` / state suite |
| 9 再起動復元 / TTL | `test_restart_restores_focus_and_pending_and_expires_pending` / `test_case9_restored_pending_executes_and_expired_pending_does_not_own_answer` |

9ケースはLLM呼出しなし。加えて失敗Tool、一覧Read、部分更新、stable ID失効、候補取消、risk変更時の拒否、親の階層制約、確認APIのsession保存、破損Stateを検証。

## ローカル自動回帰

```sh
.venv/bin/python -m unittest \
  tests.test_dialogue_state tests.test_dialogue_resolution \
  tests.test_project_router_context_guard tests.test_conversation_state \
  tests.test_brain_runtime tests.test_project_router tests.test_project_continuity \
  tests.test_project_completion tests.test_project_resume tests.test_project_registration \
  tests.test_task_conversation_flow tests.test_task_hierarchy_idempotency \
  tests.test_task_parent_confirmation_guard tests.test_contextual_agent_runtime \
  tests.test_tool_risk_policy tests.test_context_broker tests.test_personal_context_broker \
  tests.test_pending_actions_router tests.test_generic_lists tests.test_task_cancel_status -q
```

147テスト成功。Python compileall、共有Frontend JS/バージョンJS構文、git diffチェック成功。既存のContextual Agent CIに新ケースを追加し、同内容の新workflowは作成しない。

追加で実行した`tests.test_task_selection_parent_apply`は旧Universe UIのソース文字列期待2件が失敗。変更前main (`514208f`)の同じFrontendとtestを`git archive`で隔離しても4件中同じ2件が失敗し、今回の変更に起因しない。対象ファイルは変更しない。この既存不整合は別作業。

## 実アプリ / 実ブラウザ

普段のstorageを変更せず、`/tmp/petit-294-live`の独立SQLite/Chroma/Markdown領域で実際の`backend.main:app`を127.0.0.1:18094へ起動。Tool / API / Frontendをmockせず、Codex内ブラウザの既存PETIT会話画面を使用した。Notionは未設定のためローカルTask。

1. 同一sessionで`ゲーム開発タスク追加`を送信。作成成功を画面で確認。
2. `その子にWEVORA追加`を送信。候補質問なしで「ゲーム開発の子にWEVORAを追加」が返り、親の詳細に`CHILD TASKS 1件 / WEVORA`が表示された。
3. SQLiteでTask ID 1=ゲーム開発、ID 2=WEVORA、`parent_task_id=1`を確認。
4. サーバープロセスを終了・同じDBで再起動し、ブラウザを再読込。履歴が復元された。
5. `その期限明日にして`を送信。「WEVORAを変更」が返り、同じID 2の`due_date=2026-10-07`を確認。親ID 1の期限は変更なし。

この確認はローカルの実機文字会話の受入。実Notion同期、配布Desktop、マイク/STT/TTS、他OSの受入は未実施。Notionでは既存仕様どおり同期済みの親が必要で、未同期親を黙って別のTaskに置換しない。
