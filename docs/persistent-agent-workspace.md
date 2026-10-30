# #368 Persistent Agent Workspace / compact tools

最新main 3620ea1とSDK撤去PR #369を基準とする。Coreの既存Thread/Turn/Memory/Approval/Receiptが正本で、Provider補助状態は同じSQLiteのprovider_sessionsテーブルだけに追加する。

## 実装範囲

- KEEP: 既存Core Loop、同意付きProvider順位、Registry、承認/冪等性/Receipt、LM Studio/DeepSeek、無効のAntigravity CLI/ACPゲート。
- REPLACE: Codexの毎Turn一時cwd/ephemeral Threadを、管理されたagent-workspaceと成功後に保存するProvider sessionへ。プロセスはTurnごとに終了し再利用しない。常駐化は実応答の比較後に判断。
- SIMPLIFY: 全Tool JSONの本文注入を廃止。小さな名前/risk一覧から同じBrainがdiscover_toolsで最大8名の完全schemaを取得。別Routerやキーワード意図判定を追加しない。
- FIX: get_weather/search_newsの公開漏れ。登録済みsafe_readかつ管理者・通常privacyで利用可能。場所は確認済み情報だけ使い、不明なら質問する。backgroundキューToolは公開しない。

Native APIの初期公開は頻出Read5個+Discovery。Discoveryで選んだ詳細は同じTurnの次Callに追加する（API方式は追加Callが必要になる場合がある）。CLIは既存dynamic PETIT bridgeで詳細schemaだけ返す。モデルが一覧から既知Toolを直接選んだ場合もCoreの公開集合・完全schemaで検証する。schemaの文章は切り詰めない。

Gmailは接続と保存token、Notion検索は既存キー、ローカル開発は既存の明示設定を確認して公開する。空の内部Task/予定を未設定として隠さない。外部tokenの実失効は実呼出時に確認する（毎Turnの追加ネットワーク認証を行わない）。

## Workspaceと履歴

PETIT設定領域配下のagent-workspaceへAGENTS.md/CONTEXT.mdだけを生成。本体コード、個人DB、秘密、BRAIN、実repoをコピーしない。ファイルをユーザーが変更した場合は上書きせずレビュー要求で停止する。Codexのproject_root_markersをAGENTS.mdに設定し、親repoの開発指示を自動注入しない。instructionSourcesが専用AGENTS.mdだけであることを検査し、非対応CLIではfail closed。

人格/原則はpetit_prompt.pyと既存brain.INSTRUCTIONSからAGENTSを生成する。Codex固有のdeveloperInstructionsはbridge/利用可能Capabilityのみ。API方式は既存system原則を使う。Workspace/Mapping/カタログはProvider非依存で、Codexプロトコルだけadapterへ残す。Claude等のadapter自体は未実装。

同じCore Thread・モデル・権限・公開条件・Web許可・Workspace指示・直前成功Turnが一致する場合だけthread/resumeを使い、Core履歴を二重送信しない。他ProviderやguestのTurn、失敗、取消、承認待ちで連続性を破棄。モデル変更後もCoreの保存文脈だけで再開する。補助rolloutが消えたときはthread/startへ復元する。再開試行前にMappingを無効化し、クラッシュ後に未完了のAgent履歴を再利用しない。DBの一対一対応/別Thread分離/再起動相当/欠損復元は合成RPCで検証、認証済み実CLIでの会話復元は未確認。

## Webと権限

SettingsのCodex Web検索はdisabled（既定）/cached/liveを明示選択。guestは無効、local_onlyはCodex自体を拒否。変更中は処理を止める。OS networkと検索の設定は別。shell/subagent/apps/pluginsは無効、read-only restricted rootsとCore bridgeの実行前再検査を維持する。子process所有には既存CLIブランチのJob Objectを再利用。

Web検索は外部へqueryを送信する。私的会話では無効にする必要がある。queryのDLP/リアルタイム承認や実検索のprompt injection耐性は未実装・未検証なので、通常利用の受入完了とは扱わない。

## 計測と残課題

reports/agent-workspace-validation.json参照。probeは一時DB・一時認証領域・合成挨拶だけを使用し、認証を借りずmodel turnを送信しない。実CLIでAGENTS読込と3種類のWeb設定の受理を確認。実検索成功ではない。

mainで同じRegistryを読み込んだ旧公開31 schemaは15,290文字、新方式初期6 schemaは3,021文字、別途一覧766文字。schemaだけの削減は約80%、一覧を含めると約75%。CLI instructionsは1,086文字だがWorkspace AGENTSとCodex標準system promptを含む総input量ではない。ユーザー報告の35 Tool/44.864秒をこの合成測定と同一条件として扱わない。

Turn EventにはPrompt/History/State/Alertsの文字数、API Call/Tool時間、取得できたtoken usageとreasoning_tokensを保存。プロンプト全文・引数・秘密を新しいmetricsへ保存しない。CLIはprocess startup・最初の本文delta・総時間を区別し、内蔵LLM Call数/token/Thinking時間はunknown。DB/UI返却時間の分離は未実装。

残り: 認証済みCodex/DeepSeekの同一シナリオ比較、p50/p95/TTFT/token/Tool成功率/自然さ/利用枠、Web検索queryのプライバシー検証、同一会話での実承認/再開、実端末。同期アラートの毎Turn末尾付加は維持し、表示頻度改善は別作業。Antigravity CLI許諾・本番接続を本PRで解除しない。

## 公式仕様

[App Server](https://learn.chatgpt.com/docs/app-server)、[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[Configuration Reference](https://learn.chatgpt.com/docs/config-file/config-reference)。2026-10-30確認。実CLI検証版は0.130.0-alpha.5。
