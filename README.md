# PETIT — Personal Executive for Tasks, Intelligence & Tools

会話から意図を読み取り、生活・タスク・予定・やったことの記録・記憶・開発を横断して支える、**自分専用のAI秘書**。
判断と実際の処理は CLI エージェント（Antigravity CLI ＞ Codex CLI ＞ Claude Code CLI（導入予定）、受け皿として DeepSeek）に任せ、
PETIT Core（FastAPI + SQLite）が会話・記憶・権限・承認・実行記録の土台を担います。Web / PWA と Desktop（Electron）から使え、Discord Bot は今後追加します。

| 知りたいこと | 文書 |
| --- | --- |
| 何を目指しているか | [Concept.md](Concept.md) |
| いまの構成と、目標との差 | [docs/architecture.md](docs/architecture.md) |
| 会話処理・Tool実行のフロー | [docs/runtime-flows.md](docs/runtime-flows.md) |
| 文書の一覧 | [docs/README.md](docs/README.md) |
| 現在地・未確認・変更履歴 | [PROGRESS.md](PROGRESS.md) |
| 開発ルール | [AGENTS.md](AGENTS.md) |

セットアップ手順は下の「[セットアップ](#セットアップ)」を参照してください。以下には、バージョンごとの変更メモ（新しい順）が続きます。

---

## バージョンごとの変更メモ

v0.36.0開発版（#368）は、Codex専用Workspace・成功したThreadの継続・必要なToolだけの詳細取得を追加します。SDKは廃止し、旧設定は明示再選択が必要です。実モデルでの会話速度改善は未確認です。[設計・測定・残課題](docs/brain/persistent-agent-workspace.md)。

## PETIT UI v0.41.0 — Chat / Univ / Develop / Dashboard

PETITはChatを初期画面にする4領域UIへ整理しました。UnivのThree.js惑星タスク表示とDevelopの既存CLI Coding Job機能は維持。Dashboardには、既存SQLite作業セッションから直近90日の活動カレンダー、直近7日/30日合計、活動日数を表示します。過去の日付を選ぶと当日のタスク・セッション・振り返りを確認できます。スマホでは下部4タブ、Electronのメイン画面も共通Web画面で同じ構成になります。DevelopのProject Thread直接連携、PCアプリ自動時間計測、実機配布確認は後続です。設計・受入条件: [Chat-first UI / Dashboard](docs/ui/ui-chat-first-dashboard.md)。


> #368: Antigravity SDKは廃止。旧SDKの説明・検証値は履歴です。現在の移行方法は [SDK撤去](docs/brain/sdk-retirement.md)。


v0.39.0では、Antigravity CLIを明示接続するBrainとCodex CLI／Antigravity CLIに依頼する承認付きローカル開発タスクを統合しました。Development Hubから「CLIの開発タスク・進捗を見る」を開いて、許可したGitルート・目的・CLIを選び、承認後の状態・差分・静的チェックを確認できます。元checkoutは変更せず、専用コピーで作業します。任意Shell・実テストコード実行・削除・Push/PR/mergeは未対応です。[設計・制約](docs/dev/coding-tasks.md)、[実CLIの合成受入](reports/antigravity-cli-brain-live.json)を参照。

v0.34.3ではSona Coreの実行分岐とLinkraft専用同期を撤去し、予定/承認は既存Renaissance Core・Registryへ統一しました。既存SQLiteデータと過去のLinkraftリンク/イベントは削除しません。移行・検証は[撤去ガイド](docs/ops/integration-removal.md)を参照してください。

v0.34.2は開発規約の更新です。`AGENTS.md`にコード削除の事前調査・互換性保護・回帰検証と段階的整理の方針を明文化しました。実機能の削除・変更はありません。

v0.34.1ではSettingsに公式Antigravity CLIの導入検出と未検証状態を追加しました。
Googleログインの既存契約枠でPETITを動かす接続は、公式資料の矛盾とRead専用境界が
未解決のため本番無効です。SDK+LM Studio/Gemini APIはこの目的の達成には含めません。
[Windows/macOS導入・直接診断・Mock検証・残る受入](docs/brain/antigravity-cli.md)を参照。

v0.33.0開発版は、公式Antigravity SDKを選択式のRead専用Brainとして接続します。既定の推論先はloopback LM Studioで、追加のクラウドAPI課金は不要です。導入・モデル選択・実測と未確認範囲は[SDK導入記録](docs/brain/antigravity-brain-poc.md)を参照してください。Gemini API単独の追加とは区別します。

v0.32.0開発版は[単一Brainと永続Thread/Turn](docs/core/renaissance-core.md)を導入します。会話は明示して切り替え、再送は同じrequest IDで結果を照会します。既存DBは初回schema追加前にSQLiteバックアップを作成します。実運用はCore 1プロセス（workers=1）です。実Provider/配布版/実端末の受入は別途です。

設計とデータソースの役割は [docs/core/assistant-architecture.md](docs/core/assistant-architecture.md) を参照。
主要な概念の使い分けは [docs/terminology.md](docs/terminology.md) を参照。
DesktopをPCの主入口にする全体の目標・会話/実行の正本・起動/復旧・段階移行は [Desktop・共通Core基盤設計](docs/desktop/desktop-foundation-design.md) を参照。Brain/Context Brokerの方針は [docs/jarvis-agent.md](docs/core/jarvis-agent.md)。目標の新API/管理Coreは未実装です。


v0.30.3の開発ブランチでは、会話からの作業セッション開始、対象IDの引き継ぎ、重複開始と失敗再試行を改善します。開始報告はTool結果と保存状態を照合します。実モデルE2Eは未確認です。[再現・修正範囲・受入条件](docs/core/conversation-action-reliability.md)を参照。

DeepSeek中心の意図理解とTool Callingへの方針・3方式の比較・本番未接続の実験は [AI-First Agent Architecture](docs/core/ai-first-agent-design.md) を参照。既存の会話経路はまだ移行していません。

v0.31.0の開発ブランチでは、Web/旧UI/Desktop小型会話に画像添付を追加します。PNG/JPEG/WebPを4枚・各8MiBまで、画像だけでも送信できます。観測と考察を分離し、既知のSteam指標はPythonで比率を検証します。実Providerの画像認識品質・配布Desktop/macOS/PWA実機は未確認です。[設計とフェーズ](docs/channels/multimodal-discord-plan.md)、[受入セット](docs/channels/multimodal-acceptance.md)を参照。

画像はCoreに24時間保存します。クラウドへの画像・認識内容送信は既定OFFです。利用者が明示許可する場合だけ、サーバーの`.env`に `PETIT_ALLOW_CLOUD_IMAGES=true` を追加しBackendを再起動してください。Visionは既存の `PETIT_DEEPSEEK_API_KEY` / `PETIT_DEEPSEEK_FLASH_MODEL=deepseek-flash` を使用します。APIキーをClientやGitへ置かないでください。Chatの回答Providerは既存設定を使用します。

ローカル画像認識は `PETIT_VISION_PROFILE=local` とし、Chat側のLM Studioモデルを画像対応モデルに設定します。選択モデルの `GET /api/v1/models` が `capabilities.vision=true` を返す場合だけ利用できます。能力不明の旧LM Studioは更新してください。外部ホスト名のLM Studio接続もクラウド送信許可の対象です。ローカルはlocalhost・プライベートIP・`.local`ホストを使用します。

HTTP契約は `POST /api/attachments` に画像実体（multipart不要）、`X-PETIT-Session` に既存会話ID（16〜200文字）を送り、返された`id`を `/api/chat` の `attachment_ids` で参照します。参照と削除も同じheaderで `GET / DELETE /api/attachments/{id}`。既存の文字だけの `/api/chat` は維持します。会話IDはローカルClientの境界でありユーザー認証の代わりではありません。無認証のCoreをインターネット公開しない構成を維持してください。

v0.30.0ではUnivの遠景星空・ドラッグ操作とRemindersの通知センター配置を改善しました。 v0.30.1では予定名のキーワード検索とCAPCOM/カプコン別名に対応しました。 v0.30.2ではDesktopのOS通知音を任意で有効化でき、通知の表示診断を改善しました（OS上の受信・実音は未確認）。v0.29.0から、上部同期表示・Settingsから接続ステータスとNotion同期失敗の詳細を確認できます。保存済み状態を表示し、接続確認・再試行は明示操作で実行します。[接続ステータス](docs/channels/connection-status.md)を参照。

## 構成

```text
backend/   FastAPI サーバー・エージェントループ・ツール
frontend/  チャット UI（静的ファイル）
storage/   SQLite などの実行時データ（git 管理外）
```

## Windows / macOS Desktop（段階導入）

v0.28.0（開発版）は、タスク選択から作業開始までの導線を整理し、統計の日付選択と振り返り保存、タブ切替後のDesktop復旧判定を改善します。[作業開始と振り返り](docs/archive/desktop-v28-ux.md)を参照。

v0.27.0（開発ブランチ）は、小窓の惑星を削除し、作業中バーの上部固定・詳細開閉、Chatの会話欄だけのスクロールと常駐入力、Univの惑星本体の発光・ミドルドラッグ移動に対応します。検証範囲は [Desktop / Web v0.27.0](docs/archive/desktop-v27-experience.md) を参照。

「統計」タブで今日の合計作業時間・タスク別内訳・7日間の棒グラフ・作業記録を振り返れます。休憩と日をまたぐ作業は既存Coreで集計します。[作業統計](docs/life/work-statistics.md) を参照。

v0.26.0（開発ブランチ）はWindowsの更新ダウンロード/検証、作業中の星、共通入力、Notion同期競合の手動比較・採用、Desktop通知と画面のすみの声かけに対応します。新しい通知/競合APIにはv0.26.0のサーバーも必要です。実装・未確認・次の音声体験は [Desktop v0.26.0](docs/archive/desktop-v26-experience.md) を参照。

v0.25.0では、小型会話の「作業画面」から既存Tasks / Universeをアプリ内で開けます。接続・画面停止の復旧画面、小型会話の下書き保持、待機中断、位置保持に対応。Backendは別途起動してください。使い分けと実機受入は [Desktop完成・受入台帳](docs/desktop/desktop-readiness.md) を参照。

既存PETITへ接続するElectron常駐クライアントを追加しています。小型会話UI、トレイ、グローバルショートカット、更新通知、任意の日本語ウェイク検出に対応する初期実装です。
`desktop`で`npm ci && npm start`を実行し、接続先を設定してください。音声認識にはWhisper互換サーバーを設定します。ウェイク検出はopenWakeWordを使用し、ONNXモデルを選んで「ウェイク環境を自動設定」を実行します。Wakeまたは「音声会話」から、返答再生後に次の発話を待つ連続会話を開始できます。
設計比較、権限、ビルド、検証範囲は [docs/desktop.md](docs/desktop/desktop.md) を参照。iPhoneは既存PWAを継続します。

AccessKey不要の方式に向けた「へいプティ」の実験モデル学習は [openWakeWord学習環境](docs/voice/openwakeword.md) を参照。Desktop実行経路は統合済みです。実モデルの配布と実声・実マイクでの精度評価は未確認です。

## 開発ジョブ（v0.52.0）

[Develop タブ](/static/universe.html?view=development) でフォルダを登録し、モデル・Effort・依頼内容を選んで直接送信できます。Chat の開発提案も同じ一覧に表示され、開始ボタンで実行します。Git では専用ブランチで作業し、PC 上の元ファイルへの操作は個別に承認します。詳細は [開発ジョブ](docs/dev/coding-tasks.md) を参照してください。

## Activity（v0.38.0・ジョブ状態の確認）

Development Hubに、PETITの既存SQLite Job（background_research / agent_followup）の実行待ち・実行中記録・完了・失敗の一覧を追加しました。管理者認証後、Dev画面の「ジョブ状態を更新」で結果を取得できます。APIは GET /api/activity/jobs?limit=30。最大100件で、入力本文・出力本文・エラー本文を返さず、通知の既読/ACKも変更しません。runningはDB上の状態であり実プロセス生存の保証ではありません。PR #371のCoding Jobs、長時間処理の自動復旧・lease・通知連携は未統合です。

## ローカル開発状況の参照

Develop で登録済みフォルダの観測結果を確認できます。Git のブランチ・HEAD・変更数・直近コミット・ルート文書の観測に、環境変数での有効化は不要です。環境変数 `PETIT_WORKSPACE_CONTEXT_DIRS` の登録分も表示されます。追跡 ref の比較はローカルに保存された状態を使います。[ローカル開発環境の読取](docs/dev/local-development-insight.md)

## 初期設定・接続管理（v0.34.0 開発版）

初回起動時は管理者認証付きウィザードへ進み、AI優先順位、Codex公式認証、Antigravity SDK / DeepSeek、Notion、Google Calendar / Gmail、TimeTreeを設定できます。設定はGit管理外の`storage/settings/`へ暗号化保存します。API料金・クラウド文脈送信は事前同意が必要です。Local / Cloudのコードは共通で、Cloudの初期登録にはHTTPSと`PETIT_BOOTSTRAP_TOKEN`を用意します。

CLI中心で使う場合は「Brainの接続方式」を「CLIのみ」にして、CodexのChatGPT認証またはAntigravity CLIの明示接続を行い、優先順位の会話利用をONにして保存します。サーバー上の公式CLIへ会話・Tool選択を渡し、承認・実行・保存は既存Coreが管理します。SDK/APIへ自動切替しません。既存設定は従来どおり引き継ぎ、CLI画像対応は未実装です。実Codex推論の受入は未確認です。

Calendarは読み取り専用で、選択した外部サービスからSQLiteへ02:00 JSTに差分同期します。未解決エラーは通知と会話へ反映します。Google双方向同期・Tool実行後のProvider間継続・本人の外部認証を伴う全サービス受入は未完了です。導入前提・既存クライアントの認証への影響・検証手順は[初期設定と接続](docs/ops/setup-integrations.md)を参照してください。

## セットアップ

1. 依存をインストール:

   ```bash
   pip install -r requirements.txt
   ```

2. LM Studio を起動し、ローカルサーバー（OpenAI 互換）を有効にする。
   デフォルトは `http://localhost:1234/v1`。モデルをロードしておく。

3. サーバー起動:

   ```bash
   uvicorn backend.main:app --reload --reload-dir backend
   # または
   python -m backend.main
   ```

   プロジェクトルートの `.env` は起動時に自動読込されます。既に設定されているOS環境変数が優先されます。

4. ブラウザで <http://127.0.0.1:8000> を開く。

マイクからチャットへ送る場合は [音声入力の設定・Macの確認手順](docs/voice/voice_mode.md) を参照してください。ブラウザ認識に加え、Whisper互換サーバーによる録音認識を選択できます。

5. 音声読み上げを使う場合は [`docs/voice/aivis_speech.md`](docs/voice/aivis_speech.md) の初期セットアップへ進む。
   - AivisSpeechを使う場合は、Windowsでのインストール → 音声モデル追加 → Engine起動 → `/docs` / `/speakers` → `.env` → 診断CLI → WAV再生の順で確認します。
   - AivisSpeechが未準備・停止中でもチャットは利用でき、対応ブラウザでは無料のブラウザ標準TTSへフォールバックできます。
   - 有料TTS APIは前提ではありません。

## TailscaleでTailnet内へ公開する

PCとアクセスする端末を同じTailnetへ接続すると、PETITを次のようなHTTPS URLで開けます。

```text
https://PC名.tailnet名.ts.net
```

これは同じTailnet内だけの公開です。インターネット全体へ公開するTailscale Funnelは使用しません。

### 1. PETITを起動する

PowerShellでPETITのルートへ移動し、ローカルホストで起動します。

```powershell
cd "C:\PETITを置いている場所\PETIT"
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

先にPC上で動作を確認します。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

ブラウザでも <http://127.0.0.1:8000> を開きます。

Windowsでは、`scripts/start-petit-tailscale.ps1` をPowerShellから実行すると、起動モード選択、Tailscale接続、PETIT起動、ヘルスチェック、Tailscale Serve設定、ブラウザ起動まで連続実行できます。LM Studioは先に起動し、モデルをロードしておいてください。Tailscale Serve開始時には管理者権限の確認が表示されます。

```powershell
cd "C:\#Project\Server\PersonalAssistant_PETIT"
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start-petit-tailscale.ps1
```

### 2. Tailscale Serveで公開する

別の管理者権限PowerShellを開きます。

```powershell
tailscale status
tailscale serve --bg http://127.0.0.1:8000
tailscale serve status
```

成功すると、次のようなURLが表示されます。

```text
https://PC名.tailnet名.ts.net
```

`--bg`を付けるとPowerShellを閉じてもServe設定が維持されます。ただし、PC再起動後も利用するにはPETITのFastAPI自体を再度起動する必要があります。

### 3. iPhoneなどから開く

1. PCと同じTailnetのTailscaleアカウントでログインする
2. TailscaleをONにする
3. Safariなどで表示されたHTTPS URLを開く

公開状態を確認する場合:

```powershell
tailscale serve status
```

公開を停止する場合:

```powershell
tailscale serve off
```

設定を完全にリセットする場合:

```powershell
tailscale serve reset
```

## 環境変数（主なもの）

| 変数 | 既定値 | 説明 |
|------|--------|------|
| `PETIT_LM_BASE_URL` / `PETIT_LM_MODEL` / `PETIT_LM_API_KEY` | local default | 旧互換の共通設定。個別設定未指定時のフォールバック |
| `PETIT_CHAT_BASE_URL` / `PETIT_CHAT_MODEL` / `PETIT_CHAT_API_KEY` | 各 `PETIT_LM_*` | 雑談・短い確認用の接続先・モデル |
| `PETIT_AGENT_BASE_URL` / `PETIT_AGENT_MODEL` / `PETIT_AGENT_API_KEY` | 各 `PETIT_LM_*` | ツール・計画・BRAIN/Notion/予定用の接続先・モデル |
| `PETIT_LIGHT_MAX_TOKENS` | `512` | 軽量回答の最大生成量 |
| `PETIT_MAX_TOOL_ITERATIONS` | `3` | 1ターンで許可するツール実行ラウンド数。最終回答用のLLM呼び出しは別に許可 |
| `PETIT_TOOL_RESULT_MODE` | `auto` | `role=tool`を優先し、LM Studioのテンプレート非対応時だけ互換user follow-upへ退避。`tool` / `user`固定も可能 |
| `PETIT_OWNER_ID` | `soso` | PETIT内部ユーザーID |
| `PETIT_HOST` / `PETIT_PORT` | `127.0.0.1` / `8000` | サーバーの待受 |
| `PETIT_TTS_PROVIDER` | `aivis` | 読み上げProvider。AivisSpeech未利用時もチャットは動作 |
| `PETIT_TTS_BASE_URL` | `http://127.0.0.1:10101` | PETITプロセスから見たAivisSpeech Engine接続先 |
| `PETIT_TTS_STYLE_ID` | 空欄 | 空欄なら`/speakers`の最初のスタイルを自動選択 |
| `PETIT_TTS_TIMEOUT` | `30` | AivisSpeech Engine応答待ち秒数 |
| `PETIT_OBSIDIAN_VAULT_DIRS` | なし | RAG検索対象にする既存Obsidian vault。Windowsは`;`区切り |
| `PETIT_VAULT_SUBDIR` | `PETIT` | PETITがMarkdownを書き込むvault内サブディレクトリ |
| `PETIT_EMBED_RETRY_SECONDS` | `60` | Embedding停止時の再試行間隔 |
| `PETIT_CALENDAR_ICS_URLS` | なし | Google CalendarなどのiCal/ICS URL |
| `PETIT_CALENDAR_ICS_FILES` | なし | ローカルの`.ics`ファイル |
| `PETIT_CALENDAR_SYNC_TTL_SECONDS` | `300` | カレンダー読み取り同期のTTL |
| `PETIT_AI_DAILY_DIR` / `PETIT_AI_MEMORY_DIR` | vault設定時は`<vault>/PETIT/Daily` / `Memory` | 会話ログ・長期記憶Markdownの出力先 |
| `NOTION_API_KEY` | なし | NotionインテグレーションのAPIキー |
| `NOTION_PROJECTS_DB_ID` | なし | 個人プロジェクトDBのID |
| `NOTION_TASKS_DB_ID` | なし | タスクDBのID |
| `NOTION_SYNC_TTL_SECONDS` | `300` | Notion読み取り同期のTTL |
| `NOTION_PROP_TITLE` | `name` | 旧互換タスク名プロパティ |
| `NOTION_PROP_DUE` | `Date` | 期限/日時プロパティ |
| `NOTION_PROP_STATUS` | `Status` | 状態プロパティ |
| `NOTION_PROP_PRIORITY` | `Priority` | 優先度プロパティ |
| `NOTION_PROP_CATEGORY` | `Category` | 分類プロパティ |
| `NOTION_PROP_DONE_DATE` | `DoneDate` | 完了日プロパティ |
| `PETIT_GITHUB_TOKEN` | なし | private repositoryにも使える最小権限のGitHub read token |
| `PETIT_GITHUB_API_URL` | `https://api.github.com` | GitHub REST APIの接続先 |
| `PETIT_GITHUB_SYNC_TTL_SECONDS` | `300` | GitHub evidence同期のTTL |
| `PETIT_GITHUB_INITIAL_LOOKBACK_DAYS` | `30` | 初回同期で遡る日数 |
| `PETIT_GITHUB_MAX_CHECK_COMMITS` | `50` | 1回でcheckを確認するcommit数の上限 |
| `PETIT_GITHUB_MAX_DEPLOYMENTS` | `20` | 1回でstatusを確認する最近のdeployment数 |
| `PETIT_VAPID_PUBLIC_KEY` | なし | ブラウザ購読に渡すURL-safe Base64のVAPID公開鍵 |
| `PETIT_VAPID_PRIVATE_KEY` | なし | Git管理外に置くVAPID秘密鍵PEMの絶対パスまたはエンコード済み秘密鍵 |
| `PETIT_VAPID_SUBJECT` | なし | VAPID連絡先。`mailto:`または公開可能な`https:` URL |
| `PETIT_WEB_PUSH_TTL_SECONDS` | `300` | Push Serviceが通知を保持する秒数 |

AivisSpeech、Notion Adapter v2、Notion会話検索、GitHub evidence、Web Pushの詳細設定は、
[`docs/voice/aivis_speech.md`](docs/voice/aivis_speech.md)、
[`docs/life/notion_adapter_v2.md`](docs/life/notion_adapter_v2.md)、
[`docs/life/notion_search.md`](docs/life/notion_search.md)、
[`docs/dev/github_evidence.md`](docs/dev/github_evidence.md)、
[`docs/channels/web_push_notifications.md`](docs/channels/web_push_notifications.md) を参照してください。

## 現在使える主なツール

- `save_memory` / `search_memory` — 記憶の保存・検索
- `search_brain_notes` / `edit_brain_note` — BRAINを限定検索し、安全に追記・完全一致置換
- `get_tasks` / `create_task` / `complete_task` — タスク取得・作成・完了
- `add_task` — ローカルDBだけに保存する旧タスク追加
- `create_handoff_note` / `restore_context` — 中断時の引き継ぎ・復帰
- `summarize_now` — 未整理会話の手動要約
- `sync_obsidian_vault` — 既存Obsidian vaultをRAG検索用に同期
- `get_schedule` / `add_schedule` / `sync_calendar` — 予定取得、ローカル予定追加、ICS同期
- `create_daily_briefing` — 予定・タスク・最近の流れから朝ブリーフィングを作成
- `get_current_time` — 現在の日付・時刻
- `get_weather` / `search_news` / `start_background_research` — 天気・ニュース・調査キュー
- `create_internal_project` / `activate_internal_project` / `add_internal_project_alias` — 確認後に内部プロジェクトを登録・切替・別名追加
- `save_project_completion` — 確認済み到達状態をcheckpointとイベントへ保存
- `search_notion` — 共有済みNotionページを限定検索し、プロパティ・本文抜粋・更新日時・URLを取得
- `sync_notion_tasks` / `get_notion_project_candidates` / `link_notion_project_candidate` — Notion Relation同期と確認付き紐付け
- `inspect_github_repository` / `sync_github_evidence` — GitHub repository候補の読取と確認済みrepositoryの証拠同期
- `get_github_repository_candidates` / `link_github_repository_candidate` — GitHub候補一覧と確認付き紐付け

## Project Continuity Engine

PETITは複数プロジェクトの開始・終了・切り替え・再開をSQLiteで継続管理します。v0.45.0で旧来の決定論的な経路（キーワードで先に処理する方式）は撤去し、会話のBrainが `activate_internal_project` / `restore_context` / `get_project_status` / `save_project_completion` などのToolで扱います。以下の保存形式と確認の考え方は変わりません。

### 開始・再開

```text
WEVORAやる
プチ進める
PETITに戻る
さっきの続きやる
```

確認済みの正式名・別名が一意なら、`active_project_state`を切り替えます。

> v0.45.0注記: 以下の「再開時の外部source自動更新」と固定順の再開文脈は旧ルーター（`project_resume` / `project_source_refresh`）の機能で、撤去済みです。現在は日次同期と `sync_notion_tasks` / `sync_github_evidence` などのToolで更新します。記録は [docs/archive/project_source_refresh.md](docs/archive/project_source_refresh.md)。

旧実装では、選択した内部プロジェクトに紐付く外部sourceのうち、次の条件をすべて満たすものだけを更新していました。

```text
project_id = 選択したプロジェクト
status = active
confirmed_at IS NOT NULL
```

- Notionは再開ターン内で最大1回だけ、既存TTLを尊重して同期します。
- GitHubは選択プロジェクトの確認済み`owner/name`だけを読み、commit・PR・check・deploymentを別種のevidenceとして同期します。
- 未確認候補、removed link、別プロジェクト、未対応providerは呼びません。旧Linkraftリンクは保存したまま `skipped` 扱いとします。
- 1ソースが失敗しても、保存済みcheckpointからの再開は止めません。
- 前回成功キャッシュがある場合は保持し、staleと明示します。

同期後、次の順で対象プロジェクトだけを取得します。

1. `project_checkpoints`
2. 確認済み・正規化済み`project_events`
3. 確認済み`episode_project_links`の会話エピソード
4. 旧`handoff_notes`の互換情報
5. 確認済み外部source linkのfresh/stale状態

別プロジェクトの記憶や未確認Relationは混ぜません。別名が衝突する場合は候補を出し、勝手に切り替えません。詳細は [`docs/archive/project_source_refresh.md`](docs/archive/project_source_refresh.md) を参照してください。

### 終了確認

```text
終わった
実装だけ終わった。ブラウザ確認はまだ
テストも通った。次は実画面確認
デプロイしたけど本番確認はまだ
今日はここまで
```

`終わった`を即座に完全完了へせず、実装・自動テスト・実画面・デプロイ・本番確認のどこまで到達したかを確認します。明示された事実だけを証拠として扱い、プレビュー承認後に一度だけ保存します。

保存状態は最低限、`implemented`、`automated_tests_verified`、`ui_verified`、`deployed`、`production_verified`、`paused`、`blocked`、`completed`を区別します。

### GitHub evidenceと完了状態の境界

GitHub上の事実は、PETIT checkpointを自動で上書きしません。

- commit存在は、特定のrevisionが存在する証拠であり、実装全体の完了証明ではありません。
- check successは、そのcheckが対象SHAで成功した証拠です。実画面・本番確認は証明しません。
- PR mergeはbase branchへ統合された証拠です。deployは証明しません。
- deployment successはGitHubがenvironment/refへの配布成功を報告した証拠です。本番機能確認は証明しません。

同じcheckが`in_progress`から`success`へ変わる場合はdefault branch headを再確認し、deployment本体の作成後にstatusだけ変わった場合も最近のdeployment statusを再確認します。

### 新規登録・別名

```text
Roomies開発する
「Cooking Combat」をプロジェクト登録して
「プチ」をPETITの別名にして
```

未登録名は自動作成せず、登録プレビューを表示します。承認後に`projects`と`project_aliases`へ一度だけ保存し、必要なら現在プロジェクトへ切り替えます。別名衝突は事前に明示し、承認して追加した場合も以降のルーティングでは候補確認を維持します。

### 外部ソース

SQLiteは外部正本を置き換えず、内部ID、別名、確認状態、checkpoint、source link、正規化イベント、キャッシュを保持します。source linkは未確認候補として登録でき、確認・解除・再割り当てが可能です。

現在接続済み:

- 個人プロジェクト・個人タスク: Notion Adapter v2
- コード・PR・CI・deploymentの事実: GitHub evidence Adapter

次の対象:

- 長期知識・設計: BRAIN / Obsidian

## 会話処理の流れ

1回の会話（Turn）は、優先順位で選んだ1つのBrain（Antigravity CLI / Codex / Claude Code CLI / DeepSeek / LM Studio）が最後まで担当します。キーワードで先に処理する旧ルーター（v0.44.0まで残っていたもの）はv0.45.0で撤去しました。

- Brainは最初に小さなTool集合（時刻・タスク・予定・天気・ニュース・朝ブリーフィング）と、全Toolの名前一覧を受け取ります。他のToolは `discover_tools` で詳細を取得してから呼びます。
- 書き込みは確認カードで承認を取り、承認は一度だけ消費します。結果は実行記録（receipt）と一緒に保存します。
- 8 rounds / 12 calls で止まります。Toolを実行する前の障害に限り、次の候補のBrainへ切り替えます。
- 画像付きの会話は、画像の観測結果をもとに回答だけを返し、操作はしません。

詳細なフローは [docs/runtime-flows.md](docs/runtime-flows.md)、旧ルーターの記録は [docs/archive/runtime-flows-legacy-routing.md](docs/archive/runtime-flows-legacy-routing.md) を参照してください。

## Web Push通知

Service Worker、Push API、VAPIDを使い、ブラウザを閉じている場合もPETITの通知を受け取れます。購読情報、カテゴリ別設定、通知イベント、端末ごとの配信結果はSQLiteへ保存します。

通知カテゴリはすべて初期OFFです。ヘッダーの通知設定から端末を購読すると、無限計測を防ぐ作業セッション通知だけ同時にONになります。ほかは必要な種類だけ有効にしてください。作業開始後は20分ごとに継続を確認し、確認から20分返事がなければサーバー側で時間の加算を止めます。通知生成側は`dispatch_notification()`を呼び、配信先は`NotificationProvider`境界へ分離しているため、将来は同じ通知判断ロジックへAPNs Providerを追加できます。

作業時間はNotion Task DBのプロパティではなく、Notionを含むTaskのPETIT内部IDへ紐づけたSQLiteセッションとして保存します。Universeの「作業開始」に加え、チャットから「このタスクを開始」「一時停止」「再開」「今日はここまで」を操作でき、「いま何分？」「今日どれに何分？」「最近7日の作業時間」のように現在・今日・直近1〜90日を集計できます。Task名が0件または複数件に一致する場合は勝手に作成・開始せず、候補を返します。

VAPID未設定・依存未導入・通知無効時も既存チャットは動作します。設定、API、実iPhone PWA確認手順は[`docs/channels/web_push_notifications.md`](docs/channels/web_push_notifications.md)を参照してください。

## Calendar

Google CalendarのCodex/MCP接続はPETITプロセスへ自動共有されません。PETIT側で読むには`PETIT_CALENDAR_ICS_URLS`に非公開iCal URLを設定するか、`PETIT_CALENDAR_ICS_FILES`にエクスポート済み`.ics`を指定します。

同期結果はSQLiteの`sync_state`へソース別に保存し、取得失敗時は直前の正常キャッシュを維持します。TimeTreeは`TIMETREE_EMAIL` / `TIMETREE_PASSWORD` / `TIMETREE_CALENDAR_CODE`を設定した場合だけ読み取り専用ICSソースとして同期します。

`add_schedule`はICSやGoogle Calendar本体へは書かず、現在はPETITローカル予定だけへ追加します。

## 書き込み確認

Notionタスク作成・完了、ローカル予定追加、長期記憶、引き継ぎ、BRAIN修正、プロジェクト登録・別名追加・終了checkpoint保存、外部プロジェクト候補の紐付けは、ツール呼び出し時点では実行されません。

ブラウザに対象と変更内容、および「実行する / キャンセル」を表示し、`POST /api/actions/{approval_id}`で確認された操作だけを1回実行します。確認待ちは10分で期限切れになります。

BRAIN編集は設定済みVault内の既存`.md`だけに限定し、`_private`・除外フォルダ・Vault外パスを拒否します。


LM Studioが未起動でもサーバーは落ちず、UI上にエラーを表示します。

## Obsidian vault をPETITのMarkdown脳にする

既存のObsidian vaultを使う場合は`.env`などで`PETIT_OBSIDIAN_VAULT_DIRS`を指定します。PETITは`_private`・添付・内部設定を除くMarkdownを`petit_vault`としてChromaに索引化し、`search_memory`から会話記憶・要約・vaultノートを横断検索します。

PETITが自動追記するMarkdownは、既定では最初のvault内の`PETIT/Daily`と`PETIT/Memory`に置かれます。既存ノートは読み取り・検索対象、自動書き込みは`PETIT/`配下に限定します。

## 開発

- 主軸ブランチは`develop`。機能追加は`feat/<機能名>`。
- Project Continuity限定テスト:

  ```bash
  python -m unittest \
    tests.test_project_continuity \
    tests.test_project_completion \
    tests.test_project_registration \
    tests.test_notion_adapter_v2 \
    tests.test_github_evidence \
    tests.test_github_client_evidence \
  ```

- Notion会話検索テスト: `python -m unittest tests.test_notion_search -v`
- Web Push通知テスト: `python -m unittest tests.test_notifications -v`
- 作業セッション停止テスト: `python -m unittest tests.test_work_sessions -v`
- 作業記録Tool・UIテスト: `python -m unittest tests.test_work_session_tools tests.test_work_session_ui -v`
- AivisSpeech診断CLI確認: `python scripts/diagnose_aivis_speech.py --help`
- AivisSpeechテスト: `python -m unittest tests.test_aivis_speech -v`
- 全Python構文確認: `python -m compileall backend tests scripts`
- 変更のたびに`PROGRESS.md`へ追記する。
- ルール詳細は[`CLAUDE.md`](CLAUDE.md)。
