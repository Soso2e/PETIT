# PETIT Runtime Flows

この文書は、PETITの会話処理・Capability選択・Tool Calling・確認付き書き込み・進捗表示の実装フローをMermaidで可視化したものです。

実装の根拠:

- `backend/main.py`
- `backend/agent.py`
- `backend/agent_runtime.py`
- `backend/capability_router.py`
- `backend/tools/registry.py`
- `backend/tools/agent_actions.py`
- `backend/tools/task_hierarchy.py`
- `backend/agent_state.py`
- `backend/agent_progress.py`
- `backend/project_router.py`
- `backend/task_completion_intent.py`

---

## 1. 会話全体フロー

```mermaid
flowchart TD
    input[/ユーザー入力/]
    api[POST /api/chat]
    validate{空メッセージか}
    bind[request_id と session_id を束縛]
    agentEntry[agent.run]

    namedTask{名前付きタスク完了か}
    namedTaskRoute[SQLiteの tasks_cache で候補解決]

    projectRoute{Project Continuity系か}
    projectHandle[登録 完了 切替 復帰を決定論的に処理]

    exactTime{現在時刻だけの依頼か}
    timeTool[get_current_time を直接実行]

    runtime[Agent Runtime]
    capability[Capability Selector]
    agentLoop[Agent Tool Loop]

    response[ChatResponseを生成]
    pending[確認待ち操作を登録]
    persist{persist が true か}
    save[会話をSQLiteへ保存]
    artifacts[要約や索引などを非同期保存]
    output[/返答 pending_actions model_route/]

    input --> api --> validate
    validate -->|はい| output
    validate -->|いいえ| bind --> agentEntry
    agentEntry --> namedTask
    namedTask -->|はい| namedTaskRoute --> response
    namedTask -->|いいえ| projectRoute
    projectRoute -->|はい| projectHandle --> response
    projectRoute -->|いいえ| exactTime
    exactTime -->|はい| timeTool --> response
    exactTime -->|いいえ| runtime --> capability --> agentLoop --> response
    response --> pending --> persist
    persist -->|はい| save --> artifacts --> output
    persist -->|いいえ| output
```

---

## 2. Capability Selector

```mermaid
flowchart TD
    start([Agent Runtime開始])
    planning[planning進捗を発行]
    context[直近履歴 最大8件 3200文字]
    selector[ChatモデルへCapability選択を依頼]
    parsed{JSONを解釈できたか}
    fallback[Capability空配列でAgentへ]
    validate[最大4グループに正規化]
    map[登録済みToolだけへ展開]
    prompt[元の依頼 目的 履歴をAgentへ渡す]
    agent[Agent Tool Loopへ]

    start --> planning --> context --> selector --> parsed
    parsed -->|いいえ| fallback --> prompt
    parsed -->|はい| validate --> map --> prompt
    prompt --> agent
```

### Capabilityと公開Tool

```mermaid
flowchart LR
    selector[Capability Selector]

    tasks[lists_and_tasks]
    calendar[calendar]
    knowledge[knowledge]
    github[github]
    web[web]
    memory[memory]
    projects[projects]

    taskTools["get_lists / get_list_items / create_list / add_list_item / get_tasks / create_task / update_task / set_task_parent / complete_task / get_task_sync_status / retry_task_sync / sync_notion_tasks"]
    calendarTools["get_current_time / get_schedule / add_schedule / sync_calendar / create_reminder / get_reminders / manage_reminder / get_weather"]
    knowledgeTools["search_memory / search_brain_notes / search_notion / edit_brain_note / sync_obsidian_vault"]
    githubTools["review_github_activity / sync_github_evidence / get_github_repository_candidates / link_github_repository_candidate / ignore_github_repository_candidate / inspect_github_repository"]
    webTools["search_news / start_background_research"]
    memoryTools["save_memory / summarize_now / create_daily_briefing / restore_context / create_handoff_note"]
    projectTools["get_project_status / get_tasks / get_notion_project_candidates / get_linkraft_project_candidates / get_brain_note_candidates / get_github_repository_candidates / sync_notion_tasks / sync_linkraft_projects / sync_github_evidence"]

    selector --> tasks --> taskTools
    selector --> calendar --> calendarTools
    selector --> knowledge --> knowledgeTools
    selector --> github --> githubTools
    selector --> web --> webTools
    selector --> memory --> memoryTools
    selector --> projects --> projectTools
```

