# PETIT Universe — Focus Orbit

## 目的

PETITのタスク画面を、一覧中心のUIから「頭の中の宇宙」を操作する空間UIへ刷新する。

宇宙表現は装飾ではなく、既存のタスク構造と状態を理解しやすくするために使う。

## 概念対応

| PETIT | Universe UI |
|---|---|
| 生活全体 | 宇宙 |
| Area | 宇宙領域 |
| Project | 星座 |
| Objective | 中心星 |
| Action | 周囲の星 |
| active task | 強く発光する星 |
| Waiting / blocked | 暗く停止した星 |
| Done | 通常表示から外し、将来は残光として表示 |
| pending | 同期中 |
| synced | 同期済み |
| failed / conflict | 警告状態の星 |

## 今回のVertical Slice

最初から本格3Dや全Task CRUDを実装せず、既存APIで体験を確認する。

```text
/api/briefing
  ↓ SQLite由来のTask
Focus / Universe / Tasks

/api/chat
  ↓
Chatビュー
```

### Focus

- 現在のProjectを中心星として表示する
- 最大10件の未完了Actionを軌道へ配置する
- Highは大きく、Lowは小さく表示する
- Doing / Nowは内側の軌道へ寄せる
- Waiting / blockedは暗くする
- active taskは発光させる
- タスク選択時は詳細パネルを表示する

### Universe

- Projectごとに簡易星座カードを表示する
- Active Action件数を星の数として表す
- 選択するとFocusへ戻る

### Tasks

- Active / High / Allで絞り込む
- 名前、状態、優先度、期限、Project、同期状態を一覧表示する
- 行を選ぶとFocusと詳細へ戻る

### Chat

- 既存`/api/chat`を使う
- 選択中Actionを相談文へ取り込める
- 会話後に`/api/briefing`を再取得する

## active task

初期段階では次をlocalStorageへ保存する。

```text
petit_universe_active_task_id
petit_universe_active_started_at
```

これはUI体験の検証用であり、将来はProject Continuityまたは作業セッションのサーバー状態へ統合する。

## 旧UI

新UIは`/`から開く。

既存の通知、設定、制作伴走UIは`/static/legacy.html`へ退避し、新UIから戻れるようにする。

## 非目標

- Three.jsや外部3Dライブラリ
- 物理シミュレーション
- ドラッグによるRelation変更
- Objective / Actionスキーマmigration
- Task CRUD APIの新設
- 数百ノードの常時描画

## 次の段階

1. 実ブラウザとiPhoneで操作性を確認する
2. `/api/work-graph`を追加する
3. active taskをサーバーへ保存する
4. Objective / Action / blocked_byを正式データから描画する
5. 詳細パネルから既存Task更新経路へ接続する
6. Done履歴を残光として表示する
