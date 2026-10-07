# PETIT UI System v0.25.0

## 目的

PETITの各画面を個別に装飾するのではなく、共通の情報階層・操作状態・モーション・レスポンシブ規則で統一する。

## 読み込み構造

`frontend/chat_input.js`がUniverse UIを検出した場合だけ、次を追加読み込みする。

- `frontend/petit-ui-system.css`
- `frontend/petit-ui-system.js`

既存のLife・Focus・Tasks・Today・Remind・Chat実装とAPI契約は維持する。

`petit-corner-shell.js`は既存Shell CSSの後へ`petit-ui-polish.css`を追加する。共通トークンへGalaxy・Shellの色を接続し、旧装飾CSSに上書きされない具体的なセレクタで仕上げる。Desktopも同じCSSを読み込み、`petit-desktop-ui`で小型ウィンドウ専用の調整を適用する。

- Universeの天体・WebGL・カメラ操作は既存描画を維持する。
- Tasks / Chat / Settings / Remindersは背景・境界・文字・余白を揃える。
- 960px未満は四隅ナビ、PC幅はサイドバーを使用する。
- 空一覧の`colspan`セルは通常のタスク行Gridから外し、全幅で表示する。
- 変更時はService Workerのキャッシュ世代を更新し、仕上げCSSもprecacheへ含める。

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
- モバイルでは主要Viewを右上、補助機能を左下へ配置する
- 操作領域はおおむね40〜48pxを確保する
- ダーク／ライトを同じ構造で提供する
- `prefers-reduced-motion`を尊重する
- ページ非表示時はアニメーションを停止する

## Focusの立体表現

旧Focus Orbitは次のCSS表現を使用する。現在のUniverse主描画はThree.js WebGLで、利用できない場合のみCSS表示へフォールバックする。

- CSS `perspective`
- ノードごとの浅いZ深度
- ポインター位置による小さな傾き
- 既存ズーム、Orbit座標、reduced motionとの統合

3Dはタスクの位置関係を感じやすくする補助であり、操作や文字の可読性を優先する。

## 入力

日本語IME変換中および確定時のEnterでは送信しない（変換確定のみ）。変換完了後のEnterで送信し、`Shift+Enter`で改行を挿入する。既存の`compositionstart`、`compositionend`（タイマーガード）、`event.isComposing`、`keyCode 229`の保護を維持する。

## 検証

`tests/test_unified_ui_system.py`で次を確認する。

- 共通CSS／JSがUniverseで読み込まれる
- ライトテーマとreduced motionがある
- コンテキストバーとCSS 3Dがある
- タブとパネルへARIA roleを設定する
- IME Enter保護を維持する
- Web UIバージョンとAsset Versionが一致する

実ブラウザではPC幅、390x844、実iPhone PWA、ソフトウェアキーボード表示、ライト／ダーク、Focus Orbit負荷を別途確認する。

Issue #296では隔離したサンプルデータのブラウザで、320px / 390px / 1440px幅、空・複数タスク、Chat、Settingsのテーマ切替、Universe表示、小型Desktop HTMLを確認。実iPhoneキーボード、配布Electron、実LLM・音声・外部サービスは未確認。

## Desktopの入口（Issue #299）

小型会話は素早い呼び出し、アプリ内ワークスペースはTasks/Universe等の継続作業に使う。作業画面は既存のテーマ・共通UIを再利用し、同梱toolbarで小型会話とDesktop設定へ戻る。接続失敗とrenderer停止は同梱復旧画面で区別する。小型会話の下書き/未確認応答を状態文で示し、待機中断を操作取消しと表現しない。

## Task Detailの対象（Issue #297）

Univでは選択タスク、それ以外ではサーバーのactive / paused Work Sessionの`task_id`に一致するタスクを表示する。作業なし・終了時は選択タスクへ戻さず「作業中のタスクはありません」と表示する。一時停止中は対象を保持する。自由入力の作業や取得一覧に存在しないTaskはセッションの作業名だけを表示し、別Taskの編集・完了ボタンを流用しない。ビュー切替・セッション復元・開始/終了・15秒ポーリングへ追従し、変化のないポーリングでは編集フォームを置き換えない。
