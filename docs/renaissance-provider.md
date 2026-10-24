# メインBrain Provider導入記録 — #349

確認日: **2026-10-24 UTC / 2026-10-25 JST**。基準main: `4135053`（Notion PR #350マージ済み）。
実装: **Gemini API**。Antigravity CLI / SDK統合済みとは表示しない。main未マージ。

## 採用判断と一次情報

| 経路 | 正式な利用方法・費用 | 今回の判断 |
|---|---|---|
| Antigravity CLI | 本人の直接スクリプト・CIにheadlessを提供。個人の月額枠とAPI課金は別 | FAQが個人プランでの第三者アプリ内ラップを非サポートと明記。PETITに組み込まない |
| 公式Antigravity SDK | `google-antigravity`、Python >=3.10、Apache-2.0。Gemini APIキーまたはVertex。API料金・上限は別途 | 最優先で公式仕様とWindows wheel 0.1.22の公開Python APIを検査。SDK自身が実行ループ・Tool実行・履歴/セッションを所有するため、既存native Brainへの薄いcompletion Adapterとして今回は不採用 |
| Gemini API | 公開OpenAI互換REST、APIキー・API課金/無料枠 | **採用**。既存クライアントへprofileを追加。新しい実行ループ、意図ルーター、返答テンプレート、依存は追加しない |
| DeepSeek Flash | 既存APIキー・従量課金 | 選択可能な既存Brainと、明示許可したThreadでのFallbackを維持 |
| LM Studio | ローカル推論。外部API従量料金なし（機材・電力等は別） | 既定値とlocal_onlyを維持。クラウドへ自動移行しない |

