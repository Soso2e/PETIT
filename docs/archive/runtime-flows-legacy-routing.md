# PETIT Runtime Flows — 旧キーワードルーティング（アーカイブ）

> Status: **アーカイブ** / 2026-11-06（v0.45.0）で実装を撤去。後継: [../runtime-flows.md](../runtime-flows.md)、[../architecture.md](../architecture.md)
>
> v0.30系までの「決定論的ルート → Capability Router → Context Broker → Deep Agent」の会話経路。
> #345で本番text経路から外れた後も画像付き会話だけが使っていたが、v0.45.0で画像を `vision_reply.py` へ移し、
> `agent.py` / `agent_legacy.py` / `agent_runtime.py` / `brain_runtime.py` / `capability_router.py` / `context_broker.py` / `model_router.py` /
> `dialogue_resolution.py` / `project_router.py` / `project_resume.py` / `project_source_refresh.py` / `task_completion*.py` / `task_work_intent.py` /
> `task_conversation.py` / `list_conversation.py` / `date_parser.py` / `recall.py` / `agent_state.py` / `agent_progress.py` / `tools/agent_actions.py` を削除した。
> 以下の図は削除前の記録で、現行の実装ではない。コードはGit履歴で参照できる。

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
- `backend/task_work_intent.py`
- `backend/tools/registry.py`
- `backend/agent_state.py`
- `backend/agent_progress.py`
- `backend/project_router.py`
- `backend/task_completion_intent.py`
- `backend/dialogue_state.py`
- `backend/dialogue_resolution.py`

---

## 1. 会話全体フロー

### 画像添付のRead専用経路（v0.31.0 / #333）

```mermaid
flowchart TD
    file[Web / Desktop: 画像実体] --> intake[POST /api/attachments: 8MiB・30秒上限]
    intake --> check[実体decode / PNG JPEG WebP / 画素と辺の上限]
    check --> normalize[EXIF向き補正・metadata除去・長辺4096pxまで]
    normalize --> store[Core非公開storage + SQLite / session hash + opaque ID]
    store --> request[POST /api/chat: attachment_ids + 任意message]
    request --> owner{同じsession・期限内・4枚以下}
    owner -->|不一致・欠落| error[error応答 / 認識したふりをしない]
    owner -->|一致| consent{画像・認識内容の外部送信許可}
    consent -->|外部・許可なし| error
    consent -->|許可あり またはlocal| capability{モデル画像能力}
    capability -->|Flash対応 / LM Studio selected model vision=true| vision[Vision Adapter: 観測JSONを1 Callで抽出]
    capability -->|非対応・不明・通信失敗| error
    vision --> validated{JSON schema / 画像ID対応 / 上限}
    validated -->|失敗| error
    validated -->|成功| calc[Decimalによる既知Steam比率検証 / 不明・重複値は計算しない]
    calc --> brain[Core Promptで観測と考察を分けて回答 / 通常1 Call]
    brain --> saved[既存conversations + TTL付き観測JSON / 添付ID保持]
    saved --> reply[自然な返答 / usage・実Call数]
    store --> ttl[24時間で参照拒否 / 60秒周期と起動時cleanup / 明示DELETE]
```

画像経路は `agent.run` / Capability選択 / Tool Loopへ入らず、画像内の命令からWrite・承認を生成しない。外部送信は `PETIT_ALLOW_CLOUD_IMAGES` が既定OFF。VisionのProviderは既存DeepSeek Flashを優先し、`PETIT_VISION_PROFILE=local` の場合はLM Studio `/api/v1/models` の選択モデル `capabilities.vision=true` が必要。未確認モデルは失敗にする。観測の回答生成先が外部の場合も同意を再検査する。通常2 Call、空出力再試行は最大各1回。HTTP timeoutは画像経路で各45秒。画像経路のMarkdown/Chroma自動exportは停止し、認識JSONは24時間で削除する。既存会話の返答/添付IDは既存履歴の保持方針に従う。

画像とProject/GitHubの自動照合、Discord、新Thread/Turn APIはこの経路に未接続。後続は [計画](../channels/multimodal-discord-plan.md) と #245/#246/#303/#304を参照する。session IDは既存ローカルClientの会話境界であり、インターネット公開用のユーザー認証ではない。

