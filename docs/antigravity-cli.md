# Antigravity CLIと既存契約枠（#355 / #349）

## 2026-10-29の明示接続実装（#362、開発ブランチ）

利用者が非サポートの説明を受けた上で実装を明示依頼したため、Settingsで接続する選択式CLI Brainを追加した。これはGoogleによる許諾取得・規約適合の証明ではない。以下の#355段階の本番無効化記録は過去の判断として残す。

`backend/antigravity_cli_brain.py`は毎回空workspaceにfinish専用Agentを作り、公式agyへstdin NDJSONで文脈を渡す。CLIは返答またはPETIT Tool要求のJSONを返し、既存Core Loopがschema/risk/承認/receipt/再送を管理する。環境変数だけで有効にせず、SDK/ACPと別Providerとして扱う。APIキー/Coreの秘密値を子へ渡さず、認証tokenを抽出しない。cancel/timeout/出力上限/設定変更で所有CLIを止め、Windows Jobでその子processも終了する。

Settingsの「CLIへ接続・優先順位の先頭へ」→「接続テスト」→「CLIのみ」＋順位の会話利用ONを保存する。会話用モデルと開発Jobの実行CLIは独立して選べる。開発は[開発タスク設計](coding-tasks.md)を参照。

`scripts/smoke_antigravity_cli_brain.py --live --coding --output reports/antigravity-cli-brain-live.json`は本人の既存CLI認証で、合成DB/合成Gitのみを使用する。実CLIの会話・Read Tool・予定承認/再開/再送・コード変更・静的checkと元repository不変を確認した。実Codex推論、実プロジェクトの機能テスト、実WEVORA、iPhone/配布Desktop/Cloudは未確認。契約枠の由来・quota消費はunknownのまま。

## #355の直接検証段階の記録

目的は **PETIT → 未改変の公式agy → 本人のGoogleログイン → 既存Antigravity契約枠**。
SDK+LM Studio、SDK+Gemini API、Gemini API単独はこの目的の達成に含めない。

2026-10-25 UTCに `origin/main` の `65fd98a` を取得。#345/#349/#353と#351/#352を再確認した。
#352は既にmerged、#351はclosed/unmerged、#354のセットアップもmainへmergedだった。
今回それらをmergeしていない。手元のmain固有の未Pushコミット`dc865fe`、元checkoutの変更、storage/実DBを保持し、別worktreeの最新origin/mainから作業した。

WindowsではPATHと公式インストーラーの標準配置先にagyが見つからない。
Antigravityデスクトップアプリの存在はCLI導入・CLI認証の証拠にならない。
- 実機状況は `reports/antigravity-cli-direct.json` を参照。Windows公式agy 1.4.8で日本語JSON・同一会話NDJSON・合成README読取が成功。契約プランとの照合はunknownで、本番接続は無効を維持。
WEVORAの実ファイル、Google推論、macOS/iPhone/PWA/配布Desktop受入は未検証。

## 公式資料の矛盾と本番無効化

2026-10-25 UTCの公式資料を再取得した。技術仕様と利用許諾は分けて判断する。

