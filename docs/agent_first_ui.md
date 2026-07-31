# Agent-first会話とWeb UI操作面

Issue #117で決めた、PETITの会話とWeb UIの役割分担です。

## 結論

PETITの通常会話は、最終返答までAgent Runtimeへ通します。

Capability Selectorは、軽量な最終返答を作るためではなく、そのターンでAgentへ公開するTool群を絞るためだけに使います。Tool不要の雑談でもAgentが返答します。

一方、タスク更新、通知確認、予定編集などの明示操作は、会話だけに依存させずWeb UIから直接行えるようにします。

```text
通常会話
  → Agent Runtime
  → 必要な場合だけ限定Tool
  → 自然な返答

明示操作
  → Web UI
  → 既存API / Tool境界
  → 承認・冪等性・監査
```

## Agent既定にする理由

- 短い返答を別モデルへ逃がすと、会話の性格や判断が分断される
- DeepSeekをAgentとして使う前提では、通常会話をAgentから外す利点が小さい
- 「見直しない」「そのままで」「大丈夫」のような文脈依存発話を、一貫した履歴で判断しやすい
- 雑談、相談、進捗確認、Tool利用を同じAgentが扱える

## 残す安全境界

Agent既定は、すべてを自由実行にする意味ではありません。

次は維持します。

- 書き込み前の確認
- Tool引数検証
- 同一操作の冪等性
- 認証・権限境界
- Tool結果にない外部事実を作らない制約
- Project Continuityの確認済みproject identityとsource mapping
- 正確な現在時刻など、LLMを使う意味がない決定論的読み取り

Capabilityを限定公開する理由も、主目的は速度ではなく、誤Tool選択・権限逸脱・不要な書き込み提案を減らすためです。

## Web UIの役割

Web UIはチャット画面だけではなく、PETITが自走した結果を確認し、直接操作できる面にします。

優先候補:

1. 通知センター
2. タスク詳細・編集
3. 予定詳細・編集
4. 現在のproject / next action表示
5. Agentが提案した保留操作の確認

会話は「意図を伝える入口」、UIは「状態を見て確実に操作する入口」とします。

## 通知を残せるか

現状でも、生成した通知はSQLiteの`notification_events`へ保存されています。Push通知が端末へ届かなかった場合や、カテゴリ設定がOFFだった場合も、イベント自体は記録できます。

ただし、現在のWeb UIには通知履歴を読むAPIと一覧画面がなく、`read_at`や`resolved_at`もありません。そのため、ユーザーから見える通知センターとしては未完成です。

## 通知センターの次期設計

`notification_events`へ次の状態を追加します。

```text
read_at
resolved_at
entity_type
entity_id
action_url
```

通知payload例:

```json
{
  "event_id": 123,
  "category": "high_task",
  "title": "期限が近いタスク",
  "body": "Bobの歩行アニメーションを確認してください",
  "entity_type": "task",
  "entity_id": "notion-or-petit-task-id",
  "url": "/?task=notion-or-petit-task-id&notification=123"
}
```

通知をタップしたときは、PWAがURLを開き、タスク詳細パネルを表示します。

## タスク詳細画面

タスク詳細では最低限、次を操作できるようにします。

- タイトル
- 状態
- 期限
- 優先度
- エリア
- project
- 完了
- 同期状態

更新は既存の`update_task` / `complete_task`と同じ検証・同期・監査境界を通します。UIだから確認を省略するのではなく、操作内容が明確なフォーム入力であることを利用し、必要な確認だけに減らします。

## 実装順

### Phase 1: Agent既定

- Capability Selectorから直接返答を廃止
- 挨拶をinstant replyで短絡しない
- 通常会話の最終生成をAgentへ統一

### Phase 2: 通知センター

- 通知イベント一覧API
- 未読・既読・解決状態
- 通知パネル内の履歴表示
- Push payloadへevent idと対象情報を追加

### Phase 3: タスクdeep link

- `?task=<id>`からタスク詳細を開く
- 更新・完了操作
- 通知から開いた場合は既読化
- 更新後に通知を解決済みにする

## 非目標

- Agentへ全Toolを無制限公開する
- 書き込み確認を全面廃止する
- 通知だけを正本にする
- 会話を廃止して管理画面中心にする

AgentとUIは競合させず、同じデータと安全境界を共有する2つの入口として扱います。
