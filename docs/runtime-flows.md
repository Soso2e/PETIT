# PETIT Runtime Flows

この文書は、PETITの会話処理、PETIT Brain、Context Broker、Capability選択、Tool Calling、確認付き書き込み、進捗表示の実装フローを可視化したものです。

実装の根拠:

- `backend/main.py`
- `backend/chat.py`
- `backend/chat_models.py`
- `backend/pending_actions.py`
- `backend/agent.py`
- `backend/brain_runtime.py`
- `backend/context_broker.py`
- `backend/workspace_context.py`
- `backend/petit_prompt.py`
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
    api[chat.py: POST /api/chat]
    validate{空メッセージか}
    bind[request_id と session_id を束縛]
    agentEntry[agent.run]

    namedTask{名前付きタスク完了か}
    namedTaskRoute[SQLiteの tasks_cache で候補解決]
    projectRoute{Project Continuity系か}
    projectHandle[登録 完了 切替 復帰を決定論的に処理]
    exactTime{現在時刻だけの依頼か}
    timeTool[get_current_time を直接実行]

    brain[PETIT Brain]
    selector[最初のChatモデルCall]
    route{結果}
    directReply[自然文をそのまま返す]
    context[Context Broker]
    parallel[必要な個人Contextを独立Readとして並列取得]
    packet[正規化Context Packet]
    second[同じPETIT Core Promptで2回目のChatモデルCall]
    capability[CapabilityをToolへ展開]
    agentLoop[既存Deep Agent Tool Loop]

    response[ChatResponseを生成]
    pending[pending_actions.registerで確認待ち操作を登録]
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
    exactTime -->|いいえ| brain --> selector --> route
    route -->|reply| directReply --> response
    route -->|request_context| context --> parallel --> packet --> second --> response
    route -->|route_to_agent| capability --> agentLoop --> response
    response --> pending --> persist
    persist -->|はい| save --> artifacts --> output
    persist -->|いいえ| output
```

`backend/chat.py` が `/api/chat`、Agent実行、observability、Pending Action登録、SQLite会話保存、Chroma/Markdown artifact保存を所有します。`backend/main.py` はChat Routerを登録するだけで、会話実装の詳細を持ちません。

PETITの人格と会話原則は `petit_prompt.py` のCore Promptを正とします。Tool不要の雑談・相談・説明・文章作成は最初の1 LLM Callで終了します。Broker対応sourceのReadだけ不足する会話は `Brain -> Context Broker -> Brain` の原則2 Callで完了し、書き込みや対象外・複雑処理は既存Deep Agentへ進みます。

---

## 2. PETIT Brain / Context Broker

```mermaid
flowchart TD
    start([PETIT Brain開始])
    planning[planning進捗を発行]
    history[直近履歴 最大8件 3200文字]
    activeWork{active または paused の作業があるか}
    workContext[Task 状態 経過時間をcompact contextとして付加]
    optionalPC[有効時だけPC観測cacheを付加 / staleは不明]
    clock{相対日付や時刻表現があるか}
    userClock[必要な精度の日時をuser側へ付加]
    core[共通PETIT Core Prompt]
    selector[Chatモデルを1回呼ぶ]
    result{結果}
    reply[自然文を最終回答として返す]
    request[request_context]
    normalize[ContextRequestを対応source 最大4件に正規化]
    parallel[共有最大4枠 / 固定Read処理だけ並列実行]
    task[get_tasks]
    calendar[get_schedule]
    personal[search_memory / search_brain_notes / get_work_status / get_reminders]
    handoff[SQLiteで対象作業のhandoffを取得]
    packet[raw JSONをAI向けfactsへ正規化]
    partial[期限 / 失敗 / staleをpartialとして保持]
    second[Core Prompt + 元の状況文脈 + bounded Packetで2回目Call]
    final[自然な最終回答]
    route[route_to_agent]
    parse[Capability 最大4グループを検証]
    map[登録済みToolへ展開]
    agent[Deep Agent Tool Loopへ]

    start --> planning --> history --> activeWork
    activeWork -->|はい| workContext --> optionalPC --> clock
    activeWork -->|いいえ| optionalPC
    clock -->|はい| userClock --> core
    clock -->|いいえ| core
    core --> selector --> result
    result -->|reply| reply
    result -->|request_context| request --> normalize --> parallel
    parallel --> task --> packet
    parallel --> calendar --> packet
    parallel --> personal --> packet
    parallel --> handoff --> packet
    packet --> partial --> second --> final
    result -->|route_to_agent| route --> parse --> map --> agent
```

日時はsystem promptへ毎ターン結合せず、相対日付・相対時刻があるターンだけuser側へ注入します。active / pausedのWork Sessionがある場合だけ、小さいuser contextをConversation Entryへ付加します。

Context Brokerは `tasks` / `calendar` / `memory` / `brain` / `work` / `reminders` / `handoff` に対応します。Brokerは具体Tool名をLLMへ大量公開せず、固定したRead処理へ変換し、Toolのriskも実行直前に検証します。独立sourceは最大4件を並列取得し、各source約2500文字のfacts、記録時刻、鮮度、切詰めの有無を返します。詳細なsource対応表は [jarvis-agent.md](jarvis-agent.md) を参照。

`PETIT_CONTEXT_BROKER_TIMEOUT_SECONDS`（既定10秒）を超えたReadを待ち続けず、取得済みの部分結果を返します。実行中のproviderは強制停止できないため終了まで共有枠を占有し、新規要求は枠がなければ`source_busy`。実行待ちのキューを無制限に積みません。不正応答、providerエラー、staleを0件の成功として扱いません。2回目Callにも入口のactive work等を引き継ぎます。

### Call数の基準

```mermaid
flowchart LR
    direct[雑談 相談 一般知識] --> one[1 LLM Call]
    time[今何時] --> zero[0 LLM Call]
    read[Tasks Calendar Read] --> two[原則2 LLM Calls]
    complex[Write 複雑調査] --> deep[Deep Agent 必要回数]
