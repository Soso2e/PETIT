# AivisSpeech読み上げ

PETITはAivisSpeech Engineを使って返答をWAV音声に変換します。AivisSpeechが停止中・未設定・診断失敗の場合でも、**チャット自体は利用できます**。対応ブラウザではブラウザ標準TTSへフォールバックできるため、有料TTS APIは前提ではありません。

## まず選ぶ: 無料TTSの2つの使い方

| 方式 | 向いている状態 | 準備 |
|---|---|---|
| ブラウザ標準TTS | まず無料ですぐ読み上げたい / AivisSpeech未準備 | ブラウザ側だけで利用。AivisSpeech Engine不要 |
| AivisSpeech | ローカルで声質を選びたい / WAV生成を使いたい | WindowsへAivisSpeechと音声モデルを導入し、Engineを起動 |

AivisSpeechが利用できない場合、PETITはテキスト表示を止めず、対応ブラウザでは標準TTSへ切り替えます。AivisSpeechの導入や復旧が終わるまで、チャットと標準TTSだけで運用して構いません。

## Windowsでの初期セットアップ

新しい環境では、次の順番で確認してください。途中で失敗したら、その段階より先へ進まず「診断結果のstage別チェック」へ移ると原因を絞れます。

1. **AivisSpeechをインストールする**
   - AivisSpeech本体をWindowsへインストールします。
   - PETITとは別プロセスで動きます。

2. **音声モデルを1つ以上追加する**
   - AivisSpeech側で使用する音声モデルを導入します。
   - モデルやスタイルが1つもない状態ではPETITが話者を解決できません。

3. **AivisSpeech EngineまたはAivisSpeechエディタを起動する**
   - 既定のEngine URLは `http://127.0.0.1:10101` です。
   - PETITより先に起動しておくと切り分けが簡単です。

4. **EngineのAPIドキュメントを開く**

   ブラウザで次を開きます。

   ```text
   http://127.0.0.1:10101/docs
   ```

   開かなければ、PETIT側を調べる前にAivisSpeech Engineの起動状態・ポートを確認してください。

5. **話者一覧を確認する**

   ```text
   http://127.0.0.1:10101/speakers
   ```

   JSONが返り、`styles`内に少なくとも1つ`id`があることを確認します。

6. **PETITの`.env`を設定する**

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

   `PETIT_TTS_STYLE_ID`が空の場合は、`GET /speakers`で返る最初のスタイルを使用します。声を固定する場合は、`/speakers`レスポンス内のスタイル`id`を設定してください。

7. **PETITを経由しない診断CLIを実行する**

   プロジェクトルートで実行します。

   ```bash
   python scripts/diagnose_aivis_speech.py
   ```

   既定では固定文 `こんにちは、音声テストです。` を合成し、有効なWAVだけを次へ保存します。

   ```text
   storage/diagnostics/aivis_speech_test.wav
   ```

8. **`stage: complete`を確認してWAVを再生する**

   成功時のJSONには次のような情報が含まれます。

   ```json
   {
     "ok": true,
     "stage": "complete",
     "resolved_style_id": 123,
     "audio_bytes": 45678,
     "wav": {
       "channels": 1,
       "sample_rate_hz": 24000,
       "frame_count": 12345,
       "duration_seconds": 0.514
     },
     "output_path": ".../storage/diagnostics/aivis_speech_test.wav"
   }
   ```

   `stage: complete`なら、RIFF/WAVEヘッダーと音声情報の検証を通ったWAVが保存されています。まずWindows上でそのWAVを手動再生してください。ここまで成功すれば、Engine・話者・音声クエリ・合成・WAV受信の最小経路は成立しています。

WAVを保存せず疎通だけ確認する場合は次を使います。

```bash
python scripts/diagnose_aivis_speech.py --no-write
```

任意の短い文や出力先も指定できます。

```bash
python scripts/diagnose_aivis_speech.py --text "PETITの音声テストです。" --output storage/diagnostics/test.wav
```

## 診断結果のstage別チェック

診断CLIはJSONの`stage`で止まった場所を区別します。

| stage | 意味 | 次に確認する場所 |
|---|---|---|
| `not_configured` | AivisSpeech設定が無効 | `.env`の`PETIT_TTS_PROVIDER`と`PETIT_TTS_BASE_URL` |
| `engine_unreachable` | Engineへ接続できない | Engine起動、`/docs`、ホスト名、ポート、Docker/WSL境界 |
| `speaker_not_found` | 話者・スタイルを解決できない | `/speakers`、音声モデル、`PETIT_TTS_STYLE_ID` |
| `audio_query_failed` | `/audio_query`に失敗 | Engineログ、上流HTTPステータス、話者ID |
| `synthesis_failed` | `/synthesis`に失敗 | Engineログ、再試行可否、モデル状態 |
| `invalid_audio_response` | 返答が有効なWAVではない | Content-Type、応答サイズ、RIFF/WAVE、Engine出力 |
| `request_timeout` | Engine応答がタイムアウト | Engine負荷、`PETIT_TTS_TIMEOUT`、接続経路 |
| `engine_health_failed` | 疎通確認が未分類の理由で失敗 | JSONの`error_code` / `upstream_status` / `error` |
| `complete` | WAV検証と任意保存まで成功 | 保存WAVを手動再生し、その後PETIT画面を確認 |

診断JSONは、会話本文やAPIキーを残さず、接続先・話者ID・失敗分類・安全な上流情報・WAVメタデータだけを出します。

## Docker / WSLでPETITを動かす場合

AivisSpeechをWindows側、PETITをDockerコンテナまたはWSL内で動かす場合、PETITから見た`127.0.0.1`はWindowsホストではありません。

### Docker

まず次を候補にします。

```env
PETIT_TTS_BASE_URL=http://host.docker.internal:10101
```

`host.docker.internal`が使えない構成では、Windowsホストの到達可能なLAN IPを指定します。

### WSL

WSLからWindows側Engineへ届くWindowsホストIPを`PETIT_TTS_BASE_URL`へ設定します。`127.0.0.1:10101`で失敗する場合は、Windows側の到達可能なIPとファイアウォールを確認してください。

重要なのは、**スマートフォンのIPではなくPETITプロセスからAivisSpeech Engineへ到達できるURL**を設定することです。

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

成功時は`audio/wav`を返します。Engine停止、モデル未配置、スタイルID不正などの場合はHTTP 503と日本語エラーを返します。**TTSが失敗してもチャット処理自体は停止しません。**

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

スマートフォンからPETITへアクセスしても、AivisSpeechへの接続はスマートフォンから直接行いません。

```text
スマートフォン
  ↓
PETIT FastAPI
  ↓
AivisSpeech Engine
```

そのため、スマートフォン側で音が出ない場合も、まずPETITを動かしている環境から次を確認します。

```text
http://127.0.0.1:10101/speakers
http://PETITのIP:8000/api/tts/status
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