```mermaid
flowchart TD
    input[/ユーザー入力/]
    api[chat.py: POST /api/chat]
    validate{空メッセージか}
    bind[request_id と session_id を束縛]
    agentEntry[agent.run]

    namedTask{名前付きタスク完了か}
    namedTaskRoute[SQLiteの tasks_cache で候補解決]
    taskResume{名前付きTask再開か}
    taskResumeRoute[Task名を照合し一意なら作業計測を再開]
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
    save[会話をSQLiteへ保存 / 圧縮State更新 / focusは維持]
    artifacts[要約や索引などを非同期保存]
    output[/返答 pending_actions model_route/]

    input --> api --> validate
    validate -->|はい| output
    validate -->|いいえ| bind --> agentEntry
    dialogue{Pending Dialogue / Task照応 / 明示Task・Session操作か}
    dialogueHandle[候補確認またはstable IDでTask Tool実行]
    dialogueSave[Tool Registry成功hookでfocusを更新]
    agentEntry --> dialogue
    dialogue -->|はい| dialogueHandle --> response
    dialogueHandle -.->|Tool成功時| dialogueSave --> response
    dialogue -->|いいえ| namedTask
    namedTask -->|はい| namedTaskRoute --> response
    namedTask -->|いいえ| taskResume
    taskResume -->|既存Task またはTask明示| taskResumeRoute --> response
    taskResume -->|対象外 またはTaskなしのProject候補| projectRoute
    projectRoute -->|はい| projectHandle --> response
    projectRoute -->|いいえ| exactTime
    exactTime -->|はい| timeTool --> response
    exactTime -->|いいえ| brain --> selector --> route
    route -->|reply| directReply --> response
    route -->|request_context| context --> parallel --> packet --> unfinished{元の依頼に未実行ActionとCapabilityがあるか}
    unfinished -->|いいえ| second --> response
    unfinished -->|はい| capability
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
    calendar["get_schedule(日付または予定名query)"]
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
    packet --> partial --> actionLeft{continue_actionとCapabilityが明示されているか}
    actionLeft -->|いいえ| second --> final
    actionLeft -->|はい| reuse[元の依頼と取得済みPacketを既存Agentへ引継ぎ] --> map
    result -->|route_to_agent| route --> parse --> map --> agent
```

日時はsystem promptへ毎ターン結合せず、相対日付・相対時刻があるターンだけuser側へ注入します。active / pausedのWork Sessionがある場合だけ、小さいuser contextをConversation Entryへ付加します。

Context Brokerは `tasks` / `calendar` / `memory` / `brain` / `work` / `reminders` / `handoff` に対応します。 Calendar Readは日付またはキーワード`query`を`get_schedule`へ渡し、両方未指定なら`date_or_query_required`を返します。TimeTree等のSQLiteキャッシュの題名・説明・場所を検索し、日付未指定の検索では未来を優先します。Brokerは具体Tool名をLLMへ大量公開せず、固定したRead処理へ変換し、Toolのriskも実行直前に検証します。独立sourceは最大4件を並列取得し、各source約2500文字のfacts、記録時刻、鮮度、切詰めの有無を返します。詳細なsource対応表は [jarvis-agent.md](../core/jarvis-agent.md) を参照。

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
    current{同じTaskのセッション状態}
    resumePaused[同じセッションをresume_sessionで再開]
    keepActive[計測を継続し重複作成しない]
    sqlite[(work_sessions と work_session_events)]
    active[GET active 経過秒を計算]
    update[一時停止 再開 続行 終了]
    report[今日または1から90日集計]
    ui[Universe Today Chat]
    view{Task Detailの表示領域}
    selected[Univは選択中のTask]
    working[Univ以外はactiveまたはpausedセッションのTask]
    no_work[作業なし または自由入力の作業名]

    request --> resolve
    resolve -->|失敗| ambiguous
    resolve -->|成功| start --> current
    current -->|paused| resumePaused --> sqlite
    current -->|active| keepActive
    current -->|別Task またはセッションなし| sqlite
    update --> sqlite
    sqlite --> active --> ui
    sqlite --> report --> ui
    ui --> view
    view -->|Univ| selected
    view -->|それ以外| working
    working -->|Taskなし| no_work
```

Notion Task DBへ作業時間プロパティは追加しません。SQLiteのセッションへPETIT内部`task_id`を保存し、Notionを含むタスク正本と参照で結びます。開始・一時停止・再開・終了はイベントとして残すため、日付をまたぐ休憩も暦日単位で集計できます。`start_work_session`と`update_work_session`は明示依頼時の低リスク書き込み、`get_work_status`と`get_work_report`は読み取りです。

「HERE再開」「HEREタスク再開」「HERE作業再開」はProject判定より前にSQLiteの既存未完了Taskを照合します。入力どおりの完全一致、末尾の「タスク／作業」を除いた完全一致、一意な部分一致の順で解決し、複数候補では書き込みません。Task明示で0件ならTaskが見つからない旨を返し、Project登録へ流しません。Projectを明示した入力は従来経路を維持し、同名TaskとProjectがある省略入力は選択を求めます。終了済みの作業は保持して新しい計測を開始し、Taskの状態自体は変更しません。

---

## 3. Agent Tool Loop

```mermaid
flowchart TD
    call[Agentモデルを呼ぶ]
    hasCalls{Tool callがあるか}

    answer[回答本文を取得]
    empty{回答が空か}
    fallbackAnswer[言い換えを求める固定文]
    incomplete{作業予告・重複確認またはActionにWrite実行結果がないか}
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
    confirmation{Tool riskが確認対象か}
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
    incomplete -->|いいえ| evidence[実行結果を優先 / 失敗・部分成功を固定文で報告] --> finalizing --> final
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

