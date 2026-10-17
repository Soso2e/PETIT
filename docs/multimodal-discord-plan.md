# Multimodal Intelligence / Discord 計画

調査: 2026-10-17。基準main: `8fc1c5e`（origin/main）。ローカルmainの未Pushタスク再開修正 `dc865fe` とstorageの既存ファイルは保持し、実装ブランチはorigin/mainから分離する。

## 現在地

| 項目 | 実装と不足 |
| --- | --- |
| Chat / Brain | `chat.py` → `agent.py` → `brain_runtime.py`。Core Prompt共通、通常1 Call / Read原則2 Call。入力は文字列のみ |
| Provider | `lmstudio_client.py` / `model_routing.py`。Chat/AgentのLM Studio・DeepSeek Flash/Pro切替あり。画像能力宣言、画像同意、添付契約なし |
| Context | Brokerはtasks/calendar/memory/brain/work/reminders/handoff、最大4 source・facts上限・部分失敗。GitHub/Projectは通常Broker未対応（#245/#246） |
| Project | alias、checkpoint、確認済source link、選択projectだけのsource refreshを再利用可能。候補の自動正式登録は禁止 |
| 会話 | SQLite会話、session、圧縮Conversation/Dialogue Stateあり。Thread/Turn/Event/永続Approval/Receiptは#303の目標設計。request_idだけでは二重実行を保証しない |
| Client | FastAPI Module Registry、Vanilla JS、Electron小型会話/作業画面、Web/PWAあり。Discordなし。Desktop独立historyの共通化は#304、管理Coreは#305 |

調査対象: AGENTS/Concept/README/PROGRESS/ASSISTANT_ARCHITECTURE、runtime-flows/jarvis-agent/desktop-foundation-design/modular_architecture、chat/brain_runtime/petit_prompt/capability_router/context_broker/agent_runtime/lmstudio_client/model_routing/conversation_state/dialogue_state/project_continuity/project_source_refresh/tools、frontend/app.js、Desktop conversation/chat-state、関連tests。BRAINの2026-07-08ローカルLLM構成は過去の候補であり、現在のProvider選択の正本にはしない。

## 採用する最小構造

`Client → 添付受付/入力正規化 → Vision Adapter → PETIT Brain → 必要時Context Broker → 回答`

Vision AdapterはOpenAI互換のcontent配列（text + image_url/data URL）を既存LLM Clientで送る。構造化された観測（文字/数値/表/画面/不明点）を画像IDに対応付け、考察とは分ける。画像内容を通常の命令文字列へ連結してagent.runへ渡さない。初期の画像経路はRead/回答専用とし、画像内の指示からToolやWriteを起動できない。文字だけの既存経路は維持する。

直接マルチモーダルBrainなら単純回答は1 Callにできるが、観測と計算/考察の分離、誤認識の検証、画像命令の権限制限、Contextへの接続を明確にするため、最初は抽出1 Call + 回答1 Callを選ぶ。同じProvider基盤を使い、新Agent/DB/人格は作らない。初期段階では高度なWrite依頼は画像なしの明示操作へ案内する。

## 添付・privacy契約

- 画像実体だけを受け取るbounded raw-body API。外部URL、パス、任意MIMEを信用しない。PNG/JPEG/WebPをdecode/verify、EXIF向き補正、メタデータ除去、画素/辺/byte/件数制限。アニメ画像は明示拒否。
- opaque添付IDをsessionへ束縛。取得/削除/会話参照で同じsessionを照合。保存はCoreの非公開storage、公開staticには置かない。24時間TTL、明示削除と起動時/受付時cleanup。元ファイルのdigestと正規化画像の対応を記録、元EXIF/ファイル名は保存しない。
- 外部画像送信は設定による明示許可がある場合だけ。既定OFF。DeepSeekは公式にVision対応するFlash IDだけ。Proや未知IDへ黙って画像送信しない。
- LM Studioは実際の選択モデルのVision capabilityを確認できる場合だけ。text-only/unknownは失敗として返し、text回答への偽装fallbackなし。
- 画像観測はuntrusted data。抽出内容に従って権限を追加せず、現行承認/risk/Task/Notion正本を保護。履歴への添付参照と観測保存はsessionを保ち、元画像を長期Memoryへ自動exportしない。

## フェーズ / PR / 依存