- [公式FAQ](https://www.antigravity.google/docs/faq)、[Antigravity規約](https://antigravity.google/terms?hl=ja): headlessの一般説明を、第三者アプリ組み込み許可とは解釈しない。
- [公式headless](https://www.antigravity.google/docs/cli/headless/)、[2026-10-16 Forum](https://discuss.ai.google.dev/t/clarification-on-consumer-plan-policy-for-invoking-official-agy-via-local-subprocess/189905): 直接個人スクリプトとPETITラップを区別し、FAQを優先。
- [公式SDK](https://www.antigravity.google/docs/sdk/overview/)、[Tools](https://www.antigravity.google/docs/sdk/tools/)、[Lifecycle](https://www.antigravity.google/docs/sdk/lifecycle/)、[公式パッケージ](https://pypi.org/project/google-antigravity/0.1.22/)。wheelのメタデータと`Agent.chat`、`Conversation.chat`、`LocalAgentConfig`を確認した。
- [OpenAI互換API](https://ai.google.dev/gemini-api/docs/openai)、[Gemini API規約](https://ai.google.dev/gemini-api/terms)。APIキー方式は個人Antigravity OAuthを転用しない。

SDKは実在しWindows amd64/arm64・macOSのwheelもある。`Agent.chat`はセッション上の応答を返し、Callable ToolをSDK内で実行する。built-in Toolを制限する機能やhooksはあるが、**PETITがnative Tool callを受け取り、Approval/ReceiptとSQLite transactionを完了してから一段だけモデルを再開する**既存契約を、そのまま満たす公開completion APIは確認できなかった。SDKのpolicy/保存/再開を移植する方式は二重化になる。この版への適合判断であり、将来のSDK全般を不可能と断定しない。実SDKモデル呼出しは未実施、共有環境へのSDKインストールも行っていない。

WindowsのPATHに`agy` / `antigravity`は見つからなかった。バージョン・認証・exit code・streaming・CPU負荷の実測は未実施。macOS実機にもアクセスしていない。OAuth保存領域や非公開APIは読んでいない。

## API費用・制限

[Gemini公式価格](https://ai.google.dev/gemini-api/docs/pricing)、[DeepSeek公式価格](https://api-docs.deepseek.com/quick_start/pricing/)を確認。以下はStandard、USD / 100万token（税・為替・追加サービス別、確認日の価格）。

| モデル | 入力 | 出力 | 備考 |
|---|---:|---:|---|
| Gemini 3.8 Flash | $0.75 | $3.75 | 2026-12-31まで。2027-01-01以降 $1.50 / $7.50と掲載。出力はthinking込み |
| DeepSeek Flash | cache miss $0.15〜$0.30 | $0.60〜$1.20 | off-peak / peak。cache hitは $0.003〜$0.006 |

Google AI Pro/Ultra等の月額購入を、このAPIの支払い・無料枠・SDKの無制限利用と混同しない。SDKの同一モデルAPI利用にもAPI側の課金・制限が適用される。Vertex/Enterpriseは契約・モデルごとの価格を別確認する。

Geminiの無料APIにはモデル・quota制限とデータ利用条件がある。**無料サービスには機密・個人情報を送信しない**という規約を確認した。実データを扱う際は課金プロジェクトとデータ取扱条件を確認する。APIが返さないアカウント残枠・費用・quotaは推測せず`unknown`。token数から月額枠を推定しない。

少量・低コスト重視ならDeepSeek Flash継続、外部へ送らない用途ならLM Studio継続が妥当。Geminiの実品質・latency・CPUはキー未設定のため今回未評価。Tool schemaと往復履歴も入力tokenになり、1つの会話で複数回課金され得る。

## 設定と使用

サーバーの`.env`へ追加し、再起動する。キーは画面やチャットに貼らない。

```dotenv
PETIT_GEMINI_API_KEY=実際のAPIキー
PETIT_GEMINI_MODEL=gemini-3.8-flash
PETIT_CHAT_PROFILE=gemini
PETIT_DEEPSEEK_API_KEY=実際のDeepSeekキー
PETIT_DEEPSEEK_FALLBACK_THREADS=
```

`GEMINI_API_KEY`も利用可能。既存の`storage/model_routing.json`があれば保存済み選択が優先されるため、Web/Desktopの既存設定でChatを **Gemini API** に変更する。キーを置いただけでは切り替わらない。APIでは`POST /api/model-routing {"chat":"gemini"}`。単一BrainはChatを使用し、Agent選択を変更する必要はない。

通常会話も既存公開Toolも同じBrainに接続。Thread/Turn/Approval/Receipt・schema・Notionコードは変更しない。画像は従来の同意・Vision経路を維持し、今回Gemini画像入力は対応しない。

Web/Desktopの会話欄「最新の依頼」を開くと`model_route`を確認できる。`GET /api/turns/{request_id}`とThread Eventsでも、実際に試行したprovider/model、token usageまたはunknown、latency、分類済みerror、fallback理由が得られる。本文・APIキー・生のエラー応答は診断Eventsへ入れない。承認待ち・失敗・再起動後も保持する。残枠はunknownで表示する。

### Fallbackの同意と安全境界

1. 会話のThread IDを`GET /api/threads`や`?thread=...`で確認する。
2. **そのThreadの履歴をDeepSeekへ送ってよい場合だけ**、`PETIT_DEEPSEEK_FALLBACK_THREADS=thread-id-1,thread-id-2`を設定して再起動する。既定は空、ワイルドカードは使えない。
3. primaryがGeminiで、最初のモデル応答前に429/5xx/接続障害/タイムアウトが発生したときだけ、一度DeepSeek Flashを試す。receiptがあれば切り替えない。
4. Read後もWrite後も、承認再開後もFallbackしない。401/402/403、設定不足、壊れたJSON/空返答は失敗分類を返し、自動切替しない。429はquotaかrate limitか判別できないため`quota_or_rate_limit`。
5. 切替先をTurnに固定。承認再開時も同意と元Provider設定を検査し、固定先以外へ保存文脈を自動送信しない。同意撤回/Provider設定変更では停止する。Threadのlocal_onlyは常に外部送信禁止。

Fallbackは初回応答前だけの保守的な実装。既存の再送・Receipt照会を使い、途中のWriteを別Providerでやり直さない。両Provider失敗時は失敗を返して履歴を保存する。未知の外部効果は従来どおり自動再実行しない。

## 検証・再実行

```powershell
python -m pytest tests/test_gemini_provider.py tests/test_renaissance_core.py tests/test_model_route_switcher.py -q
node --test scripts/test-thread-client.cjs
# 必ず合成データ・一時DB/Workspaceのみ。Gemini未設定ならskippedを記録する。
python scripts/smoke-brain-provider.py --profile gemini --output reports/gemini-provider-live.json
# 既存設定から指定のProviderキーだけを読み、実DeepSeekで検証できる。
python scripts/smoke-brain-provider.py --profile deepseek_flash --env-file .env --output reports/deepseek-provider-live.json
# Gemini側は429を注入、Fallback先は実DeepSeek。実Gemini成功とは扱わない。
python scripts/smoke-brain-provider.py --profile gemini --fallback-probe --env-file .env --output reports/gemini-deepseek-fallback-live.json
```

Mock/HTTP契約: 雑談、Read/連続Tool、複数Turn、native Tool署名の保持、確認Write/承認復元、再送、429/503/ネットワーク/タイムアウト、認証/権限エラー、未知の外部効果、同意撤回、local_only、Tool後切替禁止を確認。実Geminiの理解精度・native protocolのサービス側適合を証明するものではない。

関連pytest **121件成功**、Thread client Node **5件成功**、構文/差分検査成功。実Chromiumの1440/390pxでは合成ProviderでGemini診断表示、Tool保存、承認復元、同Thread履歴を確認した。既存のContextual agent runtime workflowへ新Providerテストを組み込み、重複workflowは作成していない。GitHub Actionsの最終結果はPRを参照。

最初の広いpytest実行では、worktreeに引き継がれた保存済みDeepSeek選択がキー未設定だったため、local前提の旧prefetchテスト1件が失敗した（他109件成功）。本番の保存済み選択を編集せず、`PETIT_MODEL_ROUTING_PATH`を新規の一時パスへ隔離して上記121件を確認した。

- [Gemini実接続記録](../reports/gemini-provider-live.json): **skipped、キー未設定**。
- [実DeepSeek](../reports/deepseek-provider-live.json): 合成の雑談→卒研PROGRESS参照Tool→次Turn、**3/3成功**。
- [Fallback試験](../reports/gemini-deepseek-fallback-live.json): 初回Gemini 429のみ注入→実DeepSeek、同じ合成3ケース、**3/3成功**。実際のproviderはdeepseekと記録。

本番DB/実Notion/既存会話全文は送信していない。実サービスWrite、配布Desktop/macOS/iPhone、Gemini実接続、アカウント残枠、CPUの定量比較は未確認。Notion PR #350のコードは変更していない。

## CLIを直接使う個人デモ（PETIT外・任意）

以下は公式CLIがインストール・本人認証済みの場合に、空の作業フォルダから本人が直接実行する手順。今回CLIがないため未実行。PETIT Providerには登録せず、Core/UI/Tool Registryからも起動しない。

```powershell
Get-Command agy
agy --version
# 空のテストフォルダで直接実行。秘密情報をプロンプトへ入れない。
agy -p 'Reply with exactly: OK. Do not read files, run commands, or use tools.' --output-format json
$LASTEXITCODE
# streamingの独立確認（上と別のリクエスト）
agy -p 'Reply with exactly: OK. Do not use tools.' --output-format stream-json
```

stderr/exit code/タイムアウト/Tool許可・usageの取得可否は、その公式版で別途確認する。非公開認証情報、アカウント切替、MCP proxyで制限を回避する方式は使わない。このデモの成功もPETIT Brain統合の完了とは区別する。
