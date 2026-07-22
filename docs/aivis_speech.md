# AivisSpeech読み上げ

PETITはAivisSpeech Engineを使って返答をWAV音声に変換します。AivisSpeechが停止中の場合、対応ブラウザでは従来のブラウザ標準TTSへ自動フォールバックします。

## セットアップ

1. AivisSpeechをインストールし、使用する音声モデルを追加する。
2. AivisSpeech EngineまたはAivisSpeechエディタを起動する。
3. `http://127.0.0.1:10101/docs` が開けることを確認する。
4. PETITの`.env`へ次を設定する。

```env
PETIT_TTS_PROVIDER=aivis
PETIT_TTS_BASE_URL=http://127.0.0.1:10101
PETIT_TTS_STYLE_ID=
PETIT_TTS_SPEED_SCALE=1.0
PETIT_TTS_INTONATION_SCALE=1.0
PETIT_TTS_VOLUME_SCALE=1.0
```

`PETIT_TTS_STYLE_ID`が空の場合は、`GET /speakers`で返る最初のスタイルを使用します。声を固定する場合は、AivisSpeech Engineの`/speakers`レスポンス内にあるスタイルの`id`を設定してください。

## PETIT API

### 状態確認

```http
GET /api/tts/status
```

AivisSpeechへの接続可否、設定値、実際に選択されたスタイルIDを返します。失敗時は`error_code`、`retryable`、`upstream_status`も返すため、Engine停止・タイムアウト・上流HTTPエラーを区別できます。

### 音声生成

```http
POST /api/tts
Content-Type: application/json

{"text":"こんにちは"}
```

成功時は`audio/wav`を返します。Engine停止、モデル未配置、スタイルID不正などの場合はHTTP 503と日本語エラーを返します。チャット処理自体は停止しません。

AivisSpeechが一時的に`429`、`502`、`503`、`504`を返した場合、PETITは短い待機後に1回だけ再試行します。また、複数端末や再読上げで合成要求が重なっても、AivisSpeechへは直列に送信します。

## スマートフォンでの再生

モバイルSafariなどは、ユーザー操作から離れたタイミングで始まる音声再生を制限することがあります。PETITは最初のタップ・タッチ・Enter操作で無音音声とAudioContextを初期化し、その後に生成されたWAVを再生できる状態へします。

スマートフォンからPETITへアクセスしても、AivisSpeechへの接続はスマートフォンから直接行いません。`スマートフォン → PETIT FastAPI → 同じPC上のAivisSpeech Engine`の順です。そのため、`POST /api/tts`が503の場合は、まずPETITを動かしているPCから次を確認します。

```text
http://127.0.0.1:10101/speakers
http://PETITのIP:8000/api/tts/status
```

PETITをDockerやWSLで動かし、AivisSpeechをWindows側で動かす場合、コンテナ／WSL内の`127.0.0.1`はWindowsホストを指しません。`PETIT_TTS_BASE_URL`を`host.docker.internal`またはWindowsホストの到達可能なIPへ変更してください。

## 調整値

- `PETIT_TTS_SPEED_SCALE`: 話速。0.5〜2.0へ制限
- `PETIT_TTS_INTONATION_SCALE`: スタイルの感情表現の強さ。0.0〜2.0へ制限
- `PETIT_TTS_VOLUME_SCALE`: 音量。0.0〜2.0へ制限
- `PETIT_TTS_TIMEOUT`: Engine応答待ち秒数
- `PETIT_TTS_MAX_CHARS`: 1回に読み上げる最大文字数

## フロントの挙動

- 新しいPETIT返答を自動読み上げ
- 各返答のスピーカーボタンで再読上げ
- 新しいユーザー発話または再読上げ開始時に、生成中リクエストと再生中音声を停止
- AivisSpeech失敗時だけブラウザ標準TTSへフォールバック
- 最初のユーザー操作でモバイル音声再生をアンロック
- コードブロックとURLは、そのまま長く読まず画面確認を促す文へ置換

## 未確認

実AivisSpeechモデルを使った声質、初回生成時間、長文の体感、スマートフォンからPETITへ接続した場合の音声再生は実機確認が必要です。
