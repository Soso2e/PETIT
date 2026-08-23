# PETIT Runtime Flows

この文書は、PETITの会話処理、One-pass Conversation Entry、Capability選択、Tool Calling、確認付き書き込み、進捗表示の実装フローを可視化したものです。

実装の根拠:

- `backend/main.py`
- `backend/agent.py`
- `backend/agent_runtime.py`
- `backend/capability_router.py`
- `backend/situation.py`
- `backend/time_context.py`
- `backend/work_sessions.py`
- `backend/tools/work_sessions.py`
- `backend/tools/registry.py`
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
    entry[One-pass Conversation Entry]
    entryResult{Tool不要か}
    directReply[最初のLLM回答をそのまま採用]
    capability[CapabilityをToolへ展開]
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
    exactTime -->|いいえ| runtime --> entry --> entryResult
    entryResult -->|はい| directReply --> response
    entryResult -->|いいえ| capability --> agentLoop --> response
    response --> pending --> persist
    persist -->|はい| save --> artifacts --> output
    persist -->|いいえ| output
```

Tool不要の雑談・相談・説明・文章作成は、Conversation Entryの1回目のLLM回答で終了します。個人データ、現在情報、外部ソース、または操作が必要な場合だけAgent Runtimeへ進みます。

---

## 2. One-pass Conversation Entry

```mermaid
flowchart TD
    start([Agent Runtime開始])
    planning[planning進捗を発行]
    history[直近履歴 最大8件 3200文字]
    activeWork{active または paused の作業があるか}
    workContext[Task 状態 経過時間をcompact contextとして付加]
    clock{相対日付や時刻表現があるか}
    userClock[必要な精度の日時をuser側へ付加]
    staticSystem[静的なConversation Entry system prompt]
    selector[Chatモデルを1回呼ぶ]
    routed{route_to_agentをcallしたか}
    reply[自然文を最終回答として返す]
    parse[Capability 最大4グループを検証]
    valid{有効なCapabilityがあるか}
    safeFallback[fallback_readだけを公開]
    map[登録済みToolへ展開]
    goal[元の依頼 目的 必要時刻をAgentへ渡す]
    agent[Agent Tool Loopへ]

    start --> planning --> history --> activeWork
    activeWork -->|はい| workContext --> clock
    activeWork -->|いいえ| clock
    clock -->|はい| userClock --> staticSystem
    clock -->|いいえ| staticSystem
    staticSystem --> selector --> routed
    routed -->|いいえ| reply
    routed -->|はい| parse --> valid
    valid -->|はい| map --> goal --> agent
    valid -->|いいえ| safeFallback --> goal
```

日時はsystem promptへ毎ターン結合せず、相対日付・相対時刻があるターンだけuser側へ注入します。

active / pausedのWork Sessionがある場合だけ、Task名・状態・経過時間・関連IDを小さいuser contextとしてConversation Entryへ付加します。作業がない場合は追加せず、通常質問をWork Session Toolへ強制routeしません。pausedは休憩中として扱います。

- 日付だけ必要: タイムゾーン、日付、曜日
- 時刻も必要: タイムゾーン、分単位の現在日時
- 「今何時？」だけの依頼: LLMを使わず決定論的に処理

### Capabilityと公開Tool

```mermaid
flowchart LR
    selector[route_to_agent]

    tasks[lists_and_tasks]
    work[work_sessions]
    calendar[calendar]
    knowledge[knowledge]
    github[github]
    web[web]
    memory[memory]
    projects[projects]
    fallback[fallback_read 内部専用]

    taskTools["タスク リスト Notion同期"]
    workTools["作業開始 状態更新 今日 期間集計"]
    calendarTools["時刻 予定 天気 リマインダー"]
    knowledgeTools["BRAIN Notion 記憶"]
    githubTools["GitHub差分 PR Repository"]
    webTools["ニュース 外部調査"]
    memoryTools["保存 要約 復帰 引き継ぎ"]
    projectTools["Project状態 候補 source同期"]
    readTools["明示列挙した読取Toolだけ"]

    selector --> tasks --> taskTools
    selector --> work --> workTools
    selector --> calendar --> calendarTools
    selector --> knowledge --> knowledgeTools
    selector --> github --> githubTools
    selector --> web --> webTools
    selector --> memory --> memoryTools
    selector --> projects --> projectTools
    fallback --> readTools