---

## 3. Agent Tool Loop

```mermaid
flowchart TD
    call[Agentモデルを呼ぶ]
    hasCalls{Tool callがあるか}

    answer[回答本文を取得]
    empty{回答が空か}
    fallbackAnswer[言い換えを求める固定文]
    incomplete{作業予告またはRuntime外の確認だけか}
    retryUsed{再実行済みか}
    forceTool[このターンでTool callし Runtime確認へ進むよう再指示]
    deferredFail[未実行を明示した失敗回答]
    finalizing[finalizing進捗を発行]
    final[/最終回答/]

    roundLimit{Toolラウンド上限か}
    stopRound[tool_iteration_limitで停止]
    normalize[Tool callsを正規化]
    each[各Tool callを処理]

    totalLimit{Tool総数6回に到達か}
    stopTotal[tool_call_limitで停止]
    allowed{公開済みToolか}
    notAllowed[tool_not_allowed結果]
    args{JSON解釈と確認対象schema検証に成功したか}
    badArgs[理由付きinvalid_tool_arguments結果]
    duplicate{同じToolと引数を実行済みか}
    duplicateStop[duplicate_tool_call結果]
    confirmation{確認が必要か}
    writeFlow[確認付き書き込みフロー]
    execute[Toolをdispatch]
    progressStart[tool_started進捗]
    progressFinish[tool_finished進捗]
    compact[結果を最大20項目 5000文字へ圧縮]
    append[元の依頼とTool結果をmessagesへ追加]

    call --> hasCalls
    hasCalls -->|いいえ| answer --> empty
    empty -->|はい| fallbackAnswer --> incomplete
    empty -->|いいえ| incomplete
    incomplete -->|いいえ| finalizing --> final
    incomplete -->|はい| retryUsed
    retryUsed -->|いいえ| forceTool --> call
    retryUsed -->|はい| deferredFail --> finalizing

    hasCalls -->|はい| roundLimit
    roundLimit -->|はい| stopRound --> final
    roundLimit -->|いいえ| normalize --> each --> totalLimit
    totalLimit -->|はい| stopTotal --> final
    totalLimit -->|いいえ| allowed
    allowed -->|いいえ| notAllowed --> compact
    allowed -->|はい| args
    args -->|いいえ| badArgs --> compact
    args -->|はい| duplicate
    duplicate -->|はい| duplicateStop --> compact
    duplicate -->|いいえ| confirmation
    confirmation -->|はい| writeFlow
    confirmation -->|いいえ| progressStart --> execute --> progressFinish --> compact
    compact --> append --> call
```

親子関係の変更は`set_task_parent`へ集約する。タスク名の変更も同時に必要な場合は、同じTool callの`title`へ含め、Runtimeの確認を1回だけ表示する。`update_task`へ`parent_id`や`parent_task_id`を渡した場合は、確認画面を出す前に不正引数としてAgentへ返し、正しいToolの再選択を促す。

---

## 4. Tool Registryとリスク判定

```mermaid
flowchart TD
    decorator[@tool decorator]
    riskInput{riskが明示されているか}
    explicit[指定riskを使用]
    override{既定risk一覧にあるか}
    defaultRisk[既定riskを使用]
    legacy{requires_confirmationがtrueか}
    confirm[confirm_write]
    safe[safe_read]
    register[Registryへ登録]

    invoke[AgentがToolを選択]
    parse[引数JSONをdictへ]
    writeRisk{confirm_write または destructiveか}
    schema[properties required type enumを検証]
    valid{schemaに適合するか}
    invalid[[error]またはinvalid_tool_argumentsとしてAgentへ返す]
    dispatch[handlerを実行]
    error{例外や実行時エラーか}
    errorText[[error]文字列を返す]
    result[JSONまたは文字列を返す]

    decorator --> riskInput
    riskInput -->|はい| explicit --> register
    riskInput -->|いいえ| override
    override -->|はい| defaultRisk --> register
    override -->|いいえ| legacy
    legacy -->|はい| confirm --> register
    legacy -->|いいえ| safe --> register

    invoke --> parse --> writeRisk
    writeRisk -->|はい| schema --> valid
    valid -->|いいえ| invalid
    valid -->|はい| dispatch
    writeRisk -->|いいえ| dispatch
    dispatch --> error
    error -->|はい| errorText
    error -->|いいえ| result
```