| PR | 単独で検証する縦切り | 依存・境界 |
| --- | --- | --- |
| 1 Vision MVP | upload → 添付ID → `/api/chat`画像単体/文字併用 → Flash観測 → PETIT自然回答、UI、削除/期限、安全性/回帰 | #235、#282は参照。Thread設計を実装済みと仮定しない |
| 2 Context | 数値の決定論的検証、Project候補検索、確認済sourceだけのbounded GitHub Read、過去/現在/取得時刻の分離 | #245を通常Broker GitHub/Project対応の正本、#246をProject境界の正本とする。全repo横断review/候補登録Toolは通常Readに転用しない |
| 3 Discord MVP | owner allowlist、slash `/petit`・`/analyze`、Core転送、defer/timeout、分割、二重event防止 | ローカルCoreへ認証接続。DMの個人専用から開始。#303未実装なら旧session adapterの制限を明示 |
| 4 Discord継続/UX | 明示再開、永続request照会、許可チャンネル画像投稿、client間continuity | #303/#304の永続契約に依存。別会話DBは作らない。Guildへの個人情報出力は既定禁止 |
| 5 評価/最適化 | 約20件の除秘Fixture、抽出/計算/根拠/検索/権限/障害/性能の結果記録 | 実Provider・実Discord受入とmock結果を分ける |

#301/#302/#303/#304/#305はいずれもopen。#302は既存UI復旧の実装が一部進んでいるがIssue完了とは扱わない。既存open PRは調査時0件。必要な新規IssueはVisionとDiscord・評価の未追跡範囲に限定する。

## 変更範囲 / 保護範囲

変更: 添付受付、Vision Adapter、既存LLMの能力検査/usage計測、Chat画像分岐、既存UIの添付導線、Module登録、関連tests/docs/Mermaid/進捗/版数。
維持: 文字Chat契約、Core人格、Task/Notion/Project正本、Write承認とAgent再開、既存Desktop配布/起動方式。全面Framework移行、一般マルチユーザー化、Thread設計の先取り実装、main自動mergeは行わない。

## 受入と計測

PR1必須: PNG/JPEG/WebP、画像単体/併用、形式偽装/破損/巨大/向き/件数、他session拒否、削除/TTL、同意OFFで外部送信0件、非Vision拒否、Provider timeout/空出力/不正JSONを失敗表示、画像命令からWrite 0件、従来Chat/承認回帰。実Flashは機密なし合成Fixtureのみ、画像送信許可が必要。

20ケース: Steam正常/CTR不一致/欠損/期間相違、Project一致/候補複数/見つからない/古いcache/外部失敗、ぼけ/回転/複数画像/命令注入、通常Chat/Task/Calendar/承認、Discord未許可/重複event、Provider切断。認識数値正答率、計算、根拠なし件数、Project検索、不要Tool、実LLM Call、時間、usage token、推定費用、Provider失敗、回帰を記録。未実行は数値0でなく未測定とする。

Steam基準: 23/720 = 3.1944…%、465/905 = 51.3812…%。表示51.7%との差は約0.319 percentage points。期間/分母/集計定義未確認で誤りや業界比の低さを断定しない。

## 公式仕様の確認先

- [DeepSeek Vision](https://api-docs.deepseek.com/guides/vision/): Flash、OpenAI互換画像block、実体形式検出。PETITはProvider上限より小さく制限する。
- [LM Studio Chat Completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)、[Model Info](https://lmstudio.ai/docs/python/model-info/get-model-info): 選択モデルのvision確認が必要。
- [Discord Gateway](https://docs.discord.com/developers/events/gateway)、[Application Commands](https://docs.discord.com/developers/interactions/application-commands): slash添付はMessage Content Intent不要。Guild通常投稿のcontent/attachmentsにはprivileged Intentが必要。DM例外があるが受信対象は明示制限する。

## PR1の実装・検証結果

#333、`feat/multimodal-vision` / v0.31.0。画像受付→Vision構造化→共通Brain回答、Web/小型Desktop/旧UIの添付導線を実装。Steamの2つの既知比率検証はPR1へ前倒しし、入力値が不明/重複なら計算しない。通常のTask/Project Actionは変更せず、画像経路はTool 0件。添付は1会話32MiB/32枚、Core全体256MiB/1024枚も上限とする。画像の実体はmetadata除去後だけを保存し、元画像との対応はdigest/寸法/形式/添付IDで保持する。

2026-10-17: 関連pytest125件+11 subtests成功、Desktop単体64件成功/1 skip（macOS限定）。隔離ChromeのWeb・Desktop小型会話HTML・旧UIで390/1440px、画像単体送信・失敗保持/再試行・プレビュー・削除・横はみ出しなしを確認。UI fixtureはProviderをmockし、Coreの画像受付/会話保存を隔離SQLiteで実行する。配布Electron/macOS/iPhone/PWA実機・実Flash/LM Studio精度・実Discordは未確認。

20件の受入セットと指標は [multimodal-acceptance.md](multimodal-acceptance.md)。実Provider送信の許可が未確認のため、クラウド設定は変更せず実API評価は行っていない。PR1はmainへ自動mergeせずレビューに渡す。次の最小縦切りは#245/#246のProject候補Readと確認済sourceのbounded GitHub Readであり、未実装Thread設計を前提にしない。Discord継続の永続性は#303/#304に依存する。
