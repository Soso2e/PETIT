# PETIT Motion Continuity v0.8.0

## 目的

Life・Focus・Tasksを別ページとして切り替えるのではなく、同じTaskを異なる距離・情報密度で見る一つの空間として接続する。

## 構成

- `frontend/petit-motion.js`: 遷移状態、共有要素、キャンセル、タブ指標、DOM装飾
- `frontend/petit-motion.css`: 共有要素Ghost、View入場、奥行き反応、スマホTasks、Chatシート
- `frontend/life-map.js`: Life内の配置と接続線のみ。View遷移は担当しない
- `frontend/life-transition.css`: LifeからFocusへ進む際の環境反応のみ

## Transition Coordinator

遷移は次の順序で進む。

1. 現在の遷移をキャンセルする
2. 移動元要素の位置を取得する
3. PETIT本体の状態変更を先に実行する
4. 移動先Viewを描画する
5. 同一`data-motion-key`の移動先を取得する
6. 固定配置GhostをFLIP方式で移動する
7. View入場アニメーションを完了する
8. Ghostと一時状態を削除する

状態変更をアニメーション完了後へ遅延させないため、途中キャンセルや連打でも表示と内部状態が分離しない。

## Motion key

同一Taskは次の形式で関連付ける。

```text
data-motion-key="task-<task id>"
```

対象:

- LifeのTask
- Life直下の親Taskカード
- Focus Orbitノード
- Focus中央ノード
- Tasksの行

Tasksの行は既存DOMへTask IDがなかったため、取得済みTask一覧とタイトル・期限・親Taskを照合し、描画後にIDを付与する。

## 操作

### Life / Tasks

- 1回目: 選択
- 同じTaskの2回目: 選択要素を起点にFocusへ共有要素遷移

### タブ

- Life / Focus / Tasks: 選択中Taskまたは親Taskを可能な範囲で共有要素として引き継ぐ
- Today / Reminders / Chat: 共通View入場へフォールバックする

## キャンセル

新しい遷移が始まった場合、古いAnimationをcancelし、GhostとHTML上の遷移属性を削除する。遷移ごとのIDを比較し、古い非同期処理が後からcleanupや状態変更を行わないようにする。

## パフォーマンス

- 常時requestAnimationFrameを追加しない
- Ghostは遷移中だけ作成する
- `transform`、`opacity`、`filter`を中心にする
- ページ非表示時の既存Orbit停止を維持する
- Pointer追従は既存の非Touch条件を維持する
- `prefers-reduced-motion`ではGhostを作らず、状態変更を即時実行する

## 実機確認

- PC: Life → Focus → Tasks → Focus → Life
- 390x844: タブ指標、Taskカード、Chatシート
- iPhone PWA: セーフエリア、キーボード、連打、画面回転
- 低電力モード: Orbitと共有要素のフレーム落ち
- reduced motion: 機能を失わず即時切替できること
