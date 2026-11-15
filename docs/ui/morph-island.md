# PETIT shared Morph Island

## Reference & Springs

- Reference: https://designbookmark.com/motion#db-morph-island
- Source: https://designbookmark.com/motion-src/morph-island/index.html (`island.css`, `island.js`)
- Shared tokens: https://designbookmark.com/motion-src/shared/ (`tokens.css`, `base.css`, `motion.js`)
- `frontend/components/morph-island.js` と `morph-island.css` は上記ソースの物理スプリング定数をそのまま使用している：
  - `--island-w: 380 24`（width morph: stiffness 380, damping 24）
  - `--island-h: 300 22`（height morph: stiffness 300, damping 22、縮小時は stiffness 1.3x）
  - press spring: stiffness 520, damping 18
  - max radius: `32px`（`min(height / 2, 32)`）
  - volume give: `width * (1 + clamp(-H.v / 7000, -0.05, 0.05))`
  - コンテンツ切替: 2レイヤーによるブラー付きクロスフェード（`0.09s` 遅延）
- `tests/test_morph_island.cjs` は上流の積分器（dt上限 1/30 秒・1フレーム4サブステップ）を別に実装し、伸長・縮小の両方で幅・高さ・角丸・スケールを毎フレーム比較して一致を確認している。
- reduced motion では、モーフの途中で設定が変わった場合も含めて目標値へ即座に移る（上流は臨界減衰のスプリングで動き続ける。PETITの意図的な差分）。
- 色・フォント・影は PETIT の `petit-ui-system.css`（`--ui-surface-solid`, `--ui-text`, `--ui-muted`, `--ui-ok`, `--ui-warn`, `--ui-danger`, ダーク/ライト両テーマ）に従う。

## Placement & Live Status Integration

- `frontend/universe.html` 読み込み時に `frontend/components/petit-island-status.js` が画面上部中央（`.petit-island-dock`）へ自動マウントし、以下の状態を優先順に表示する：
  1. 会話・音声の即時状態（`petit:mascot` イベント: `listening` / `thinking` / `speaking` / `approval` / `error` / `success`）
  2. 開発ジョブ実行中・確認待ち（`GET /api/coding/activity?limit=10`）
  3. 未読通知（`GET /api/notifications/events?state=pending&limit=10`）
  4. 作業セッション計測中・一時停止中（`GET /api/work-sessions/active` + 1秒ごとの経過時間表示）
  5. `idle`（待機中: `PETIT`）
- アイランドをクリック（タップ）すると、表示中の状態に対応する画面（`development` / `reminders` / `focus` / `chat`）へ移動する。
