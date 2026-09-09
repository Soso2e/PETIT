# PETIT Desktop — 段階導入設計

Issue: [#253](https://github.com/Soso2e/PETIT/issues/253)。調査日: 2026-09-07。

## 今回の判断

**Electronの薄い常駐シェル＋既存FastAPI/Webを採用する。** iPhoneは既存PWAを継続する。
初回は既存サーバーへ接続するクライアント方式。Python、SQLite、Chroma、LM Studio、AivisSpeechをアプリへ複製・同梱しない。

| 方式 | 軽量性 | 保守・音声・共通UX | 判断 |
| --- | --- | --- | --- |
| Tauri 2 | OS WebView利用で小さい | RustとJS、WKWebView/WebView2差の検証が必要。既存Web Speech認識の互換性は保証できない | サイズ最優先になった段階で再評価 |
| Electron | Chromium/Node同梱で大きい | 既存JSを使用。両OSの描画・AudioWorkletとNode音声SDKを揃えやすい | 今回採用 |
| PWAのみ | 追加ランタイムなし | OSトレイ、グローバルショートカット、隠れた状態のマイク制御が不足 | iPhoneを維持 |

[Tauri App Size](https://v2.tauri.app/concept/size/)、[Electron Security](https://www.electronjs.org/docs/latest/tutorial/security)を参照。判断はPETITの既存構成との比較による。
軽量性を無条件に達成したとは扱わない。最初のmacOS arm64パッケージは約302MB。常駐メモリ・CPU・電池消費は実機測定が必要。

## 現在の共通基盤

- `backend/app.py` / `backend/kernel/modules.py`: FastAPI組み立て。`backend/frontend_api.py`: `/`、`/static`、Service Worker配信。
- `frontend/index.html` → `universe.html`: 現行Web/PWA。`legacy.html`と`app.js`には独立利用できる会話UIがある。
- `frontend/app.js`: `/api/chat`、request/session ID、会話復元、確認API、ジョブ表示。Desktopも同じファイルを読む。
- `frontend/session.js`: セッション分割と会話復元補助。Desktopも共有する。ブラウザとDesktopのlocalStorageは別なので、同一セッションIDには自動統合しない。
- `frontend/voice.js`: Web Speech入力、確認発話、`/api/tts`のAivisSpeechと端末TTS fallback。Desktopは入力クラスだけ差し替える。
- `backend/shortcut_voice.py`: iOS Vocal Shortcut入口。変更しない。

小型画面は `/static/desktop/index.html`。CSS、ウィンドウ操作、録音adapterのみ追加する。通常Web/PWAはDesktop JSをロードしない。
Service WorkerにDesktop資産をprecacheせず、DesktopもService Workerを登録しない。共有voice.jsの変更はDesktop adapter存在時のみ有効。

## ウェイクワード

| 選択肢 | Windows / macOS | 制約・費用・精度 | 採用範囲 |
| --- | --- | --- | --- |
| Porcupine | ローカルNode SDK、日本語、OS/CPU別モデル | AccessKeyと利用条件の確認が必要。日本語`.pv`とカスタム`.ppn`が必要 | 任意・初期検証版として実装 |
| openWakeWord | Python等で別プロセス化可能 | 公式は英語対応。日本語「プティ」を即時保証できず、学習・誤検知評価が必要 | [v0.1学習環境](openwakeword.md)を追加。Desktop統合は後続 |
| Voskで全文認識→文字列一致 | 日本語軽量モデルあり | 常時STTは専用検出器より負荷が増える。固有名の誤認識も評価が必要 | 初回不採用 |
| Web Speech常時再起動 | WebView依存 | 通信・可用性・バックグラウンド・OS差の影響が大きい | 不採用 |
| トレイ / グローバルキー | 両OS | マイク不要。キー競合時はトレイへ案内 | 常に使える基本入口 |

[Porcupine概要](https://picovoice.ai/docs/porcupine/)と[Node SDK](https://picovoice.ai/docs/quick-start/porcupine-nodejs/)は日本語・デスクトップ対応、AccessKey、プラットフォーム別モデルを説明している。
[openWakeWordの言語対応](https://github.com/dscripka/openWakeWord#language-support)、[Voskモデル一覧](https://alphacephei.com/vosk/models)も比較した。

「プティ」は短く、環境音や会話との区別が難しい可能性がある。初期推奨は日本語モデルの「へいプティ」。実際にConsoleで生成できるフレーズと各OSのモデルを用い、短い「プティ」は誤検知・見逃しを測ってから採用する。名前だけの文字列一致をウェイク検出成功とは扱わない。

`wake-worker.cjs`はElectron utility processでPorcupine＋PvRecorderを実行する。待機PCMは検出器だけに渡し、録音ファイルやサーバーへ送らない。検出時はマイクプロセスを停止し、固定の`wake`イベントだけをMainへ返す。検出語でツールは実行しない。

Mainが小型画面を表示 → AudioWorklet録音 → WAV → 明示設定したSTT URL → 確定文字列 → 共有voice.js → 共有app.js → 既存Chat/確認API、の順に処理する。応答音声は既存TTS。

初回は一発話単位。応答後は再びマイクを押すか、小型画面を閉じて再度呼びかける。UI表示中はウェイクを停止するため、自分の返答による再検出を避けられる。TTS後に自動で次の録音へ進む完全ハンズフリー会話、割り込み発話、ウェイクと用件を一息で話す際の先頭音声引継ぎは後続。

## 常駐・OS権限

- トレイ/メニューバー常駐。閉じるボタンとEscapeは隠す。終了はトレイの「PETITを終了」。単一起動で重複ウィンドウを防ぐ。
- `Ctrl / ⌘ + Shift + Space`で表示＋音声入力（STT未設定時は文字入力）。競合時は設定とトレイに表示する。任意キー設定は後続。
- 初回起動・ウェイク待機・ログイン起動は設定で制御する。ログイン起動は既定OFF、インストール版のみ。BackendやLM Studioの自動起動は含まない。
- ロック/スリープで録音・STT・待機を停止。両方解除されたとき、設定済みで画面が非表示の場合に待機を再開する。スリープ解除そのもの、ログアウト中、アプリ終了中の呼び出しは対象外。
- Windows: 設定 → プライバシーとセキュリティ → マイク → マイクアクセスとデスクトップアプリのアクセスを許可。拒否時は文字入力を使用。
- macOS: `NSMicrophoneUsageDescription`とaudio-input entitlementを同梱。システム設定 → プライバシーとセキュリティ → マイクでPETITを許可。署名・公証済みアプリで改めて確認する。
- 画面録画・カメラ・フルディスクアクセスは要求しない。通常キーの登録にアクセシビリティ権限を一律要求しない。OSで登録できない場合はトレイで代替する。
- [globalShortcut](https://www.electronjs.org/docs/latest/api/global-shortcut)、[powerMonitor](https://www.electronjs.org/docs/latest/api/power-monitor)、[macOSメディア権限](https://www.electronjs.org/docs/latest/api/system-preferences#systempreferencesaskformediaaccessmediatype-macos)に準拠する。

## 配布・更新

初回は **GitHub ReleasesでDMG / NSISを配布し、Desktopから更新通知**。ストア運用や独自更新サーバーを増やさない。既存リポジトリはpublic。通知確認はGitHubの公開APIだけを使用し、PATを配布しない。

- PRではDesktopテストだけを実行し、インストーラーは生成しない。
- Actionsの手動実行（`workflow_dispatch`）ではmacOS arm64 / Windows x64をビルドし、未署名の開発用Artifactとして14日保存する。
- `main`の履歴上にある`v*`タグをpushすると、`desktop/package.json`とのバージョン一致を検証した上で両OSをビルドし、DMG / EXEを同名タグのGitHub Releaseへ自動添付する。workflow自身はタグを作成しない。
- 安定版SemVer、同じOS/CPU用の`PETIT-<version>-mac-arm64.dmg`、`mac-x64.dmg`、`win-x64.exe`があるReleaseだけ候補にする。WebのみのRelease、draft/prerelease、旧版は除外。
- 起動10秒後と24時間ごと（設定でOFF可能）、またはトレイ/設定から確認。ネットワーク失敗はアプリ起動を妨げない。自動確認は同一バージョンをプロセス内で重複通知しない。
- 通知から公式Releaseページを開き、利用者がインストーラーを実行する。初回公開前や対応assetがないときは「利用可能なDesktop更新なし」となる。
- Desktopのバージョンとサーバーのバージョンは別に進められる。今回の最低サーバーは小型画面の追加を含むv0.20.0。アプリ更新はPythonやユーザーデータを置換しない。サーバー更新は従来のGit等の手順を維持。
- 署名・公証・鍵管理・実更新テストが揃ったらelectron-updaterのGitHub providerを評価し、署名検証付きのダウンロード＋再起動時適用へ進む。自動更新を実装済みとは扱わない。

[Electron更新ガイド](https://www.electronjs.org/docs/latest/tutorial/updates)、[electron-builder配布](https://www.electron.build/publish/)、[Tauri updaterの署名要件](https://v2.tauri.app/plugin/updater/#signing-updates)を比較。今回は通知で要件を満たし、署名準備前の自己更新を避ける。

## セキュリティ・設定保存

sandbox / contextIsolationを有効にし、Node integrationは無効。外部遷移・新規ウィンドウ・webviewを禁止する。Desktop IPCは指定サーバーの小型画面、Settings IPCは同梱設定画面のメインフレームに限定する。
URLは認証情報・queryなしのHTTPS、または厳密なloopback HTTPだけ。STTは利用者が設定した固定URLのみで、リダイレクトは禁止。応答音声とチャットの相対URLはPETITサーバーと同一originを維持する。
**接続するPETITサーバー自体は信頼する必要がある。** シェルは汎用ブラウザとして利用しない。

設定はElectron userDataの`desktop.json`。AccessKeyはsafeStorageで暗号化し、Rendererへ復号値を返さない。OS/端末間で暗号文をコピーしない。STT用Bearer keyは任意の`PETIT_DESKTOP_STT_KEY`、Porcupine keyの環境変数代替は`PETIT_PORCUPINE_ACCESS_KEY`。鍵・録音・認識本文をログに書かない。

録音はmono PCM16 WAV、無音8秒・発話後無音1.2秒・最大30秒で終了。サーバー送信前に形式/サイズを再検証し、STT通信は最大60秒。同時送信は1件。取消・画面非表示後の遅延結果は破棄。現状のRMS判定は簡易実装であり、騒音環境のVAD評価は後続。

## 開発・導入

```bash
# 1. 従来のPETIT / LM Studioを起動する（ルートのREADMEを参照）
# 2. Desktop開発版を起動する。Node.js 24 LTS推奨
cd desktop
npm ci
npm start
```

初回設定でPETIT URLを入力して保存する。別PCならTailscaleのHTTPS URLを使用する。サーバー停止や旧サーバーで小型画面がない場合は設定へ戻り、接続失敗を表示する。

音声入力には別途Whisper互換STTを用意する。例は[whisper.cpp server](https://github.com/ggml-org/whisper.cpp/tree/master/examples/server)。公式手順でビルド・日本語対応モデルを用意した上で:

```bash
whisper-server -m models/ggml-base.bin --host 127.0.0.1 --port 8080
```

Desktop設定のSTT URLは`http://127.0.0.1:8080/inference`。`file`、`language=ja`、`response_format=json`、`model`をmultipartで送り、`{"text":"..."}`を受け取るサーバーに対応する。LM StudioのチャットURLをSTTとして流用しない。
音声応答は小型画面の「音声応答」をONにする。AivisSpeechは既存の[導入手順](aivis_speech.md)を使用する。

ウェイク検証はPicovoice ConsoleでAccessKey、日本語`.pv`、対象OS/CPU用の`.ppn`を用意し設定へ保存。「マイクで呼びかけを待つ」をON → 小型画面を閉じる → トレイの待機ONを確認 → 呼びかけ → 小型画面が表示されてから用件を話す。

```bash
# Desktopディレクトリで実行
npm test             # OS/マイクなしの境界・録音・取消テスト
npm run test:smoke   # 実Electron + 仮サーバー + 生成音声。実マイクは使用しない
npm run pack         # このOS用の展開済みアプリ
npm run build        # このOS用のインストーラー。ローカル実行だけではReleaseへ公開しない
```

macOSはDMG、WindowsはNSIS。PRではNodeの関連テストのみ。OS別パッケージを試したい場合はActionsを手動実行し、開発用Artifactを取得する。現在の自動ビルド対象はmacOS arm64 / Windows x64。
公開する場合だけ、`desktop/package.json`のversionと一致するSemVerタグ（例: `v0.20.0`）をmain上のコミットへ付けてpushする。タグpush後は両OSのインストーラーをビルドし、GitHub Releaseを自動作成して添付する。
macOS Developer ID署名＋公証、Windowsコード署名が未整備の間は、原則として`workflow_dispatch`のArtifactで実機検証し、公開用タグは切らない。署名・インストール・上書き更新を確認後にRelease運用へ移行する。

## 受け入れ確認と後続

自動テスト結果と今回の手動確認はPRに記録する。次はWindows実機、macOSの署名済みアプリで、以下を確認する。

1. 初回設定、サーバー停止、再接続、複数起動、マルチモニター、終了/ログイン起動。
2. マイク許可/拒否/後から解除、USB/Bluetooth切替、他アプリ使用中。
3. 「へいプティ」「プティ」の成功率、誤検出回数、検出→UI→録音の時間。モデルなし・不正キーでも文字会話を維持。
4. ロック/スリープが重なっても停止、解除後の待機復帰、CPU/メモリ/電池消費。
5. 実STT→実LLM→AivisSpeech/端末TTS、書き込み前の明示確認、途中取消。
6. iPhoneの既存PWA・音声・Service Worker更新を回帰確認。
7. 署名済みReleaseからのインストール、旧版への更新通知、会話データを維持する上書き更新。

後続: 完全な連続音声会話、自由なショートカット設定、サーバー自動起動/同梱、署名済み自動更新。今回のPRはこれらを完了扱いしない。
