# PETIT shared Toggle Switch

## 元にしたもの

- 見た目と動き: https://designbookmark.com/motion#db-toggle-switch
- ソース: https://designbookmark.com/motion-src/toggle-switch/（`switch.css` / `switch.js`）と `shared/`（`tokens.css` / `base.css` / `motion.js`）
- 2026-11-15 に上記を取得して移植した。依存なしの Vanilla JS。

## 動き（元と同じ値）

| 値 | 元 | PETIT |
|---|---|---|
| 位置スプリング（stiffness / damping） | `S(0, 320, 18)` | 320 / 18 |
| 伸びスプリング（stiffness / damping） | `S(0, 300, 20)` | 300 / 20 |
| 切替時の伸びの初速 | `w.v = 60` | 60 |
| つまみ / 移動量 / 最大の伸び | 26px / 20px / 10px | 同じ |
| 積分 | 1フレーム最大 1/30 秒・4分割 | 同じ |

つまみは進む方向へ伸び、端で小さく跳ねてから丸に戻る。トラックは進み具合に合わせてアクセント色で埋まる。

元との違い:

- 動いている間だけ `requestAnimationFrame` を回す（元は常時ループ）。動きは同じ。
- 色はページのテーマ変数（`--accent`、`--line-strong`、`--text`、`--muted`）を使う。設定画面では `setup.css` の青アクセント。
- `prefers-reduced-motion: reduce` のときはアニメーションせず切り替える。
- コードから `input.checked = ...` を設定したとき（設定の読込など）は動かさずに位置を合わせる。人が切り替えたときだけ動く。
- 元のデモ用の自動切替はない。

## 使い方

`/static/components/toggle-switch.css` と `/static/components/toggle-switch.js` を読み込む。

既存のチェックボックスをその場でスイッチにする（設定画面はこの方法）:

```js
window.PetitToggleSwitch.enhance(document.getElementById('sync-notifications'));
```

チェックボックス自体は残るので、`id`・`name`・`change` イベント・`input.checked` の読み書きはそのまま使える。キーボード（Space）とスクリーンリーダーは `role="switch"` 付きのネイティブ input が担う。

新しく行ごと作る:

```js
const sw = window.PetitToggleSwitch.mount(container, {
  label: '同期失敗の高優先度通知',
  description: '同期に失敗したとき、すぐに知らせます',
  checked: true,
  onChange: on => save({ sync_notifications: on }),
});
sw.setChecked(false);                     // 動かさずに合わせる
sw.setChecked(true, { animate: true });   // 切替アニメーション付き
sw.destroy();
```

## 配置

- `frontend/setup.html`（設定とサービス接続）: `.check` 行の7つのオン/オフ設定をスイッチ化。スイッチは行の右端。
- Notion ページ選択の一覧（複数選択）はチェックボックスのまま。

## テスト

- `node --test tests/test_toggle_switch.cjs`（スプリング値、伸びと跳ね、コードからの設定、reduced motion、destroy）
- 実ブラウザ: 隔離サーバー `tests.setup_ui_server` で設定画面を開き、7つのスイッチ、クリックとSpaceでの切替、保存→再読込での保持、390px幅で横スクロールなし、コンソールエラーなしを確認。
