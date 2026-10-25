# 公式Antigravity SDK Brain — Refs #349

確認日: 2026-10-24 UTC / 2026-10-25 JST。基準main: `4135053`。
専用ブランチ: `feat/renaissance-antigravity-sdk`。v0.33.0開発版・main未反映。

## 採用した方法

ユーザーの最新指示と再更新されたIssueに従い、公式Python SDK `google-antigravity==0.1.22` を
**選択式のメインBrainバックエンド**として追加した。SDK自身がAgent LoopとTool選択を担当する。
既定は `LocalOpenAIAgentConfig` + loopback LM Studio。単なるGemini API Providerの追加ではない。

PR #351は別のGemini API実装で、取り込まず、マージしない。DeepSeek / 直接LM Studio経路は維持する。
SDKはRead専用で、Writeの受入完了を意味しない。Issueは未確認項目を残したままOpenとする。

## 正規経路・契約・費用

| 方法 | 認証・追加費用 | 本件の扱い |
|---|---|---|
| 公式SDK + LM Studio | APIキー不要。既存ローカルモデル推論なので追加クラウドAPI料金なし。PCのメモリ・電力を使用 | 実装・実ランタイム・実ローカルモデルの合成会話を検証 |
| 公式SDK + Gemini | APIキーと別API料金/無料枠・データポリシー。Antigravity月額ログイン枠ではない | 明示cloud許可が必要。現在キーなし・実通信skipped |
| 公式SDK + Cloud / Enterprise | 公式資料に別認証・契約を案内 | 今回は設定・接続していない |
| 公式CLIの本人直接スクリプト / CI | 本人の正規CLIログイン。サービスの契約・quotaに従う | `agy`未導入と本人が確認。実行未確認 |
| 個人契約CLIをPETITからラップ | 現行FAQが第三者アプリ内ラップを非サポートと明示 | 許諾確認済みとは扱わず、実装しない |
| Gemini API単独 | SDKのAgent Runtimeを使わない | #349の成果として代用しない |

公式根拠:

- [SDK overview](https://antigravity.google/docs/sdk/overview/)、[Local models](https://antigravity.google/docs/sdk/local-models/): 公式SDKでプログラムを構築でき、ローカルOpenAI互換サーバーへの接続も案内されている。
- [Tools](https://antigravity.google/docs/sdk/tools/)、[Policies](https://antigravity.google/docs/sdk/policies/)、[Lifecycle](https://antigravity.google/docs/sdk/lifecycle/): Python Tool、内蔵Tool制限、保存・再開。
- [PyPI 0.1.22](https://pypi.org/project/google-antigravity/0.1.22/): Windows amd64 wheelのSHA256とPython APIを確認。SDKが配布するローカルGo runtimeを使用する。
- [FAQ](https://www.antigravity.google/docs/faq)、[追加規約](https://antigravity.google/terms)、[Headless](https://antigravity.google/docs/cli/headless/): CLIスクリプトの技術的な対応と、個人契約でのアプリ組込許可を区別する。

[2026-10-07の公式フォーラム回答](https://discuss.ai.google.dev/t/can-a-local-ai-coordinator-launch-the-official-antigravity-cli-with-subscription-sign-in/186246)にはローカルcoordinatorによるCLI起動を認める説明があるが、現行FAQと食い違う。フォーラム説明だけでFAQを上書きしない。
月額枠でのCLI組込が引き続き必要なら、[公式Supportの導線](https://www.antigravity.google/docs/faq#how-do-i-get-support)から、単一ユーザーのPETIT内部起動の許否、適用契約、FAQとの相違を問い合わせる。問い合わせは送信していない。OAuth/cookieの抽出、非公開API、アカウント切替による回避は行わない。

## 実装と安全境界

- `backend/brain.py`は明示選択された`antigravity_sdk`だけ別バックエンドへ分岐する。同じTurnでnative Brain Loopは起動しない。
- `backend/antigravity_brain.py`が公式SDKを実行。内蔵Toolは`finish`だけ。SDKのshell/file/web/MCP/Skills/Subagent/Triggersは公開しない。
- SDKのPython Tool `petit_read_tool`から、`get_current_time` / `get_tasks` / `get_schedule` / `get_work_status` / `get_project_status` / `find_projects` / `get_reminders`だけを利用できる。
- 毎回、許可リスト・現在のRegistry risk・JSON schema・取消・Provider固定を再検査して既存Readを呼ぶ。Write、未知Tool、未定義引数、壊れたJSON、非有限数は拒否する。Read Toolの名称や引数を自然文のregexで推定しない。
- Thread/Turn/本文/承認/Receiptの正本は既存SQLite。新しいDBやschemaは作らない。SDK会話IDは既存Turn Eventsに紐づける。
- 各Turnは新しい一時SDKセッションへ同じThreadのbounded履歴だけを渡す。SDKの保存履歴を重ねて注入しない。Core再起動後はCore履歴から再構築し、同request再送は保存結果を返す。
- SDKは専用Python Workerで実行する。設定はlocal pipeで渡し、キー・本文をargvや診断へ出さない。親Coreがdeadline、取消、Provider変更を監視し、そのTurn用WorkerとSDK子プロセスだけを終了する。SDK起動途中の取消にも同じ境界を使う。
- `local_only`はloopback SDKだけ許可。クラウド認証へ切り替わったら停止する。自動Fallbackは実装せず、別Providerへ文脈を再送しない。
- Web/Desktop共通の「最新の依頼」で`antigravity_sdk`、実model、auth、推論先、usage/null、latency、session IDを確認できる。失敗時も既存Eventsから診断を復元し、生の例外本文・APIキーは保存しない。
- 画像・旧completion API・WriteはこのSDKバックエンドの対象外。SDK未対応経路でGemini直APIや別ループへ黙って切り替えない。

実装フローの正本は [runtime-flows.md](runtime-flows.md)。Notion同期コード・実DB・本番のProvider選択は変更していない。

## 導入・選択

Python 3.12以上の専用環境で既存PETIT依存に加えて導入する。既存共有環境へ無断でインストールしない。

```powershell
python -m venv .venv
# 既存PETITの開発手順でアプリ依存を導入後:
.\.venv\Scripts\python.exe -m pip install -r requirements-antigravity.txt
.\.venv\Scripts\python.exe -m pip check
```

LM StudioでTool Calling対応モデルを読み込み、loopbackサーバーを起動する。SDKはモデルを自動ダウンロード/自動ロードしない。

```dotenv
PETIT_ANTIGRAVITY_AUTH=local
PETIT_ANTIGRAVITY_BASE_URL=http://127.0.0.1:1234/v1
PETIT_ANTIGRAVITY_MODEL=LM StudioでロードしたモデルID
PETIT_ANTIGRAVITY_TIMEOUT_SECONDS=90
PETIT_ALLOW_ANTIGRAVITY_CLOUD=false
```

base/model省略時は既存Local Chat設定を使う。SDKのlocal接続はlocalhost/127.0.0.1/::1のHTTPだけで、外部hostnameや認証付きURLは拒否する。
Web/DesktopのChatモデルで **Antigravity SDK（Read専用）** を明示選択する。旧Agent欄では選択しない。
APIなら`POST /api/model-routing {"chat":"antigravity_sdk"}`。キーを置くだけで自動切替はしない。

SDK+Geminiを使う場合のみ、別API課金とデータ送信条件を確認し、`PETIT_ANTIGRAVITY_AUTH=gemini`、実model ID、`PETIT_ANTIGRAVITY_API_KEY`（または`GEMINI_API_KEY`）、`PETIT_ALLOW_ANTIGRAVITY_CLOUD=true`を明示設定する。現在この経路の実通信は未実施。

## 再現可能な検証

独立SDK検証はPETITをimportせず、一時workspace/sessionとダミーToolだけを使う。既定は設定構築だけ。`--live`で実推論する。
レポートは上書きしないため、新しい出力名を指定する。

```powershell
.\.venv\Scripts\python.exe scripts/probe_antigravity_sdk.py
.\.venv\Scripts\python.exe scripts/probe_antigravity_sdk.py --live --backend local --model ロード済みID --output sdk-session-new.json
# クラウドは明示選択とキーがある場合のみ。キーがなければskipped。
.\.venv\Scripts\python.exe scripts/probe_antigravity_sdk.py --live --backend gemini --output sdk-cloud-new.json
# 実SDKと実LM Studioを、合成PETIT DBへ接続。Notion・実データは使わない。
.\.venv\Scripts\python.exe scripts/smoke_antigravity_brain.py --model ロード済みID --output sdk-core-new.json
python -m pytest tests/test_antigravity_sdk.py tests/test_antigravity_sdk_probe.py tests/test_renaissance_core.py tests/test_model_route_switcher.py -q
node --test scripts/test-thread-client.cjs
```

ブラウザ検証はPlaywright/Chromeがある環境で`PETIT_TEST_PYTHON`を上の専用Pythonへ設定し、
`scripts/test-antigravity-sdk-ui.cjs`を実行する。8877番ポートと一時DBを使い、本番PETITを操作しない。
Desktop sourceのブラウザadapterを含むが、配布Electronの実機受入とは区別する。

## 実測・残件

- Windows / Python 3.13.3 / SDK 0.1.22 / Qwen3.5-9B、テスト用model ID `petit-agy-probe`で実施。既存モデルを利用し、新規モデルは取得していない。
- [独立SDKの3ターンと保存再開](../reports/antigravity-sdk-session-local-live.json): 実runtime、ダミーTool1回、stream/text一致、同じconversation IDで再開成功。起動2.177秒、各turn約3.020/0.927/2.122秒。推論品質一般の評価ではない。
- [実Coreの初回記録](../reports/antigravity-sdk-core-local-live.json): 通常会話→実Read→次turnの参照、3/3成功。推論先はLM Studio。SDK Agentを単にimportした結果ではない。
- [最終Worker方式の実Core検証](../reports/antigravity-sdk-core-lifecycle-live.json): 3ターン成功、再送一致、Core復旧後の会話継続。Turn約5.618/7.917/6.008秒。実timeoutは0.504秒でfailed、実取消は4秒後の要求に対して全体4.478秒でcancelled、effectsなし。終了後にlocalharness.exeの残留なしを確認。
- [実Chromium](../reports/antigravity-sdk-browser-live.json): 1440/390pxで実SDK+LM StudioのRead Tool、backend診断、履歴の再読込を確認。390pxはDesktop source adapterで、配布Electron本体の実証ではない。
- pytest81件＋5 subtests、Thread client Node5件、Python/JS構文とpip check成功。初期ブラウザテストはUniverseのDOM selectorと初期化待ちの誤りで失敗し、テストを修正して再確認。途中のWorker実通信ではWindows pipeの文字コード不一致（UnicodeEncodeError）を検出し、stdin/stdoutとWorker環境をUTF-8へ固定した。[失敗記録](../reports/antigravity-sdk-core-isolated-live.json)も保持する。
- SDK本体の実インストールサイズ150,487,703 bytes、うち同梱runtime 146,133,504 bytes（Windows amd64、依存パッケージ分は別）。API料金がゼロでも、このランタイムとモデルのRAM/起動コストは必要。
- PyPIにはmacOS arm64/x86_64、Windows amd64/arm64のwheelを確認。macOS実機の動作は未確認。
- クラウドSDKはキー未設定のため[skipped](../reports/antigravity-sdk-cloud-skipped.json)。CLIは未導入。月額枠を使えたとは表示しない。
- Write、実Notion/Calendar、画像、配布Desktop、macOS/iPhone、一般的な日本語/Tool選択精度は未確認。既存Chromaの非推奨警告は残る。

SDKが実際にメインBrainで会話・Read Toolを使えることと、全端末/全機能の完成は区別する。
Issueの未確認項目を消さず、実データ・配布Desktopの受入と、Writeを必要とするかの判断を次に行う。
