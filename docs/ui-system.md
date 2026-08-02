# PETIT UI System v0.7.0

## 目的

PETITの各画面を個別に装飾するのではなく、共通の情報階層・操作状態・モーション・レスポンシブ規則で統一する。

## 読み込み構造

`frontend/chat_input.js`がUniverse UIを検出した場合だけ、次を追加読み込みする。

- `frontend/petit-ui-system.css`
- `frontend/petit-ui-system.js`

既存のLife・Focus・Tasks・Today・Remind・Chat実装とAPI契約は変更せず、最後の共通レイヤーとして適用する。

## 情報階層

常設コンテキストバーでは次を表示する。

1. 現在のView
2. 現在選択しているTaskまたは親Task
3. 作業セッションと経過時間
4. 同期状態

画面ごとに別々だった「いま何を見ているか」「作業中か」「同期できているか」を、移動しても見失わないようにする。

## デザイン原則

- 宇宙表現は背景と奥行きに限定し、情報より強くしない
- High Taskと現在の作業を最優先にする
- 同じ意味のボタン、カード、状態には同じ見た目を使う
- モバイルでは主要Viewを下部ナビへ固定する
- 操作領域はおおむね40〜48pxを確保する
- ダーク／ライトを同じ構造で提供する
- `prefers-reduced-motion`を尊重する
- ページ非表示時はアニメーションを停止する

## Focusの立体表現

Three.jsは現時点で導入されていない。新しい依存や描画ループを増やさず、既存Orbitへ次を追加する。

- CSS `perspective`
- ノードごとの浅いZ深度
- ポインター位置による小さな傾き
- 既存ズーム、Orbit座標、reduced motionとの統合

3Dはタスクの位置関係を感じやすくする補助であり、操作や文字の可読性を優先する。

## 入力

日本語IME変換中のEnterでは送信しない。送信は `Ctrl+Enter` または `Cmd+Enter` とし、既存の`compositionstart`、`compositionend`、`event.isComposing`、`keyCode 229`の保護を維持する。

## 検証

`tests/test_unified_ui_system.py`で次を確認する。

- 共通CSS／JSがUniverseで読み込まれる
- ライトテーマとreduced motionがある
- コンテキストバーとCSS 3Dがある
- タブとパネルへARIA roleを設定する
- IME Enter保護を維持する
- Web UIバージョンがv0.7.0である

実ブラウザではPC幅、390x844、実iPhone PWA、ソフトウェアキーボード表示、ライト／ダーク、Focus Orbit負荷を別途確認する。
