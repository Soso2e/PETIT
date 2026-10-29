# Conversation-to-Action Reliability — 初回修正（#335）

調査基準は `feat/multimodal-vision` の `2f3fe8b`。修正ブランチは `origin/main` の `8fc1c5e` から分離し、Vision差分・既存storage・ローカルmainの未Push修正を変更しない。

## Phase 1：再現と原因

隔離SQLiteとMockを使い、修正前に `tests.test_action_reliability.ActionReliabilityTests` の初期5テストを実行。4 failure / 1 errorで再現した。実環境の過去応答を生成したモデル内部の判断は観測できないため、過去会話そのものの全原因を断定するものではない。

| 経路 | 確認できた原因 |
|---|---|
| `agent.run → dialogue_resolution → project_router → Brain` | 明示Session開始の決定論処理がなく、最初の発話を通常会話の返答で終えられた。 |
| `capability_router.choose` | Workのguardに「セッション」がなく、guard自体も `request_context` / モデルのCapability選択より後にあった。Context要求がTask / Calendarの明示操作も遮れた。エラーfallbackはReadのみを公開した。 |
| `brain_runtime._run_context_path` | Context取得後は `tools=None` の回答生成で終了し、元の操作へ戻る経路がなかった。 |
| `agent_runtime._execute_loop` | 作業予告や重複確認の検査はあったが、実行結果がない「開始したよ」は通過した。`started=false` も失敗判定対象外だった。 |
| `Registry → dialogue_state.observe_tool_result` | 観測対象はTask writeのみ。Work開始のID・実行状態が次ターンの構造化Stateへ入らなかった。BrokerのTask factsからも安定IDが落ちていた。 |
| `tools.work_sessions` | 未完了だけで検索したため完了・キャンセル・削除と不存在を区別しにくく、同じpaused Taskでも計測を作り直した。重複判定は開始トランザクション外だった。 |

追加の同時実行テストで、初回Notion列追加の `duplicate column name: remote_deleted_at` も再現。列存在確認から追加までを既存SQLiteの `BEGIN IMMEDIATE` で直列化した。

## Phase 2–3：既存構造で修正

- 明確なSession開始・短い開始照応・開始状態の質問を既存Dialogue入口へ追加。完全一致/正規化/一意な部分一致で既存タスクを解決し、IDでRegistryの `start_work_session` を実行する。明示操作はriskが `low_risk_write` の場合だけ即時実行する。
- `focus_stack` は言及/選択対象、`last_action` は対象IDと実行状態、実際のactive/paused状態は `work_sessions` を正とする。既存のTask write用Pendingと承認APIは維持する。
- Task所有の既存 `pending_dialogue` に `start_work_session` を許可。10分TTL、元依頼、候補の安定ID、失敗状態を保存し、候補選択時は既存の原子的なclaimを使う。失敗後の補足だけでは再実行しない。再試行は明示開始で行う。対象IDの再確認後にToolへ渡す。
- 同一Taskのactiveは再利用、pausedは計測履歴を保持して再開。重複判定と開始を同じSQLiteトランザクションへ入れた。HTTP APIの従来の明示session ID契約は維持する。
- 明示ActionのCapabilityをモデルのContext/狭いrouteより優先する安全guardを追加。意味理解は引き続きBrainに任せ、`action_required` / `continue_action` とCapabilityで操作目的を伝える。新しいAgent・Router・DBは作らない。
- Contextが必要な操作だけ、取得済みPacketを元依頼とともに既存Agentへ渡す。BrokerはReadのみ。通常のRead質問ではAgentへ進まない。Task factsの安定IDも保持する。
- AgentはActionなのにWrite結果がない場合、既存の一度限りの再指示を使い、再度未実行なら失敗を明示する。失敗/部分成功は結果から報告する。承認後にもWrite結果を引き継ぐ。開始の直接回答はTool結果と保存session ID・Task ID・active状態が一致する場合だけ成功とする。
- 検索対象は一覧のHigh/件数制限と分離したローカル全状態キャッシュ。terminal状態と未同期情報を区別し、外部に存在しないとは断定しない。名前に加えて内部IDとNotion external IDを使える。Task別名の永続機構は現行にないため追加しない。

## 検証と指標

Mockによる決定論的テストと実モデル受入は分ける。新規テストは元会話、直前対象、重複/paused再開、複数候補、不存在/terminal/Low優先、失敗再試行、改名後のID維持、話題転換、キャンセル、TTL/session分離、同時開始、Routerエラー、Contextからの継続/Read維持、未実行/失敗の誤成功防止、承認後の結果、隔離 `/api/chat` を含む。

隔離HTTPの5発話では、開始/重複開始/状態照会/短い開始はLLM 0 Call、作業内容の補足だけMockの1 Call。追加質問0、保存session 1件、会話5件。並列4開始もsession 1件を検証する。この値は合成fixtureの結果であり実ユーザーでの操作成功率ではない。

雑談は従来の1 Call。Read Contextは原則2 Call。Context→Actionは不要な最終回答Callを省き既存Agentへ進む。未実行なのに成功発話したAgentだけ、安全確認のため最大1 Call増える。State・名前照合はローカルDBのみで、依存追加・外部検索・Embedding追加なし。通常応答時間の実モデル比較は未実施。

関連pytestは183 passed + 29 subtests。新規25ケースは `python -m unittest tests.test_action_reliability -v`、その他の対象一覧とVision重ね合わせの結果はPRに記録する。Python compileall、バージョンJS構文、diffの空白検査も成功。LM Studioの `127.0.0.1:1234/v1/models` は接続不可で、実モデルE2E・実Notion書込み・実Desktop受入は未確認。実データへ試験書込みは行っていない。

変更前の基準ブランチでも `tests.test_task_completion_conversation` は9件中3 errors（廃止済み `backend.main._register_pending_actions` と古いfixtureの `project_id` 欠落）。無変更の `origin/main` ではChat/承認ルートの直接列挙検査も2件失敗し、合計5 failed / 13 passedを同じ環境で再現した。今回の回帰と分離し、既存テスト整備は [#336](https://github.com/Soso2e/PETIT/issues/336) で追跡する。`test_one_pass_router` の旧Brain以前のRead route/Prompt文字列期待値は現行契約へ更新した。

## 後続

1. 実モデルで元会話・否定/仮定/柔らかい依頼・自然な話題転換を反復し、操作成功率、誤成功率、不要質問数、Call数、p50/p95を測る。
2. #303の永続Action契約に沿って、Task以外のProject/Calendar等の目的・対象・部分成功・必要slotの継続を設計する。今回のTask所有Pendingを汎用承認キューとして使わない。
3. Task別名・外部同期範囲を含めた検索の改善、作業詳細（「カット中」等）の記録Tool、終了後の新しい開始と再送を区別する永続request receiptは別スコープ。
4. 一般の複数操作の全完了検証、任意の成功文と個々のTool結果の対応検証は引き続き課題。初回PRの保証を全操作へ一般化しない。