確認対象Toolでは、未定義引数、必須不足、型不一致、enum外の値を承認前に拒否する。既存Toolが許容している数字文字列IDは、`integer`互換として維持する。

### リスク区分

```mermaid
flowchart LR
    safeRead[safe_read]
    lowWrite[low_risk_write]
    confirmWrite[confirm_write]
    destructive[destructive]

    direct[その場で実行]
    approval[ユーザー確認が必要]

    safeRead --> direct
    lowWrite --> direct
    confirmWrite --> approval
    destructive --> approval
```

---

## 5. 確認付き書き込みと再開

```mermaid
flowchart TD
    proposal[Agentが確認対象Toolを提案]
    args[Tool schema検証済みの引数]
    saveState[Agent stateをSQLiteへ保存]
    stored["original_request / messages / capabilities / selected_names / attempted / rounds / used_tools / request_id / session_id"]
    confirmation[Runtimeが確認文とexecute_agent_writeを1回だけ返す]
    register[main.pyがapproval_idを登録 10分TTL]
    decision{ユーザーが承認したか}
    cancel[書き込みをキャンセル]
    wrapper[execute_agent_write]
    load{Agent stateが30分以内か}
    expired[期限切れエラー]
    validate{対象Toolが確認対象か}
    invalid[許可されていないTool]
    started[tool_started進捗]
    dispatch[対象Toolをdispatch]
    failed{書き込み成功か}
    failure[tool_finished失敗]
    resume[resume_after_write]
    readOnly[確認不要Toolだけを公開してAgent Loop再開]
    final[自然な最終回答]
    delete[Agent stateを削除]

    proposal --> args --> saveState --> stored --> confirmation --> register --> decision
    decision -->|いいえ| cancel
    decision -->|はい| wrapper --> load
    load -->|いいえ| expired
    load -->|はい| validate
    validate -->|いいえ| invalid
    validate -->|はい| started --> dispatch --> failed
    failed -->|いいえ| failure
    failed -->|はい| resume --> readOnly --> final --> delete
```

Agentが自然文だけで「実行しますか？」と返した場合は承認として扱わず、確認対象Toolをcallするよう1回だけ再指示する。これにより、Agent本文とRuntimeカードの二重・三重確認を防ぐ。

---

## 6. 進捗表示

```mermaid
flowchart LR
    runtime[Agent Runtime]
    events["planning / tool_started / tool_finished / finalizing"]
    emit[agent_progress.emit]
    jobs[(SQLite jobs)]
    api[既存Jobs API]
    ui[Web UIの一時ステータス]
    history[通常会話履歴]

    runtime --> events --> emit --> jobs --> api --> ui
    ui -.->|進捗は履歴へ保存しない| history
```

---

## 7. 名前付きタスク完了の決定論的フロー

```mermaid
flowchart TD
    input[/例 LiTデザインは完了した/]
    extract{完了表現と対象名を抽出できるか}
    skip[通常ルートへ]
    cache[(tasks_cache)]
    score[表記を正規化して候補を採点]
    active{未完了候補があるか}
    completed{完了済み候補があるか}
    already[すでに完了と回答]
    none[一致なしと回答]
    unique{最高得点候補が1件か}
    multiple[候補を提示して確認]
    confirm[complete_taskの確認を返す]

    input --> extract
    extract -->|いいえ| skip
    extract -->|はい| cache --> score --> active
    active -->|いいえ| completed
    completed -->|はい| already
    completed -->|いいえ| none
    active -->|はい| unique
    unique -->|いいえ| multiple
    unique -->|はい| confirm
```

---

## 8. Project Continuityの決定論的フロー