```

`fallback_read`はSelectorへ公開しない内部グループです。Router出力の欠落、JSON互換出力の失敗、Tool call引数の破損、モデル接続失敗時にだけ使い、書き込みToolを含めません。

### 作業記録

```mermaid
flowchart LR
    request[UniverseまたはChat]
    resolve{既存未完了Taskを1件に解決}
    ambiguous[0件または複数候補を返す]
    start[start_work_session]
    sqlite[(work_sessions と work_session_events)]
    active[GET active 経過秒を計算]
    update[一時停止 再開 続行 終了]
    report[今日または1から90日集計]
    ui[Universe Today Chat]

    request --> resolve
    resolve -->|失敗| ambiguous
    resolve -->|成功| start --> sqlite
    update --> sqlite
    sqlite --> active --> ui
    sqlite --> report --> ui
```

Notion Task DBへ作業時間プロパティは追加しません。SQLiteのセッションへPETIT内部`task_id`を保存し、Notionを含むタスク正本と参照で結びます。開始・一時停止・再開・終了はイベントとして残すため、日付をまたぐ休憩も暦日単位で集計できます。`start_work_session`と`update_work_session`は明示依頼時の低リスク書き込み、`get_work_status`と`get_work_report`は読み取りです。

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
    forceTool[このターンでTool callするよう再指示]
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
    args{引数検証に成功したか}
    badArgs[invalid_tool_arguments結果]
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

親子関係の変更は`set_task_parent`へ集約します。タスク名変更も同時に必要な場合は、同じTool callの`title`へ含め、Runtimeの確認を1回だけ表示します。

Agentの出力は通常プレーンテキストとし、比較・手順・コードなど可読性が明確に上がる場合だけ最小限のMarkdownを許可します。

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
    invalid[[error]またはinvalid_tool_arguments]
    dispatch[handlerを実行]
    error{例外や実行時エラーか}
    errorText[[error]文字列]
    result[JSONまたは文字列]

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

    proposal --> args --> saveState --> confirmation --> register --> decision
    decision -->|いいえ| cancel
    decision -->|はい| wrapper --> load
    load -->|いいえ| expired
    load -->|はい| validate
    validate -->|いいえ| invalid
    validate -->|はい| started --> dispatch --> failed
    failed -->|いいえ| failure
    failed -->|はい| resume --> readOnly --> final --> delete
```

Agentが自然文だけで「実行しますか？」と返した場合は承認として扱わず、確認対象Toolをcallするよう1回だけ再指示します。

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
    direct[Tool不要の会話]
    tasks[タスクと任意リスト]
    cal[時刻 予定 天気 リマインダー]
    know[BRAIN Notion 記憶検索]
    git[GitHub状況とRepository候補]
    web[ニュースと外部調査]
    mem[長期記憶 要約 復帰 引き継ぎ]
    project[Project Continuity]
    deterministic[決定論的処理]

    chat --> direct
    chat --> tasks
    chat --> cal
    chat --> know
    chat --> git
    chat --> web
    chat --> mem
    chat --> project
    chat --> deterministic
```

---

## 10. 停止条件と安全境界

```mermaid
flowchart LR
    limits[停止条件と安全境界]
    onePass[Tool不要会話は1回のLLMで終了]
    safeFallback[Router失敗時は読取Toolだけ]
    staticPrefix[system promptへ動的時刻を混ぜない]
    round[Toolラウンド上限]
    calls[Tool総数6回]
    duplicate[同一Tool 同一引数の再実行禁止]
    allowed[Capability外Toolの拒否]
    args[確認対象引数を承認前に検証]
    defer[作業予告のみの回答を1回再実行]
    confirm[confirm_write destructiveは承認必須]
    resume[Agent state 30分TTL]
    approval[approval_id 10分TTL]
    writeOnce[承認後の追加書き込みは禁止]

    limits --> onePass
    limits --> safeFallback
    limits --> staticPrefix
    limits --> round
    limits --> calls
    limits --> duplicate
    limits --> allowed
    limits --> args
    limits --> defer
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
- Conversation EntryとCapabilityグループ
- Agent Tool Loopと停止条件
- Tool Registryとrisk
- 確認付き書き込みとAgent state再開
- ProgressイベントとUI配信
- Project Continuity

Mermaid図と実装が一致しない状態でmainへ反映しないでください。