- [Headless仕様](https://www.antigravity.google/docs/cli/headless/): `-p`、JSON/NDJSON、`--conversation`、stdin stream、Pythonからの起動を記載。
- [2026-10-07フォーラム回答](https://discuss.ai.google.dev/t/can-a-local-ai-coordinator-launch-the-official-antigravity-cli-with-subscription-sign-in/186246): 本人専用・公式バイナリ・stdio・認証情報を扱わないCoordinatorを許容すると説明。同じスレッドの10/19時点でもFAQとの矛盾について再質問があり、解消する回答は確認できなかった。
- [現行FAQ](https://www.antigravity.google/docs/faq): 直接スクリプト/CI用途と、個人プランで第三者アプリがCLIをラップする用途を分け、後者を非サポートとしている。
- [追加利用規約6条](https://www.antigravity.google/terms): 第三者ソフトによるサービスへのアクセスを制限する。本人専用PETIT/公式CLI subprocessへの明示的な例外は確認できない。

**許可を確定できない。** 規約違反と断定したり、フォーラム回答だけで許可済みにもしない。
ユーザー指示に従い、PETIT本番接続/テスト会話/順位追加はサーバー側で拒否する。
環境変数・設定UIで解除できるフラグを設けない。CLI指定が紛れ込んだ際もLM Studio等へ暗黙変更しない。
Googleへの問い合わせは未送信（以下を本人から確認するか、別途送信指示が必要）。

問い合わせ案:

1. 本人だけが使うFastAPI Coordinatorから、本人PCの公式agyを未改変で逐次起動し、promptとJSON出力のみをstdio経由で扱う形は、現行6条/FAQの例外として認められるか。10/7回答と現行FAQのどちらが適用されるか。
2. 同一本人のWeb/Desktop/iPhone PWAからlocalhostまたはTailscaleで操作する場合も同じ扱いか。一般公開・複数ユーザー・アカウント共有は行わない。
3. 公式CLIのみが認証/通信を扱い、PETITはOAuth/token/cookieを一切扱わない条件で、既存Pro/Ultra等の契約枠が適用されるか。追加credit/overageを使わず停止できる公式設定と、その確認方法は何か。
4. 低並列・利用制限時停止・明示会話IDによる継続・構造化出力のPETITへの保存は許容されるか。必要な事前許諾手続き/対象プランはあるか。
5. 上記条件を公式文書へ反映できるか、本人の構成に適用される書面回答を提供できるか。

## 実装した準備

- `backend/antigravity_cli.py`: bounded CLI検出、公式JSON/NDJSONの解析、エラー分類、token usageとquotaの分離。本番プロンプト実行コードを持たない。
- `replay_fixture`: **offline mock専用**。既存Thread/Turnの受付後、`antigravity_cli_mock_*` Eventsに対応付けと進捗を記録。新DB/schema/Brainは増設しない。同じrequestの再実行、Thread間ID共有、ID変更、壊れた/途切れた出力を拒否。セッションを既存DBから復元し、途中失敗は勝手に再送しない。
- Toolイベントは観測として扱う。PETIT Toolを再実行せず、raw引数/出力は保存しない。Mock記録は通常の`model_backend`や実行済みreceiptへ偽装しない。
- 管理者認証付きSettingsでCLI候補検出/未検証状態/公式手順を表示。診断APIはファイル存在確認のみ、ネットワーク・認証・モデル応答を実行しない。
- `scripts/probe_antigravity_cli.py`: 独立直接テスト用。既定は`--version`のみ、`--live`指定時だけ一時合成workspaceで挨拶→README→明示ID継続を逐次実行。APIキー用環境変数を子に渡さず、資格情報ストアを読まない。結果は観測した項目だけ記録し、契約枠・認証種別はunknownのまま。PETIT runtimeからimportしない。
- 同スクリプトはdeadline/取消時に所有プロセスツリーを終了し、出力を制限。stdout/stderrは一時ファイルで受け、rawエラーをレポートしない。

単一プロセスstdin streamingは将来の選択肢。初期は`--conversation <explicit ID>`で1 Turn/1プロセスが扱いやすい。
`--continue`は他Threadの直近会話を拾う危険があるため採用しない。
stdin streamではusage/num_turnsが累積になるため、単純合計しない。`control_request`で承認を横取りする方式は公式headless仕様で対応しておらず、PETIT Approval連携が成立したとは扱わない。

## ファイル権限と既存SDKの再利用

PR #352のThread/Turn/Events・Provider固定・取消/期限管理、#354の管理者認証/設定UIを再利用する。
SDKのAgent起動/LM Studio設定/ローカルモデルの実証はCLI認証・契約枠・CLI Tool証拠として流用しない。
既存`external_brain.tool_bridge`のRegistry/schema/risk/Approval/Receiptは将来のPETIT Tool用に維持するが、CLI内蔵Toolはそこを自動で通らない。

[Headless](https://www.antigravity.google/docs/cli/headless/)と[Permissions](https://www.antigravity.google/docs/cli/permissions)によると、workspace内の読取**と書込**は標準で許可されうる。
**cwd指定だけではRead専用・フォルダ境界・_private禁止を保証できない。** `--sandbox`だけで十分とも扱わない。
正式統合の前に、以下が必要:

- Settingsから許可ルートを明示選択。canonical pathを実行直前に再検査し、drive root/外側/リンク経由/`_private`を既定拒否。
- CLI公式permission設定を隔離し、既存のユーザーallowルールにより制限が広がらないことを確認。強制できない場合はread-only OS境界または公式に権限を限定できる実行方式を検証する。
- CLI内蔵read/write/shellとPETITの承認の責務を確定。観測イベントは実行**後**なので、イベント解析だけでは事前承認できない。write/delete/commandは許可しない。
- 文書に含まれる指示を信頼せず、promptへの注意書きだけで権限制御の代用にしない。`--dangerously-skip-permissions`、非公開API、credential抽出、account rotationは使用しない。

## Windows / macOSの導入と直接確認

[公式Get started](https://www.antigravity.google/docs/getting-started/)のCLIタブを本人が確認して導入する。
Windows PowerShellは公式`https://antigravity.google/cli/install.ps1`、macOSは公式`https://antigravity.google/cli/install.sh`の手順。
自動でインストーラーを実行しない。Windows標準先は`%LOCALAPPDATA%\agy\bin`、macOSは`~/.local/bin/agy`。PATH反映のため新しいターミナルを開く。

1. `agy --version`を確認。
2. 本人がターミナルで`agy`を起動し、公式画面でGoogleログインする。PETITへ認証情報を入力しない。契約内容とoverage/credit設定を公式画面で確認する。
3. 秘密情報のない合成workspaceで直接実行する:

```text
agy -p "こんにちは。日本語で返答してください。" --output-format json
agy -p "現在のフォルダのREADME.mdを読み、内容を要約してください。" --output-format stream-json
agy -p "前の内容の続きを説明してください。" --conversation <直前の明示conversation_id> --output-format json
```

再現用スクリプト（Windows/macOSとも、PETIT依存を入れたPython環境）:

```text
python scripts/probe_antigravity_cli.py --output reports/antigravity-cli-direct.json
python scripts/probe_antigravity_cli.py --live --output reports/antigravity-cli-direct-live.json
```

`--live`は本人の認証完了・直接CLI利用の確認後に合成データで実行。成功してもPETIT本番接続は有効にならない。
CLIのJSONにmodelがなければunknown。token数から契約枠残量や課金額を逆算しない。
APIキー不使用だけでは月額枠利用の証拠にならないため、公式アカウント/利用画面と照合する。

## 完了条件に残ること

Googleの規約許諾、サブスクリプション契約枠との対応・推論前後の残量差分、許可フォルダ/_privateのRead専用境界とPETIT Approval、実WEVORAおよびCoreへの実応答/Tool履歴保存、実429/認証切れ/CLI取消・deadline/Core復旧/並行/UI配信、macOS/iPhone/配布Desktopは未検証。
Googleの許諾とデータ境界が確定するまで、実WEVORA等の実文書をPETITからCLIへ送らない。
最終受入は実WEVORAのPROGRESS参照→`antigravity_cli`の実応答→実Tool履歴と回答のCore保存を照合し、LM Studio/Gemini API未使用を確認する。現在はこの受入に未達であり、#349/#355をcloseしない。


## 2026-10-27 Windows実機検証追記

- 公式インストーラー配下の `agy.exe` を直接起動し、バージョン `1.4.8` を確認。APIキー・APIトークン・Google Cloud/Vertex関連の認証環境変数を子プロセスから除いた状態で、日本語JSON会話が成功した。公式CLIの既存認証で推論できたが、アカウント識別情報や認証情報は読んでいない。
- `agy -p /model` は `gemini-4-argon-medium` を表示。各JSON応答にはモデル名が含まれなかったため、これはCLIが示す選択モデルであり、個々の応答のサーバー側モデル証明ではない。
- 同一の明示conversation IDで `stream-json` を再開し、NDJSONの6イベントと成功結果を確認。JSON/streamのtoken使用量はCLI値として記録し、契約枠の残量とは分けた。
- 公式 `/usage` はGemini 4 Argonの週次枠残量98%を表示し、`/credits` はAI Premium credits残高0を表示した。契約プラン名も呼出前後の差分も示されないため、既存の月額契約枠が今回の推論に使われたかは **unknown**。
- 一時フォルダに作成した合成READMEだけを `--mode=plan --sandbox` で読み取り、ランダムな検証文字列を応答から照合した。ストリーム上のToolは `read_file` 2回だけで、書込・削除・コマンド・補助AgentのTool実行は観測せず、ファイルの内容も不変だった。実WEVORA・PETIT DB・実スレッドは使用していない。
- 更新後の `scripts/probe_antigravity_cli.py --live` も実行し、挨拶・合成README読取・同一会話の継続が全て成功した。読取Toolは `read_file` のみで、許可外Toolは観測しなかった。この直接CLI実証はPETITへの統合実証ではない。Googleの規約/FAQとフォーラム回答の相違、許可フォルダ/_privateの強制境界、PETIT Approvalとの接続が残るため、本番起動は引き続き無効。429、認証切れ、CLI取消/timeout、Core保存、macOS/iPhone/配布Desktopも未確認。
- 詳細な構造化証跡: `reports/antigravity-cli-direct.json` と `reports/antigravity-cli-validation.json`。公式資料: [headless mode](https://www.antigravity.google/docs/cli/headless/)、[execution modes](https://www.antigravity.google/docs/cli/modes/)、[permissions](https://www.antigravity.google/docs/permissions?tab=cli)、[model quotas](https://www.antigravity.google/docs/cli/commands/usage/)、[AI credits](https://www.antigravity.google/docs/cli/commands/credits/)。
