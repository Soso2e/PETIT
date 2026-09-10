# PETIT 音声モード（Phase 1–2）

PETITの既存チャットAPIを変えず、ブラウザの音声機能を入出力層として追加する。

## 実装範囲

### Phase 1: 音声応答

- ヘッダーの「音声応答 ON/OFF」で自動読み上げを切り替える
- 設定は `localStorage` に保存する
- PETITの新しい返答、確認操作の結果、バックグラウンド調査結果を読み上げる
- 各アシスタント返答のスピーカーボタンから手動で再生できる
- コードブロックとURLは読み上げず、画面確認を案内する

### Phase 2: 押して話す音声入力

- マイクボタンを押すと日本語の音声認識を開始する
- 認識途中の文章を入力欄に表示する
- 発話終了後、確定した文章を既存の `/api/chat` へ自動送信する
- PETITが話している途中にマイクを押すと読み上げを停止する
- マイク拒否、無音、ネットワーク失敗を画面に表示する

## Mac / Webでの使い方

現行Web画面の `chat-input` と送信ボタンにも共有音声処理を接続します。旧UI専用の要素がなくてもマイクを初期化します。

チャット欄の「ブラウザ認識 / 録音認識」で方式を選び、マイクを押します。
- ブラウザ認識: 日本語の認識結果を表示し、発話終了後に送信します。ブラウザや認識サービスの対応状況に依存します。
- 録音認識: 話し終わったら■を押します（最大60秒で自動停止）。マイクを解放してからPETITサーバーへ送り、文字起こし後にチャットへ送信します。途中の文字表示はありません。
- サーバー録音認識が設定済みで方式をまだ選んでいない場合は、録音認識を初期選択します。選択はブラウザに保存します。
- 入力済みの下書きがあれば、認識結果を末尾に加えて送信します。失敗時は下書きを復元し、自動送信しません。
- 入力欄でmacOSの音声入力を利用して文章を入れ、通常の送信ボタンを押す方法も使えます。

### 録音認識の設定

PETITを動かすサーバーの `.env` で次を設定し、PETITを再起動します。

```dotenv
PETIT_STT_URL=http://127.0.0.1:9000/v1/audio/transcriptions
PETIT_STT_MODEL=whisper-1
PETIT_STT_API_KEY=
```

URLは例です。実際に稼働するWhisper互換サービスの完全なエンドポイントとモデル名を指定してください。
LM Studioのチャット用URLをそのまま指定しても文字起こしはできません。STTサービスの導入・モデル起動は別途必要です。
HTTPSまたはlocalhost HTTPのみを許可し、リダイレクトは追いません。
認証キーはサーバー側だけに置きます。`GET /api/stt/status` の `configured` は設定の有効性であり、サービスの稼働確認ではありません。

録音はWebM/Opus、MP4、Ogg/Opusからブラウザ対応形式を選びます。STT側もその形式を受け付ける必要があります。
録音の上限はブラウザで60秒、APIで8MiB、STT待機は60秒です。音声はPETITでファイル保存・ログ出力せず、設定したサービスへ転送します。
外部サービスの場合はそのサービスへ音声が渡ります。ブラウザ認識の処理先はブラウザ側の仕様に従います。

### 使えない場合

1. HTTPのLAN IPで開いている場合はHTTPSへ変更します。同じMac内ならlocalhostを使えます。
2. Macの「システム設定 → サウンド → 入力」で入力メーターが動くか確認します。
3. サイトのマイク権限と「システム設定 → プライバシーとセキュリティ → マイク」のブラウザ権限を確認します。
4. ブラウザ認識でネットワークエラーが出る場合は録音認識へ切り替えます。これはマイク故障とは別の認識サービス接続エラーです。
5. 録音認識が未設定・接続不可の場合はSTTのURL、モデル、起動状態を確認します。

Mac自体を非対応とは判定しません。ブラウザ音声認識には対応差があり、録音取得にはsecure contextが必要です。
参考: [MDN SpeechRecognition](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition)、[MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)。
Desktopは従来のAudioWorklet / Desktop STT設定を利用します。今回のWeb設定とは別です。

## 検証

- `node --test tests/frontend/voice-input.test.cjs`
- `.venv/bin/python -m pytest tests/test_web_stt.py tests/test_voice_router.py tests/test_frontend_router.py tests/test_voice_task_interaction.py -q`
- 実機確認: Safari / Chromeで権限許可・拒否、録音停止、文字起こし、チャット送信、下書き復元を確認します。実マイク・実STTは自動テストとは別の受け入れ確認です。
