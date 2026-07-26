# AivisSpeech読み上げ

PETITはAivisSpeech Engineを使って返答をWAV音声に変換します。AivisSpeechが停止中の場合、対応ブラウザではブラウザ標準TTSへ自動フォールバックします。

## 無料運用の方針

PETITの読み上げに有料APIは必須ではありません。

- **高速・確実さ優先**: ブラウザ標準TTS
- **日本語の声質優先**: ローカルAivisSpeech

AivisSpeechをまだ導入していない、Engineが停止している、モデル設定が失敗している場合でも、PETITのテキスト会話は継続します。音声応答を有効にしている対応ブラウザでは、標準TTSへ切り替わります。

## 初期セットアップ

### 1. AivisSpeechをインストールする

AivisSpeech公式配布ページから、PETITを動かすPCへAivisSpeechをインストールします。

Windowsでは、インストール後にスタートメニューからAivisSpeechを起動できることを確認します。PETITとAivisSpeechは同じPCで動かすのが最も簡単です。

### 2. 音声モデルを追加する

AivisSpeechを起動し、使用する音声モデルを追加します。モデルが1つも入っていないと、Engineへ接続できても話者を取得できず、音声合成できません。

追加後、AivisSpeech上で短い文章を入力し、アプリ単体で音声を生成できることを先に確認してください。

### 3. AivisSpeech Engineを起動する

AivisSpeech EngineまたはAivisSpeechエディタを起動します。既定の接続先は次です。

```text
http://127.0.0.1:10101
```

ブラウザでAPIドキュメントを開きます。

```text
http://127.0.0.1:10101/docs
```

開けない場合は、PETITではなくAivisSpeech側の起動・ポート・ファイアウォールを確認します。

### 4. 話者一覧を確認する

PowerShellで実行します。

```powershell
Invoke-RestMethod http://127.0.0.1:10101/speakers |
    ConvertTo-Json -Depth 20
```

話者とスタイルの一覧が返れば、PETITからEngineへ到達できます。声を固定する場合は、使いたいスタイルの`id`を控えます。

### 5. `.env`を設定する

プロジェクトルートの`.env`へ設定します。

```env
PETIT_TTS_PROVIDER=aivis
PETIT_TTS_BASE_URL=http://127.0.0.1:10101
PETIT_TTS_STYLE_ID=
PETIT_TTS_TIMEOUT=30
PETIT_TTS_MAX_CHARS=1000
PETIT_TTS_SPEED_SCALE=1.0
PETIT_TTS_INTONATION_SCALE=1.0
PETIT_TTS_VOLUME_SCALE=1.0
```

`PETIT_TTS_STYLE_ID`が空の場合は、`GET /speakers`で返る最初のスタイルを使用します。声を固定する場合は、先ほど確認したスタイルIDを設定します。

`.env`を変更したらPETITを再起動します。OS環境変数に同名の設定がある場合は、`.env`よりOS環境変数が優先されます。

### 6. 診断CLIを実行する

PETITの会話画面やブラウザ再生から切り離し、Engine疎通、話者取得、固定短文合成、WAV検証を順番に確認します。

```powershell
python scripts/diagnose_aivis_speech.py
```

成功すると次のように表示されます。

```json
{
  "ok": true,
  "stage": "complete"
}
```

既定では`こんにちは、音声テストです。`を合成し、有効なWAVだけを次へ保存します。

```text
storage/diagnostics/aivis_speech_test.wav
```

保存せず疎通だけ確認する場合は次を使います。

```powershell
python scripts/diagnose_aivis_speech.py --no-write
```

### 7. 保存WAVを再生する

Windows PowerShellで実行します。

```powershell
Invoke-Item .\storage\diagnostics\aivis_speech_test.wav
```

日本語音声が再生できれば、次の経路は成功しています。

```text
PETITのPython処理
→ AivisSpeech Engine
→ 音声クエリ
→ WAV合成
→ ファイル保存
```

その後、PETITのブラウザ画面で音声応答を有効にして確認します。

## 診断結果別の確認

結果はJSONで出力され、`stage`で失敗箇所を区別します。

### `not_configured`

`.env`の次を確認します。

```env
PETIT_TTS_PROVIDER=aivis
```

### `engine_unreachable`

Engineが起動していないか、接続先が違います。

```powershell
Invoke-RestMethod http://127.0.0.1:10101/speakers
```

これも失敗する場合は、AivisSpeechの起動、ポート、Windowsファイアウォールを確認します。

### `speaker_not_found`

音声モデルが追加されていないか、`PETIT_TTS_STYLE_ID`が実在しません。一度空欄に戻します。

```env
PETIT_TTS_STYLE_ID=
```

### `audio_query_failed`

文章から音声クエリを作成する段階で失敗しています。AivisSpeechアプリ単体で同じモデルが発話できるか確認します。

### `synthesis_failed`

音声クエリ作成後のWAV合成で失敗しています。診断JSONの`upstream_status`とAivisSpeech側ログを確認します。

### `invalid_audio_response`

HTTP応答は返っていますが、有効なWAVではありません。接続先が別サービスやエラーページになっていないか確認します。

### `request_timeout`