親子関係の変更は`set_task_parent`へ集約します。タスク名変更も同時に必要な場合は、同じTool callの`title`へ含めます。作成・変更・完了・親子変更・同期再試行は、ユーザーの明示指示がある場合に限ってAgentがToolをcallし、`low_risk_write`として同じターン内で実行します。対象が曖昧な場合はToolをcallせず、候補を絞る質問を返します。

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
    observe[Task成功 / Workの対象IDと実行状態をfocusとlast_actionへ / best effort]

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
    error -->|いいえ| observe --> result
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

タスク操作では`create_task`、`update_task`、`complete_task`、`set_task_parent`、`retry_task_sync`を可逆な`low_risk_write`として扱います。予定追加、BRAIN本文編集、外部ソースとの紐付けなど影響範囲が広い操作は`confirm_write`を維持し、削除などの`destructive`は常に確認対象です。riskにかかわらず、書き込みToolの引数はschemaで検証してから実行します。

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
    dispatch[元のsessionを束縛して対象Toolをdispatch / 成功hook]
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

`pending_actions.py` が短期のapproval状態、10分TTL、承認API、承認後のTool dispatchを所有します。`chat.py` はAgent Runtimeが返した`pending_actions`を`pending_actions.register(...)`へ渡し、返された`approval_id`を`ChatResponse`へ載せるだけです。APIモデルは`chat_models.py`で共有し、確認Routerから`main.py`を参照しません。

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
    visible{Desktop小型画面は表示中?}
    ui[Web / Desktop UIの一時ステータス]
    history[通常会話履歴]

    runtime --> events --> emit --> jobs --> api
    visible -->|表示中・Webは従来どおり| api --> ui
    visible -->|非表示| skip[Desktop取得休止・再表示で即時取得]
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
    execute[complete_taskを即時実行]
    failed{書き込み成功か}
    success[完了を反映したと回答]
    failure[未反映を明示]

    input --> extract
    extract -->|いいえ| skip
    extract -->|はい| cache --> score --> active
    active -->|いいえ| completed
    completed -->|はい| already
    completed -->|いいえ| none
    active -->|はい| unique
    unique -->|いいえ| multiple
    unique -->|はい| execute --> failed
    failed -->|はい| success
    failed -->|いいえ| failure
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

    guard[Dialogue State入口でTask確認回答を先に処理]
    workGuard{名前付きTask再開に該当するか}
    workHandle[Task照合と作業セッション再開 または候補確認]
    input --> guard --> workGuard
    workGuard -->|はい| workHandle
    workGuard -->|いいえ| registration
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
    args[全書き込み引数を実行前に検証]
    defer[作業予告のみの回答を1回再実行]
    confirm[confirm_write destructiveは承認必須]
    explicit[可逆なタスク変更は明示指示時のみ即時実行]
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
    limits --> explicit
    limits --> resume
    limits --> approval
    limits --> writeOnce
```

---

## Dialogue Stateと確認回答 (#294)

```mermaid
flowchart TD
    U[同一sessionの入力] --> Load[SQLite Stateを読取 / 失敗はfallback]
    Load --> Pending{10分以内のtasks所有Pending?}
    Pending -->|候補回答| Select[保存した順序で名前 ID 前者 後者 番号を選択]
    Select --> Claim[Pending IDを原子的に一度だけ消費]
    Claim --> Valid[stable IDで現在のTaskとsourceを再確認]
    Pending -->|cancel| Cancel[Pendingのみ解除]
    Pending -->|明示した別の話題| Clear[Pending解除 / 通常入口へ]
    Pending -->|未解決の短い回答| Ask[Task候補質問を維持 / Work補足は再実行せず通常Brainへ]
    Pending -->|なし| Focus[24時間以内のfocus / 最大8件]
    Focus --> Unique{同一turnで一意か}
    Unique -->|いいえ| Save[操作と候補を保存 / 短く確認]
    Unique -->|はい| Valid
    Valid --> Risk[既存low_risk_write / Task hierarchy検証]
    Risk --> Tool[既存create update complete set_parent start_work_session]
    Tool --> Hook[Registry共通hook / Task成功・Work結果と対象IDを記録]
    Hook --> Reply[結果を返す / 外部同期と部分失敗を区別]
    Tool --> Work[Work開始はSQLite BEGIN IMMEDIATEで同一Taskのactive・pausedを再利用]
    Work --> Verify[返却session IDと保存済みactive Taskを照合]
    Verify -->|一致| Reply
    Verify -->|失敗・不一致| Retry[10分TTLの既存Pendingへ元依頼・対象ID・failed状態を保持]
    Retry -->|明示した再試行だけ| Claim
```

Task clarificationはaction approvalではありません。確認付きwriteは既存確認APIのままです。大量一覧ReadやTask失敗結果はfocusを上書きしません。Work開始失敗は再試行対象としてIDを保持しますが、成功した作業状態とは区別します。Frontend `history`は互換維持し、Dialogueの正本はsession別Backend SQLiteです。明示的な話題転換・キャンセル後は短い開始だけで旧対象を再実行しません。詳細と検証範囲は [Conversation-to-Action Reliability](../core/conversation-action-reliability.md)。