```

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

`fallback_read`はSelectorへ公開しない内部グループです。Context Broker対象外の安全なfallbackまたはDeep Agentでだけ使用し、書き込みToolを含めません。

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

Agentの出力もPETIT Core Promptを共有し、Toolあり/なしで人格を切り替えません。

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
    register[pending_actions.pyがapproval_idを登録 10分TTL]
    api[POST /api/actions/{approval_id}]
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

    proposal --> args --> saveState --> confirmation --> register --> api --> decision
    decision -->|いいえ| cancel
    decision -->|はい| wrapper --> load
    load -->|いいえ| expired
    load -->|はい| validate
    validate -->|いいえ| invalid
    validate -->|はい| started --> dispatch --> failed
    failed -->|いいえ| failure
    failed -->|はい| resume --> readOnly --> final --> delete
```

`pending_actions.py` が短期のapproval状態、10分TTL、承認API、Sona Core互換分岐、承認後のTool dispatchを所有します。`chat.py` はAgent Runtimeが返した`pending_actions`を`pending_actions.register(...)`へ渡し、返された`approval_id`を`ChatResponse`へ載せるだけです。APIモデルは`chat_models.py`で共有し、確認Routerから`main.py`を参照しません。

Agentが自然文だけで「実行しますか？」と返した場合は承認として扱わず、確認対象Toolをcallするよう1回だけ再指示します。

---

## 6. 進捗表示

```mermaid
flowchart LR
    runtime[Brain / Agent Runtime]
    events["planning / gathering_context / tool_started / tool_finished / finalizing"]
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
    none[通常Brainへ]
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
    context[タスク 予定 記憶 BRAIN 作業 リマインダー 引き継ぎ]
    tasks[タスクと任意リスト]
    cal[時刻 予定 天気 リマインダー]
    know[BRAIN Notion 記憶検索]
    git[GitHub状況とRepository候補]
    web[ニュースと外部調査]
    mem[長期記憶 要約 復帰 引き継ぎ]
    project[Project Continuity]
    deterministic[決定論的処理]

    chat --> direct
    chat --> context
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
    twoPass[Broker対応Readは原則2回]
    brokerRead[Context BrokerはReadのみ]
    partial[provider片方失敗でも部分結果を維持]
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
    limits --> twoPass
    limits --> brokerRead
    limits --> partial
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

## 11. 任意のPC観測

```mermaid
flowchart TD
    startup[Module Registryのstartup] --> enabled{設定が有効か}
    enabled -->|いいえ| off[観測しない]
    enabled -->|はい| observer[独立Observer thread]
    observer --> git[指定Gitルートだけを読取 / timeoutあり]
    git --> app[任意で前面アプリ識別子]
    app --> cache[時刻付きsnapshotをメモリに保存]
    cache --> wait[停止可能な間隔待ち]
    wait --> observer
    cache --> api[GET /api/workspace-context]
    cache --> entry[Brain入口 / freshだけ文脈へ]
    shutdown[shutdown] --> stop[停止要求 / snapshotを破棄]
```

この拡張は既定無効で、Web利用の前提ではありません。サーバーPCだけを観測し、通知・外部操作・任意コード実行へ直接接続しません。

## 保守ルール

以下へ変更を加えた場合は、この文書の対応するMermaid図も同じ変更で更新してください。

- `/api/chat`と確認API
- 決定論的な会話ルート
- PETIT Brain / Context Broker / Capabilityグループ
- Agent Tool Loopと停止条件
- Tool Registryとrisk
- 確認付き書き込みとAgent state再開
- ProgressイベントとUI配信
- Project Continuity

Mermaid図と実装が一致しない状態でmainへ反映しないでください。

## 10. Desktop音声入口（Issue #253）

Desktopは既存の会話・承認・TTSを使用する。iPhone PWA / Vocal Shortcutは従来経路を維持する。
詳細と未確認事項は [desktop.md](desktop.md) を参照。

```mermaid
flowchart TD
    Tray[トレイ / グローバルショートカット] --> Main[Electron Main]
    Mic[任意のローカル待機音声] --> Wake[Porcupine utility process]
    Wake -->|検出のみ・PCMは送信しない| Main
    Main --> Stop[待機マイク停止]
    Stop --> Overlay[小型UI表示]
    Overlay -->|STT設定済み・音声開始| Capture[AudioWorklet録音 / 発話終了判定]
    Capture --> Validate[IPC送信元・WAV・同時実行上限検証]
    Validate --> STT[明示設定されたWhisper互換STT]
    STT -->|確定文字列| Voice[共有 voice.js]
    Overlay -->|文字入力| ChatUI[共有 app.js]
    Voice -->|通常発話| ChatUI
    Voice -->|確認への返事| Approval[既存確認ボタン]
    ChatUI --> ChatAPI[既存 /api/chat / PETIT Brain]
    ChatAPI -->|pending_actions| Approval
    Approval --> ConfirmAPI[既存 /api/actions / Agent state再開]
    ConfirmAPI --> Reply[共有返答UI]
    ChatAPI --> Reply
    Reply --> TTS[共有 /api/tts / 端末TTS]
    Hide[閉じる / ロック / スリープ] --> Cancel[録音・STT取消 / 遅延結果を破棄]
    Cancel --> Resume{非ロック・非スリープ・画面非表示・opt-in?}
    Resume -->|はい| Wake
```