合成処理が設定時間内に完了していません。一時的な確認として次へ増やせます。

```env
PETIT_TTS_TIMEOUT=60
```

ただし日常会話では長く待たせず、ブラウザ標準TTSへ切り替える設計を優先します。

### `complete`

WAV検証と保存まで成功です。保存ファイルを再生し、その後PETIT画面の読み上げを確認します。

## PETIT API

### 状態確認

```http
GET /api/tts/status
```

AivisSpeechへの接続可否、設定値、実際に選択されたスタイルIDを返します。失敗時は`error_code`、`retryable`、`upstream_status`も返すため、Engine停止・タイムアウト・上流HTTPエラーを区別できます。

PowerShellでは次を使えます。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/tts/status |
    ConvertTo-Json -Depth 10
```

### 音声生成

```http
POST /api/tts
Content-Type: application/json

{"text":"こんにちは"}
```

成功時は`audio/wav`を返します。Engine停止、モデル未配置、スタイルID不正などの場合はHTTP 503と日本語エラーを返します。チャット処理自体は停止しません。

AivisSpeechが一時的に`429`、`502`、`503`、`504`を返した場合、PETITは短い待機後に1回だけ再試行します。また、複数端末や再読上げで合成要求が重なっても、AivisSpeechへは直列に送信します。

## 連続失敗時の回路遮断

接続失敗、タイムアウト、一時的な上流HTTPエラーなど、再試行可能な失敗が2回連続した場合、PETITは60秒間AivisSpeechへの新しい合成要求を上流へ送りません。その間は`aivis_circuit_open`として即時失敗し、対応ブラウザではブラウザ標準TTSへすぐフォールバックできます。

`GET /api/tts/status`では次を確認できます。

- `circuit_open`: 回路遮断中か
- `consecutive_failures`: 連続失敗回数
- `retry_after_seconds`: 再試行までの残り秒数
- `last_error_code`: 最後の失敗分類
- `last_upstream_status`: 最後の上流HTTPステータス

60秒経過後は次の合成要求を許可します。また、状態確認でEngine疎通に成功するか、音声合成に成功すると、連続失敗回数と回路遮断状態を即時リセットします。話者レスポンス不正など再試行不能なエラーは回路遮断の失敗回数へ含めません。状態はPETITプロセス内だけで保持し、再起動後へは引き継ぎません。

## スマートフォンでの再生

モバイルSafariなどは、ユーザー操作から離れたタイミングで始まる音声再生を制限することがあります。PETITは最初のタップ・タッチ・Enter操作で無音音声とAudioContextを初期化し、その後に生成されたWAVを再生できる状態へします。

スマートフォンからPETITへアクセスしても、AivisSpeechへの接続はスマートフォンから直接行いません。`スマートフォン → PETIT FastAPI → 同じPC上のAivisSpeech Engine`の順です。そのため、`POST /api/tts`が503の場合は、まずPETITを動かしているPCから次を確認します。

```text
http://127.0.0.1:10101/speakers
http://PETITのIP:8000/api/tts/status
```

PETITをDockerやWSLで動かし、AivisSpeechをWindows側で動かす場合、コンテナ／WSL内の`127.0.0.1`はWindowsホストを指しません。`PETIT_TTS_BASE_URL`を`host.docker.internal`またはWindowsホストの到達可能なIPへ変更してください。

例:

```env
PETIT_TTS_BASE_URL=http://host.docker.internal:10101
```

## 調整値

- `PETIT_TTS_SPEED_SCALE`: 話速。0.5〜2.0へ制限
- `PETIT_TTS_INTONATION_SCALE`: スタイルの感情表現の強さ。0.0〜2.0へ制限
- `PETIT_TTS_VOLUME_SCALE`: 音量。0.0〜2.0へ制限
- `PETIT_TTS_TIMEOUT`: Engine応答待ち秒数
- `PETIT_TTS_MAX_CHARS`: 1回に読み上げる最大文字数

## フロントの挙動

- 新しいPETIT返答を画面へ表示した後、読み上げを非同期で開始する
- 読み上げ文を句点・疑問符・改行などで分け、約48文字を目安、最大72文字のチャンクへまとめる
- 先頭チャンクを先に生成し、再生中に次チャンクを先読みする
- 各チャンクの準備が5秒を超えた場合はAivisSpeech処理を中止し、残りだけブラウザ標準TTSへフォールバックする
- 音声状態は`音声を準備中…`、`PETITが話しています…`などの短い表示にする
- 各返答のスピーカーボタンで再読上げできる
- 新しいユーザー発話、音声入力、再読上げ開始時に、生成待ちチャンクと再生中音声を停止する
- 最初のユーザー操作でモバイル音声再生をアンロックする
- コードブロックとURLは、そのまま長く読まず画面確認を促す文へ置換する

チャンク長と5秒のタイムアウトは、まず体感確認するためのフロント初期値です。実AivisSpeechと実機で計測後、必要なら環境設定へ移します。

## 未確認

実AivisSpeechモデルを使った最小診断の成功、回路遮断からの復旧、先頭再生までの時間、チャンク間の間、長文の体感、PCブラウザとスマートフォンでの割り込み・フォールバックは実機確認が必要です。