```mermaid
flowchart TD
    input[/プロジェクトに関する入力/]
    registration{登録の続きか}
    registrationHandle[Project登録フロー]
    completionDraft{完了確認中か}
    completionHandle[Project完了フロー]
    taskCompletion{Task完了の続きか}
    taskHandle[Task完了フロー]
    explicitCompletion{Project完了表現か}
    explicitHandle[Project完了フロー]
    action{明示的な開始 再開 切替か}
    none[通常Agentへ]
    resolve[aliasとactive projectから解決]
    kind{解決結果}
    ambiguous[候補確認]
    candidate[新規Project候補の確認]
    activate[active projectを切替]
    resume[checkpointや外部sourceから復帰文を生成]

    input --> registration
    registration -->|はい| registrationHandle
    registration -->|いいえ| completionDraft
    completionDraft -->|はい| completionHandle
    completionDraft -->|いいえ| taskCompletion
    taskCompletion -->|はい| taskHandle
    taskCompletion -->|いいえ| explicitCompletion
    explicitCompletion -->|はい| explicitHandle
    explicitCompletion -->|いいえ| action
    action -->|いいえ| none
    action -->|はい| resolve --> kind
    kind -->|ambiguous| ambiguous
    kind -->|new_candidate| candidate
    kind -->|resolved| activate --> resume
    kind -->|none| none
```

---

## 9. チャットで行えることの全体像

```mermaid
flowchart TD
    chat([PETIT Chat])

    tasks[タスクと任意リスト]
    cal[時刻 予定 天気 リマインダー]
    know[BRAIN Notion 記憶検索]
    git[GitHub状況とRepository候補]
    web[ニュースと外部調査]
    mem[長期記憶 要約 復帰 引き継ぎ]
    project[Project Continuity]
    direct[決定論的処理]

    taskRead[一覧 取得 同期状態]
    taskWrite[作成 更新 完了 親子関係 同期再試行]
    calRead[現在時刻 予定 天気 リマインダー一覧]
    calWrite[予定追加 リマインダー操作 同期]
    knowRead[記憶 BRAIN Notion検索]
    knowWrite[BRAIN編集 Vault同期]
    gitRead[活動レビュー Repository検査 候補取得]
    gitWrite[Repository紐付け 候補無視 同期]
    webRead[ニュース検索]
    webResearch[Background research開始]
    memOps[保存 要約 Daily briefing Context復元 Handoff]
    projectOps[状態取得 外部候補取得 source同期 開始 再開 完了]
    directOps[名前付きTask完了 現在時刻 Project明示操作]

    chat --> tasks --> taskRead
    tasks --> taskWrite
    chat --> cal --> calRead
    cal --> calWrite
    chat --> know --> knowRead
    know --> knowWrite
    chat --> git --> gitRead
    git --> gitWrite
    chat --> web --> webRead
    web --> webResearch
    chat --> mem --> memOps
    chat --> project --> projectOps
    chat --> direct --> directOps
```

---

## 10. 停止条件と安全境界

```mermaid
flowchart LR
    limits[停止条件]
    round[Toolラウンド上限]
    calls[Tool総数6回]
    duplicate[同一Tool 同一引数の再実行禁止]
    allowed[Capability外Toolの拒否]
    args[確認対象の未定義引数 必須 型 enumを承認前に拒否]
    defer[作業予告のみの回答を1回再実行]
    manualConfirm[Runtime外の書き込み確認をTool callへ戻す]
    confirm[confirm_write destructiveは承認必須]
    resume[Agent state 30分TTL]
    approval[approval_id 10分TTL]
    writeOnce[承認後の追加書き込みは禁止]

    limits --> round
    limits --> calls
    limits --> duplicate
    limits --> allowed
    limits --> args
    limits --> defer
    limits --> manualConfirm
    limits --> confirm
    limits --> resume
    limits --> approval
    limits --> writeOnce
```

---

## 保守ルール

以下へ変更を加えた場合は、この文書の対応するMermaid図も同じ変更で更新してください。

- `/api/chat`と確認API
- 決定論的な会話ルート
- Capabilityグループまたは公開Tool
- Agent Tool Loopと停止条件
- Tool Registryとrisk
- 確認付き書き込みとAgent state再開
- ProgressイベントとUI配信
- Project Continuity

Mermaid図と実装が一致しない状態でmainへ反映しないでください。
