# PETIT Universe — Life / Task / Child Task

## 目的

PETITのタスクを、独立したProject階層ではなく、Life直下のTask親子構造として扱う。

```text
Life
├─ 単独Task
├─ 親Task（Projectの役割）
│  ├─ 子Task
│  └─ 子Task
└─ 単独Task
```

ProjectはUI上の別オブジェクトではない。必要なTaskそのものが親になり、その下に実行可能な子Taskがぶら下がる。

例:

```text
Life
└─ PETITを改善する
   ├─ タスクUIを刷新する
   └─ 音声応答を高速化する
```

## 階層ルール

- すべてのTaskはLife直下または親Taskの子に属する
- 親として選べるのはLife直下Taskだけ
- 階層は`Life → 親Task → 子Task`の2段に制限する
- 子Taskを持つ親Taskを別のTaskの子にはしない
- TaskはUIまたはChatからLife直下へ戻せる
- Notion Taskの親にはNotionへ同期済みのTaskだけを選べる

## ビューの役割

### Focus

- 選択中のLife直下Taskを中央星として表示する
- 中央Taskが親なら、その未完了High子Taskを軌道へ表示する
- 単独Taskの場合は中央Taskだけを表示する
- 親Taskセレクトと前後ボタンでFocus対象を移動する
- `Life › 親Task`のパンくずからLife一覧へ戻る
- タスクの選択と作業開始を分離する
- ボタンまたはスマホのピンチでOrbitを拡大・縮小する
- 遠景では主要Taskを優先し、拡大すると追加Taskとラベルを表示する

### Life

- Life直下Taskをカードとして一覧表示する
- 子Taskを持つTaskは親カードとして表示する
- 子Taskは親カードの内側へインデントして表示する
- 子を持たないTaskは単独Taskとして表示する
- 独立したProjectカードや`All`分類は作らない

### Tasks

- High「重要」とLow「あとで」を混ぜずに表示する
- 親Task列には、親がなければ`Life直下`、子なら親Task名を表示する
- 完了、元に戻す、High↔Low変更を行う

### Chat

- 選択中Taskを文脈としてPETITへ相談する
- `set_task_parent`を使い、確認後にTaskを別Taskの子へ移す
- 「XをPETIT開発の子タスクにして」または「XをLife直下へ戻して」に対応する
- 作業継続確認中にチャットへ返答した場合も、作業継続として扱う

## Task親子Relation

SQLiteの`tasks_cache`へ`parent_task_id`を追加する。

Notion由来Taskでは、既存の親Task Relationも保持する。

```text
parent_task_id       PETITローカルTask ID
parent_external_id   Notion親ページID
parent_external_ids  Notion親Relation配列
```

読み取り時はNotionの`parent_external_id`を優先してローカルTaskへ解決し、UI向けに以下を付与する。

```text
parent_title
root_task_id
root_title
hierarchy_role = root | child
child_count
has_children
```

既存Universe rendererとの移行互換として、`project_title`には一時的に`root_title`を入れる。ただし意味はProjectではなくLife直下の親Taskである。

## 親子変更

Task詳細の親Taskセレクトから次を行う。

```text
PATCH /api/notifications/tasks/{task_id}/parent
```

親へ移す場合:

```json
{"parent_task_id": 123}
```

Life直下へ戻す場合:

```json
{"move_to_life": true}
```

SQLiteへ即時反映し、Notion Taskは既存Outboxへ`parent_external_ids`を追加して非同期同期する。

## 作業セッション

タスクを選択しただけでは計測しない。詳細の「作業開始」を押した時だけ、既存の`/api/work-sessions`へ作業セッションを作る。

```text
選択中
  ↓ 作業開始
計測中
  ↓ 20分
継続確認
  ├─ 返答あり → 次の20分へ
  └─ 20分無応答 → 自動停止
```

セッションIDとactive task IDだけをlocalStorageへ保存し、開始時刻・一時停止時間・自動停止判定はSQLite上のサーバー状態を正とする。

## モーション設計

外部3Dライブラリを追加せず、CSSとVanilla JavaScriptで空間感を作る。

- 星雲の呼吸
- 軌道の低速回転
- 子Task nodeの段階的な出現
- 選択中Taskの明確な発光
- ビュー切替時の短い奥行きトランジション
- Pointerによる微細なparallax
- ピンチズーム
- `prefers-reduced-motion`時はアニメーションを停止

モバイルでは表示Node数を抑え、ズーム時だけ追加Nodeを見せる。

## API

```text
GET   /api/notifications/tasks?priority=all&limit=500
PATCH /api/notifications/tasks/{task_id}/parent
POST  /api/work-sessions/start
GET   /api/work-sessions/{session_id}
POST  /api/work-sessions/{session_id}/respond
POST  /api/work-sessions/{session_id}/pause
POST  /api/work-sessions/{session_id}/resume
POST  /api/work-sessions/{session_id}/end
```

## 非目標

- 独立したProject階層の表示
- 3段以上のTask階層
- Three.jsや外部3Dライブラリ
- Done履歴の残光表示
- Taskのドラッグ&ドロップ

## 実機確認

- Life直下に単独Taskと親Taskが並ぶ
- 親Taskカード内に子Taskが表示される
- Task詳細から親を設定できる
- Task詳細からLife直下へ戻せる
- Notion Taskの親Relationが同期される
- Chatで親子変更を依頼し、確認後に反映される
- 親Task自身がOrbit上で子Taskとして重複表示されない
- タスクを選ぶだけでは時間が増えない
- 作業開始後だけ時間が増える
- 再読み込み後も作業状態が復元される
- Focus内で親Taskを前後移動できる
- ズーム段階で子Task表示数が変わる
- iPhoneでピンチズームできる
- `prefers-reduced-motion`で不要な動きが止まる
