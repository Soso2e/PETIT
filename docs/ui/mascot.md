# プティちゃん（PETITマスコット）

Status: 現行（v0.56.0）
関連Issue: [#440](https://github.com/Soso2e/PETIT/issues/440)（前段: #432 Desktop SVGマスコット）

梨＋土星の輪のマスコット「プティちゃん」を、Web と Desktop で同じ軽量SVGモジュールから描く。表示専用で、会話本文・音声・認証情報は扱わない。

## ファイル

| ファイル | 役割 |
| --- | --- |
| `frontend/mascot/petit-mascot.js` | **正本**。SVG生成、表情・動作・状態のレジストリ、色、静的SVG出力（DOM不要） |
| `frontend/mascot/petit-mascot.css` | パーツの表示切替と動作アニメーション（CSSのみ・フィルターなし） |
| `frontend/mascot/petit-mascot-web.js` / `.css` | Web版: 画面内の歩行・クリック/ドラッグ反応・設定カード |
| `frontend/mascot/gallery.html` | 表情・動作・状態・色の確認ページ（`/static/mascot/gallery.html`） |
| `frontend/mascot/petit-mascot.svg` | アイコン等の元にできる静的SVG（`toStaticSVG` で再生成できる） |
| `desktop/mascot/*` | 正本の複製（Electron の `file://` 画面用）。`npm run sync:mascot` で更新し、差分はテストが検出する |
| `desktop/pet.*`, `pet-state.cjs`, `pet-config.cjs` | Desktop常駐ウィンドウ、状態の絞り込み、見た目設定・散歩の計算 |

## 拡張のしかた

- **表情を足す**: `EMOTIONS` に `{ eyes, mouth, brows, cheeks, sweat, fx, lid, look }` を1行追加。パーツは既存の組み合わせでよい。
- **形（パーツ）を足す**: `PARTS.<slot>` に描画関数を1つ追加。`paint(kind, strokeWidth)` を使えば色はCSS変数・静的出力の両方に対応する。
- **動作を足す**: `ACTIONS` にキー（一回きりなら `ms`）を足し、CSSに `[data-action="名前"]` のルールと keyframes を足す。
- **PETITの状態との対応を変える**: `STATES`（`idle / wake / active / typing / listening / thinking / speaking / approval / success / error / offline / sleep`）。`transient` 付きは一時表示後に元へ戻る。
- **色を足す**: `PRESETS` に `{ label, body, ring, leaf }`。明暗のグラデーション・影は本体色から自動計算する。
- テスト（`tests/frontend/mascot.test.cjs`）が、未定義パーツ参照・CSSのない動作・重いフィルターを検出する。

## 状態連動

`session.js` と `voice.js` は `document` に `petit:mascot` イベント（`detail: { state }` のみ）を出す。

- 送信開始 → `thinking`、結果 → `success` / `approval`（確認待ち）/ `error`
- 音声入力中 → `listening`、読み上げ中 → `speaking`（チャンク間のちらつきは450msで吸収）
- Web版は入力欄フォーカスで `typing`（入力欄を見る）、3分無操作で `sleep`
- Desktopの小型チャット（`frontend/desktop/overlay.js`）は `speaking` を状態として、成功・失敗・確認待ちを一回きりの反応としてElectronへ渡す。mainは `pet-state.cjs` の許可リストで検証し、反応はモードとして保存しない
- Desktopは OS の無操作が5分続くと `sleep`（表示中だけ30秒ごとに `powerMonitor.getSystemIdleTime()` を確認）

## Web版の振る舞い

- レイヤー全体は `pointer-events: none`。本体（既定72px）だけがクリック・ドラッグに反応する。
- チャット欄が見えていればその上端を床にして歩く。見えない画面ではビューポート下端。ボタン・入力欄・リンク・Canvas の上には立ち止まらない（`elementsFromPoint` で確認）。
- 待機中は 3.5〜11.5秒ごとに「歩く／見回す／跳ねる／伸び／ダンス」などを1つ選ぶ。クリックで反応、5回連打で怒る、ドラッグでぶら下がり→落下→着地。視線はカーソルを追う。
- 負荷: rAF は歩行・落下中だけ。待機中は setTimeout とCSSアニメーションのみ。タブ非表示でアニメーション・タイマーを停止。軽量表示（`data-petit-performance="lite"`）では輪・葉の常時アニメーションを止める。
- 設定（Settings の「プティちゃん」カード、`localStorage` の `petit_mascot_web_v1`）: 表示・歩き回る・動き（OSに従う／常に動かす／止める）・大きさ（40〜160px）・カラープリセット・本体/輪の任意色。既定は幅760px超で表示、モバイルとDesktopワークスペース内では非表示。

## Desktop版の振る舞い

- Desktop設定「画面上のプティちゃん」: 表示（既定OFF）、大きさ（56〜200px）、カラー、本体/輪の色、動き、散歩（既定OFF）。値は `pet-config.cjs` で検証してから `desktop.json` に保存し、描画に必要な値だけをレンダラーへ送る。
- 窓は大きさに合わせて変わり、足元（下辺中央）を保つ。
- 散歩: 20〜60秒ごとに同じ高さで最大260px移動（30fpsで `setPosition`）。会話中・スリープ/ロック中・ユーザーがつまんで動かしたときは止まる。
- 「動き」が「OSに従う」のとき、OSの「視差効果/アニメーションを減らす」がONなら静止する。動かしたい場合は「常に動かす」を選ぶ。

## トレイ・メニューバー・アプリアイコンへの応用（未実装）

- `PetitMascot.toStaticSVG({ emotion, colors, size, fx })` は DOM なしで単体SVG文字列を返す（mainプロセスでも `require` できる）。状態別のトレイ画像はこれをPNGへ変換して作る想定。
- macOS メニューバーはテンプレート画像（単色）が基本のため、輪郭だけのバリエーションが別途必要。
- アニメーションするトレイは、数フレームを事前に画像化して切り替える方式が負荷面で妥当。

## 未確認

- Windows / macOS 実機での常駐時のCPU・メモリ、散歩中の描画、マルチディスプレイ、実際の音声会話との同期
- iPhone / Android 実機での表示（モバイルは既定OFF）
