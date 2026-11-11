# PROGRESS — 変更履歴

**Current Version: v0.56.1**

**Last Updated: 2026-11-11 UTC**

## 現在の状態 / 未確認・TODO（最新を上書き）

- 開発スレッド自動投影とNotion同期競合残骸解消・Uvicorn監視除外（v0.56.1）: チャットから起票された開発ジョブ（`propose_development_job`）を開発タブのスレッド階層（`coding_develop_threads`）へ自動投影し、リポジトリ名解決（`PersonalAssistant_PETIT`）に対応。Uvicornのファイル監視を `--reload-dir backend` に限定して作業領域clone時のホットリロード誤発動を防止。3ヶ月前の古いキュー残骸（`status='conflict'` 8件）を解決済みに落とし、Notion同期運用アラートの誤検知を解消。単体テスト追加・全件成功。実画面確認済み。

- #440 プティちゃんマスコット刷新（v0.56.0）: 梨＋土星の輪の新デザインをWeb/Desktop共通の軽量SVGモジュール（`frontend/mascot/`）に統一。表情18種・動作21種をレジストリ化し、会話（考え中/成功/確認待ち/エラー）・音声（聞き取り/発話）・入力中・無操作のおやすみに連動。Web（Universe）では操作を妨げずチャット欄の上を歩き、クリック/ドラッグ/カーソル追従に反応、Settingsで表示・大きさ・色・動きを変更（既定はデスクトップ幅でON、モバイルOFF）。Desktopは大きさ・色・動き・散歩（既定OFF）を設定可能。`desktop/mascot/` は複製で `npm run sync:mascot` で更新（テストで差分検出）。Windows/macOS実機の常駐負荷・散歩・実音声同期、モバイル実機は未確認。トレイ/メニューバー画像化とアプリアイコン差し替えは後続（`toStaticSVG` を用意）。

- #438 チャット応答のMarkdownレンダリング表示対応（v0.55.0）: PETITのチャットUI（universe.html / legacy.html / desktop/index.html）において、AIアシスタントの返答メッセージ（通常応答およびストリーミング応答）を安全にMarkdownレンダリングする共通モジュール（frontend/markdown.js、frontend/markdown.css）を新設。生HTMLのXSSエスケープ・javascript:リンクの無害化、見出し（h1〜h6）・太字・斜体・取り消し線・インラインコード・フェンスコードブロック（言語バッジ＋ワンクリックコピー）・タスクチェックボックス・引用・水平線・GFMテーブルを綺麗に装飾。ユーザー側のメッセージはプレーンテキストを維持し、Service Workerにも静的アセットを登録。Node契約テスト・単体テスト追加。実端末・実ブラウザでの描画確認は未完了。

- iPhone・モバイルWebAppでのチャット入力欄と下部タブ重なり解消（v0.54.4）: iPhoneなどのモバイルWebApp/Safariにおいてチャット入力欄と下部タブバーが重なって入力できない不具合を修正。通常時はセーフエリア（`env(safe-area-inset-bottom)`）とタブバーの実高さを考慮した十分な安全マージン（`--petit-bottom-nav-height`）を確保し、入力フォーカス時および仮想キーボード表示時（`window.visualViewport` / `petit-chat-input-focused` / `petit-keyboard-open`）は下部タブバーを画面外へ滑らかに退避させて入力欄をキーボード直上へ追従。回帰テスト追加。実iPhone端末（Safari/ホーム画面追加PWA）での手動受入は未完了。

- #436 Desktop E2E確認の改善（v0.54.3）: v0.54.2 のWin/Mac実Electron Smokeは初期挨拶を通過し、承認後の返答で完全一致のDOM検索が失敗した。回答者バッジ付きバブルでも返答本文を検出できるロケータへ変更し、失敗時に画面・fixture通信の診断を出力。任意のPRタイトル [desktop-smoke] に限り、タグ発行前にWin/Mac実Electron Smokeを実施する。既存タグは移動しない。実installer・実端末の検証は未完了。


- #434 Desktop Releaseの初期挨拶修正（v0.54.2）: 空履歴でも初期挨拶を消していたためMac/Windowsのスモークでタイムアウト。空履歴なら初期挨拶を保持、保存履歴・保留承認・履歴取得エラーでは削除する。回帰テスト追加。タグv0.54.1は移動せず、新バージョンで再リリース。実配布・実端末は未確認。


- #432 Desktop SVGマスコット（v0.54.1、開発PR）: Electronに初期OFFの小型透明マスコットを追加。位置保存/トレイ・設定切替/小型Chat起動、既存Wake・会話状態のアニメーション連動を実装。外部依存・サーバーAPI・音声処理は不変。Windows/macOS実機での常駐動作・マルチディスプレイ・負荷評価と、配布版の更新は未確認。

- #429 CLI自由度向上とリポジトリ・作業記録ツールの拡充（v0.54.0）: チャットからGitリポジトリを安全に追加する `add_coding_repository` Tool、重複・誤記録した作業セッションを削除する `delete_work_session` Tool と REST API（`DELETE /api/work-sessions/{id}`）を追加。Front Brain からの一般作業委譲（`delegations.ELIGIBLE`）に `antigravity_cli` を追加し、`FRONT_DIRECT` へ両Toolを登録。新規単体テスト8件、関連テスト52件全件成功。実CLI（Antigravity CLI）での通し会話は受入確認が必要。

- PR #421/#422/#425 統合: モバイルChat入力欄と下部ナビの重なりを解消（4タブ維持、キーボード追従）、Development Activityの数値Job IDだけを安全にコピー、PETITの口調を女性の個人秘書（一人称「私」）に変更。Nocord統合のv0.53.0を維持し、旧3タブ固定テストを4タブ期待へ更新。実スマホ端末での操作検証は未実施。

- Nocord統合・Discord Knowledge Gateway（v0.53.0、PR #424）: Nocord-BotのDiscordログ収集・FTS5/trigram全文検索・添付ファイルテキスト抽出（PDF/Markdown/テキスト/JSON等）をPETITへ統合。Personal/Guild ZoneのDB保存先・検索先不一致を解消し、Owner指定サーバー/DMはPersonal Zone、他サーバーは自ギルドZoneに厳格分離。Guild内非公開チャンネルの閲覧権限認可（`permitted_channels`フィルタ）により一般ユーザーへの機密漏洩を防止。プライベートスレッドは親チャンネル許可を継承せず明示登録のみ許可する安全境界を徹底。Bot側にSQLite永続化キューを備えた `ArchiveBuffer` を導入し、Bot強制終了・再起動時も未送信イベントを欠落させず自動復旧・再送。破損・巨大PDF（最大50ページ制限、最大10万文字制限、例外シールド、セマフォ同時2件、10秒タイムアウト）によるBot停止・会話遅延を完全防御。メッセージ編集の即時反映（`on_message_edit`）、チャンネル登録解除時の即時除外、`/petit archive sync` を完備。全入口共通の安全な新Tool `search_discord_archive`、Nocord元DBからの無損失移行スクリプト `scripts/migrate_nocord.py` を実装。関連pytest 51件全件成功。実Discord Gateway接続・実PDF抽出環境は未確認。

- #418 開発ルート統合（v0.52.0）: Chat の開始確認と Develop の直接送信を同じ Coding Job 台帳へ接続。UI フォルダ登録、モデル・Effort と残量選択、Git の専用ブランチでの編集・検査・commit、PC の Everything IPC／走査・scratch コピー・元ファイル操作の承認、Claude 認証 UI と Codex 既存認証を実装。Windows の実 Codex Sol／Antigravity Argon・Flash で合成 Tool 往復、利用枠と Everything IPC、Claude の未ログイン状態を確認。合成 HTTP と Chromium で Develop からの直接送信・差分、Chat の提案カード復元・承認を確認。Claude の OAuth 完了・実 Opus 推論、実 DeepSeek の意図判定、実端末は未確認。Git のテスト・ビルドは信頼済みリポジトリのコードをホストで実行する。
- #418 検証: 関連 pytest 225件、Node 契約テスト11件が成功。Windows の広範囲 pytest には別機能の失敗が残り、旧 API・パス表記等の19件は変更前の `origin/main` でも再現した。

- #414 設定UI・AI/サービス接続・接続ステータスの再設計と統合（v0.51.0）: 通常Settingsタブ最上部に「現在の接続状態とショートカット（AI Brain順位・カレンダー同期元・Notion/Gmail・接続ステータス診断）」ハブを配置し、画面/音声/通知設定と外部接続設定の役割を明確に分離。`/static/setup.html` に常設ステータス概要バー・状態/保存済みバッジ（`利用可能`/`接続済み`/`🔑 キー保存済み`）・2カラム整理・冗長な注意事項や旧SDK/実験ACPの折りたたみ（`<details>`）・TimeTree/Googleカード内でカレンダー同期元切替と手動同期を1クリック完結する導線・ハッシュ直通移動（`#ai`/`#notion`/`#timetree`/`#google`/`#sync`）を追加。接続ステータスダイアログにも色分けピルと各設定セクションへの直通リンクを追加。単体テストとPlaywright実ブラウザ（1440/390/320px）で確認済み。実アカウント（TimeTree/Notion/Google OAuth/実CLI）での手動受入と実スマホ端末は未確認。

- #411 Front Brain と CLI 委譲（v0.50.0、既定 OFF の試験機能）: 設定のトグルで DeepSeek を最初の担当にし、複数ステップの作業を作業用 Thread の Turn として CLI（既定 Claude Code → Codex、Claude は Sonnet / Haiku）に任せる。開始は確認なしで、返答末尾とチャット上部に表示する。単体テストと合成 Provider の実ブラウザ操作は確認済み。**実 CLI での通しは未確認**（この PC の `claude` は v2.1.126 で `--restricted` 未対応かつ未ログイン。`claude update` と `claude login` が必要）。DeepSeek の振り分け精度の評価も未実施。次: 実 CLI での確認、`docs/brain/front-brain-delegation.md` §7 の評価。既存の失敗: `tests/test_claude_agent.py` と `tests/test_home_files.py` の計3件は Windows のテスト側の文字コード（cp932）の問題で、main でも落ちる。

- #410 会話Turn進捗・応答ドラフトのストリーミング表示（v0.50.0）: 実行中Turnの表示専用・揮発の進捗ハブ（`turn_stream.py`）とSSEエンドポイント（`GET /api/turns/{request_id}/stream`）を追加。OpenAI互換API Brain（LM Studio / DeepSeek）では `stream=True` で本文deltaを受信しドラフト表示、Toolラウンド・Brain Fallback時は途中ドラフトを破棄。CLI Brainは構造化応答検証後に使うためフェーズ表示のみ。確定結果・承認・effect receipt・保存は従来どおり `/api/chat` / `/api/turns/{id}` の台帳を正とする。Web / Desktop / Universe の「考え中…」バブルを進捗・ドラフトでリアルタイム更新。実LM Studio / DeepSeekでのストリーム推論・実端末表示は未確認。

- #408 過去作業時間記録と開発者モード回答者表示（v0.49.0）: 過去作業時間を遡及登録できる新Tool `record_past_work`（`duration_minutes`, `task`, `started_at`, `ended_at`）とREST API（`/api/work-sessions/record`）を追加し、日別・期間集計（`today_summary`, `period_summary`）へ即時反映。開発者モードON時にメッセージ吹き出しへ回答者バッジ（`🧠 Provider (Model)`）を常時表示し、クリックで詳細を展開できるように改善。履歴復元（`/api/conversations`）時に `turns.result_json` から `model_route` を復元してリロード後も回答者情報を保持。単体・UI契約テスト追加。実端末での表示・実Provider推論は未確認。

- #393 Univ 3Dカメラ入力（v0.48.4、#394）: OrbitControlsを自前の `createCameraController` に置き換え、ジェスチャーに属する指だけでカメラを動かす（2本目の指がHUDに乗っても振動しない）、ピンチ後に残った指は全指が離れるまで無効、軽い追従スムージングと短い慣性、タップ判定をカメラ入力側へ統合。WebGL表示中に見えない旧DOMボタン（`univ-space.css` の `pointer-events: auto`）がスマホで3Dビューの約15%を覆い、ドラッグ不発・何もない所のタップで近くのタスクが選択される原因だったため子孫も無効化。ラベルは見えている文字だけを当たりにした。#391（v0.45.1）のリサイズ時の巻き戻し修正はマージ済み。Playwright（Chromium・タッチエミュレーション）で確認、iPhone/Android実機は未確認。

- Development Job UI回帰修正（v0.48.3、#390、mainマージ済み）: 既存Coding Jobsの詳細がstatus/イベント番号不変でも更新されるようsummary/error/checks/workspace/branchを描画差分判定へ追加。Claude Code CLIをAntigravity CLIと誤表示しないよう修正。SQLite・Brain・Worker・承認は変更なし。静的回帰契約テスト追加。Windows実画面は未確認。

- #372 Activity状態フィルター（v0.48.2、#395、mainマージ済み）: 既存SQLite Activityの最新取得結果を画面上で「すべて／待機・実行中／失敗／完了」に絞り込めるようにした。切替時に再通信せず、30秒自動更新・管理者API・秘密本文非表示を維持。実Windows/iPhone受入は未確認。

- #372 Activity鮮度表示（v0.48.1、#406、mainマージ済み）: Development Hubの背景Activityに最終取得日時を表示し、通信失敗時に前回成功時刻と取得失敗を区別する。SQLiteのジョブ状態を稼働保証と誤認しない。Brain/Worker/認証は変更なし。Windows/iPhone実機は未確認。

- v0.48.0（PR #407）、v0.47.0（PR #405）、v0.46.0（PR #402）は main にマージ済み。H5（v0.47.0）: Home ファイル Tool（list/read/search/write/edit、Hook と同じ線、`.git` は読取も拒否）を全 Brain に公開し、Codex エージェントモード（cwd=Home、shell なし）を追加（#404）。未確認: 実 Codex / agy。D3（v0.48.0、Discord Guild モード、#403）。

- 再設計 H1 + D1（v0.46.0、`claude/ai-redesign-discord-bot-h0xlft`・未マージ）: 人格の正本を PETIT Home（`~/PETIT-Home` / `PETIT_HOME`）へ移し全Brainで共有、人格変更は Core 計算の差分を確認カードで承認（#396）。Discord Bot Owner モード MVP を別プロセスで追加、owner 判定は Core（#397）。未確認: 実 Discord 接続、Desktop の確認カードでの差分表示、Home の場所の設定UI。H2: PETIT Tool の MCP bridge（#398、実 Claude Code CLI の接続確認済み）、D2: Discord の承認ボタンと通知 DM（#399）も同じブランチに追加。H3: Claude Code エージェントモード（#400、設定で ON のときだけ。cwd=Home・--restricted・MCP・L0〜L3 Hook・--resume・承認後の再開。実 CLI で通し確認済み、Bash はサンドボックス依存がある環境でのみ・未確認）。H4: worktree での開発（#401、`petit/` ブランチへの push は確認なし・PR は承認・main への push は禁止。実 CLI で worktree→テスト→commit→push→PR 提案まで確認、GitHub での PR 実作成は未確認）。次: D3（Guild モードの土台）、または H5（Codex / Antigravity CLI の追従）。

- #391 Univ 3Dカメラ操作（v0.45.1、PR中）: リサイズ（スマホのアドレスバー出入り・レール開閉）やタスク構成変更のたびに `resetCamera()` が走り、ドラッグ回転・ピンチ拡縮した視点が全体表示へ巻き戻っていた。ユーザーがカメラを動かした後と操作中は自動フィットしない（明示リセットで解除）。操作中は自動Tweenを止める。Playwright（Chromium・モバイルエミュレーション）で確認、iPhone/Android実機は未確認。

- 旧キーワードルーティング撤去（v0.45.0、`refactor/remove-legacy-routing`、PR #386の上に積んだPR・未マージ）: 画像付き会話を `vision_reply.py`（Read専用1 Call、挙動同じ）へ移し、本番から到達不能になった21モジュール（agent / agent_legacy / agent_runtime / brain_runtime / capability_router / context_broker / model_router / dialogue_resolution / project_router / project_resume / project_source_refresh / task_completion(_intent) / task_work_intent / task_conversation / list_conversation / date_parser / recall / agent_state / agent_progress / tools.agent_actions）と比較PoC 2本を削除。DB tableは削除していない（agent_run_states等は残る）。プロジェクト再開時の外部source自動更新やNotion明示検索などの決定論的処理は#345以降すでに通常会話から使われておらず、今回コードを削除した（Brain+Toolで扱う）。旧図は docs/archive/runtime-flows-legacy-routing.md。frontend/app.js の agent_progress 表示分岐は未使用のまま残っている。実端末での画像会話・プロジェクト再開の受入は未確認。

- Claude Code CLI Executor（v0.44.0、`feat/claude-code-executor`、docs/unify-directionを含む・未マージ）: Concept §4のExecutor 3番目として公式`claude`を会話Brain・Coding Jobに接続（明示接続のみ、組込みTool/MCP/設定読込なし、APIキー非継承、JSON Schemaで判断だけ受取）。既定の優先順位をAntigravity CLI→Codex→Claude Code→DeepSeekへ。CLI BrainがdiscoverをToolとして要求すると失敗していた不具合を修正。Linkraft撤去漏れで/api/connectionsがImportErrorになっていた不具合を修正。朝ブリーフィングを初回Tool集合へ追加。実CLI（開発コンテナ）で雑談・Read・承認付き予定保存を確認。Windows/macOS実端末・本人ログイン・契約上の扱いは未確認。詳細 docs/brain/claude-code-cli.md。既存の失敗テスト51件（旧ルーティング系、base同数）は未対応。削除候補（旧キーワードルーティング・ACP等）は判断待ち。

- 文書統一 Step 1（`docs/unify-direction`、未マージ）: Concept.mdをCLI中心方針（Router=DeepSeek任意 / Executor=Antigravity CLI＞Codex＞Claude Code(予定)＞DeepSeek）の北極星として書き直し、旧全文は docs/archive/concept-legacy.md へ。docs/architecture.md（現行概要と目標との差）と docs/README.md（一覧・配置ルール）を新設し、docs を分野別フォルダへ移動。CLAUDE.mdはAGENTS.mdへの入口に縮小。次: Step 2 Issue再編（ラベル付与・epic統合・新規Issue）。このPCに gh が無いため導入・認証が必要。Router/Executor分離、Claude Code順位、アカウント範囲、Antigravity規約は未決定（Concept §10）。

- #372 Activity live refresh (v0.43.0開発PR): Development Hub表示中かつタブ可視時のみ30秒間隔でSQLiteの保存済みJob状態を再取得。Codex等は別一覧と明記、永続Read調査を区別。新DB・Worker・Brain変更なし。実端末と実Providerの進捗反映は未検証。

- #382 (v0.42.1開発PR): Desktop Wake/音声会話中の無発話待機を8秒→20秒に変更し、無音終了時はSTTを呼ばずoverlayを閉じて既存Wake待機を再開。手動マイクの8秒、発話後1.2秒、確認待ち/半二重方式は維持。音声回帰テスト追加。実Wakeモデル・実マイク・長時間稼働の受入は未確認。

- #372 P0 Durable Read Task（v0.42.0開発PR）: ニュース/天気の管理者依頼のみ、既存jobsのlease・fencing・冪等性・Read専用再起動復旧・取消・通知イベントを追加。通常会話と別Workerで処理。旧background_research/agent_followup、Coding Job、承認済みデータを変更しない。実Provider/実Windows・iPhone/PC停止中の実行/汎用Web調査や自律計画は未検証・未実装。docs/durable-read-tasks.md参照。テスト結果はPRに記録する。

- v0.41.0 Chat-first UI/Dashboard: Chatを初期画面にし、Chat / Univ / Develop / Dashboardの4領域ナビに整理。スマホ下部4タブ、Desktopの共通画面にも適用。Dashboardは既存work_sessionsの90日集計APIで活動カレンダー・直近7日/30日・活動日数を追加。Three.jsと既存CLI Jobs、DB/承認機構は不変。Developの継続開発Thread/司令塔UIとDesktop二画面同期は後続。GitHub PRのJS/CIと実Win/iPhone受入は区別する。docs/ui-chat-first-dashboard.md参照。


- #372 Coding Job Activity統合（v0.40.0）: coding_jobsの状態を機密本文なしの認証済みGET /api/coding/activityで表示し、Development HubのActivityへ通常jobsと並列表示。未初期化の場合はテーブル/DBバックアップを生成しない。作成・承認・キャンセル・完了は既存Coding UIのまま。実行中はDB記録でありプロセス生存保証なし。永続Job復旧・実端末受入・実Codex推論は未検証。


- #362 / #225 CLI Brain・Coding Job統合（v0.39.0、実機会話の利用者確認あり）: PR #371のAntigravity CLI専用Brain、モデル一覧、CLI-only接続、承認付きCoding Job、開発タスク画面を最新mainのDevelopment Hub/Activityと統合。公式agyの推論1件、旧PR CI7件を確認。CLI規約の適用範囲、実Codex推論、開発Jobの実行品質、配布端末のUI、再起動復旧は未確認。Coding Jobは既存jobs Activityとは別正本であり統合表示は今後の課題。ユーザーの会話性能テストは変更しない。


- #372 Activity最小実装（v0.38.0）: 既存jobs SQLiteのqueued/running/done/failedを認証済みGET /api/activity/jobsで確認できるようにし、Development Hubへ結果プレビューを持たない一覧を追加。通知配信ACKを変更せず、失敗例外・input/result本文を公開しない。runningはDB上の請求状態で稼働保証なし。Coding Jobs（PR #371）は未統合。再起動回復、lease、ジョブ受付、通知・実端末テストは次段。Python/Nodeの回帰テスト追加。

- #372 Development Hub read-only 初段（v0.37.0）: Chat/Tasks/Univの既存導線を壊さず、開発パネルをナビ・検索パレットに追加。明示許可したローカルGitの観測キャッシュからブランチ・HEAD・変更・直近コミット・文書の存在を表示し、stale/disabledを区別。ファイル本文・秘密・任意パス・Git fetchは扱わない。Node契約テスト追加。実Windows/iPhoneおよび実ローカルrepoでの表示は未検証。次は永続バックグラウンドJobとCodex等の開発セッションを結び、Activityへ進捗表示する。

- #368 Workspace/Tool公開（実装済み・実モデル未確認）: Codexの専用AGENTS読込、Core DBへの補助Thread保存/resume/履歴重送防止、権限/モデル/途中失敗時の分離、別会話とのThread ID衝突拒否、欠損復元、Webの明示許可を実装。通常Brainへ天気/newsを公開、未設定サービスを除外し小さなindex/詳細schema発見へ変更。実CLI0.130.0-alpha.5で専用AGENTSと3検索mode設定受理を確認（未認証・推論/検索なし）。関連pytest95件・Thread Node5件・Chromium1440/390px成功（合成Provider）。合成31schema 15,290文字→初期6schema 3,021文字+index766文字。実応答p50/p95/枠/自然さはunknown。docs/persistent-agent-workspace.mdと測定report参照。

- #368 SDK撤去（実装済み・契約テスト確認）: SDK専用Brain/Worker/依存・導入スクリプトを撤去し、Codexが使う共通validator/Provider照合/プロセス停止をprovider_runtimeへ移動。旧SDK設定・秘密・DBを保持し再選択必須、新規接続禁止。78件成功、Thread Node5件・Chromium1440/390pxの設定/再起動受入成功（合成Provider）。Workspace/永続Thread/動的Tool公開は別PRで実装（本節の#368 Workspace/Tool公開を参照）。実会話の性能比較は後続。実Provider・配布端末は未確認。詳細はdocs/sdk-retirement.md。

- #366 セキュリティ/回帰修正（PR上で確認中）: 誤削除された petit-version.js の起動・遅延ロードを復旧。公開APIを /api/chat に限定し、ゲスト会話はHttpOnlyのpetit_guest Cookieから独立Threadを導出して管理者/他ゲストの履歴を分離。未認証SDK経路はTool全禁止、承認再開では管理者権限Contextを復元。DBをセッション真実源とし、プロセスを跨ぐログアウトを反映。既存テストの新しい認証境界への追従とゲストAPIアクセス拒否の回帰テストを追加。GitHub CI完了待ち、未ログインUIでの履歴/再取得・Discord等のサービス認証経路は実機受入が必要。

- #365 / v0.35.0 管理者セッションDB永続化と非管理者向け安全な会話モード（実装済み・単体テスト完了）: 管理者セッションをSQLite（admin_sessions）に保存し、サーバー再起動やリロードによるセッション喪失を解消（1年間有効）。UI設定から管理者セッションの終了（ログアウト）を可能にし、非管理者状態でもチャット（/api/chat）を許可。非管理者時はTool全般を禁止して純粋なテキスト応答のみに制限（コード変更や副作用操作を防止）。関連テスト23件成功。次は実画面でのログイン・ログアウト受入。

- #357 ACP初回導入（PR #358 main反映済み・本番Brain未接続）: 公式ACP Agentの検証付き導入、ACP initialize、oauth-personal設定UI/APIを追加。Windows実Agentのinitializeと認証方式広告を確認。OAuth、モデル応答、契約枠、PETIT Thread/Turn/Receipt接続、Session復元、OS隔離、実フォルダ読取は未確認または未実装。通常会話・実フォルダ・Terminal・backgroundは無効のまま。次は本人操作のOAuth、Windows隔離の実証、既存Core/Approvalとの接続を分けて受入する。既存agy CLI経路は変更なし。

- #355 / #349（当時の直接検証記録。v0.39.0で明示接続経路を追加）: Windowsの公式agy 1.4.8を使い、APIキー環境変数を除いて日本語JSON会話、同一conversation IDのNDJSON継続、/model、/usage、/creditsを実測。gemini-4-argon-medium、Gemini 4 Argon週次枠98%残、AI Premium credits残高0を確認したが、契約プランと呼出ごとの枠消費はunknown。plan+sandbox/request-reviewで一時READMEのみread_file読取、検証文字列を確認し、書込/削除/コマンド/subagentなし・ファイル不変。GoogleアカウントID、規約許諾、PETIT Core保存、実WEVORA、429/認証切れ/取消、macOS/実端末は未確認。docs/antigravity-cli.mdとreports/antigravity-cli-direct.jsonを参照。

- #353 / PR #354（main統合済み・外部認証受入未確認）: PR #352のSDKを再利用し、管理者認証付き初回ウィザード、暗号化ホスト設定、AI順位と同意付きFallback、Codex公式app-server、Google共通OAuth/Gmail Read Tool、Notion対象選択、Calendar 02:00 JST差分同期、永続アラートと会話警告を追加。Python121件+8 subtests成功/1 skip、Desktop66件成功/1 skip・Thread Node5件、Chromium1440/390pxを確認。公式SDK+実LM StudioでRead/記憶Write/予定承認/再送/再起動/未認証Codex→SDKのFallbackを合成DBで確認し、承認引数・receipt・保存行を照合。初期の依存競合・小型モデルのTool未呼出/誤成功発言も検出し、最終は明示bridge契約プロンプトで成功。自然文の一般的な実行品質、本人のCodex/課金API/Notion/Google/TimeTree認証、実02:00/Push/Cloud/配布端末は未検証。Google双方向・Tool後のProvider間継続・画像順位Fallbackは未実装。次は利用者による実接続受入。設計/制約はdocs/setup-integrations.md、証跡要約はreports/setup-integrations-validation.json。

- #349 / PR #352（main統合済み・SDK/ローカル推論の実証、CLI契約枠は未達）: feat/renaissance-antigravity-sdkで公式SDK 0.1.22のAgent Loopを選択式バックエンドへ接続。既定はloopback LM Studio。限定Read bridgeのschema/risk検査、Turn専用Workerの取消/deadline/Provider固定、既存Thread/Turn/Events/履歴を再利用。実SDK+Qwen3.5-9Bの会話→get_tasks→次Turn、独立SDKのstream/保存再開、実Core再送/復旧/timeout/取消、実Chromium 1440/390pxのWeb/Desktop source adapterを確認。関連pytest81件+5 subtests・Node5件成功。Write/画像/配布Desktop/macOS/実サービス受入、SDK+Gemini（キーなし）は未確認。個人契約CLIラップは現行FAQで非サポート、agy未導入。PR #351は未採用・未マージ、Notionコード/本番設定/実DBは不変。SDKの証拠をCLIの完成と扱わず、次は#355の許諾/CLI直接検証と実端末受入。詳細: docs/antigravity-brain-poc.md。

- #345 / #341（確認済みProjectフォルダ、実装済み・実データ受入未確認）: 既存project_source_linksへlocal_workspace対応を確認付きで保存し、既存get_local_development_status(project_id)からWorkspaceObserverのキャッシュを取得。Task.project_idと同じIDを使い、同名フォルダはcanonical rootのIDで区別する。allowlist/実行時再検査/private/symlink・junction拒否、文書更新日時・出典・観測時刻・実Git状態を分離。34件の関連テストを一時Git/DBで確認。Core #346・記憶検索 #347と結合済み。関連pytest154件+3 subtests、Node4件、Chrome 1440/390pxと実DeepSeek Flash・合成7ケース（7/7）を確認。実登録フォルダ・実Discord/Notion・配布端末の受入は別途。
- #345（元発言検索・記憶鮮度、実装済み・実機未確認）: 既存conversationsの入力/出力を日時・発言元・Thread・原文ID付きでbounded検索するToolを追加。旧NULL sessionは推測で結合しない。save_memoryは固定保存上限を設けず、正規化重複・明示置換・期限・visibilityをSQLiteで扱い、旧行を保持。private元発言/記憶をstandard検索から除外し、private検索ではembeddingを呼ばない。全件再索引を個別索引更新へ縮小。Core PR #346を取り込み、単一Brainへ接続済み。#346 → #347 → #348の順でレビューする（全PRのbaseはmain、main未マージ）。
- #345 / #303（実装済み・実機未確認）: 単一native Brain Tool Loop、永続Thread/Turn/承認/receipt、既存chat/画像/作業開始接続と明示Thread切替を追加。本文は既存conversations、旧session/ID/データを維持し、初回追加schema前にSQLiteバックアップを作成。旧ルーティングは本番text/Worker経路から除外。旧agent_legacy.run・Taskの重複登録・idle自動分割・fetch差替えを撤去。再送/並行/ロールバック/承認再開/ローカル専用の隔離検証を実施。後続#347/#348との結合状態で実DeepSeek Flash・合成7ケースのTool実行と保存結果を確認（7/7、初期6/7の失敗記録も保持）。実Providerの一般的な理解精度、実Notion/Discord、配布Desktop/iPhoneは未確認。新会話契約はdocs/renaissance-core.md。次は3 PRのレビューと実データ受入、Discord本人確認/配信adapter。

- #341（main統合候補・実機未確認）: Opt-in既存workspace観測に、登録GitルートのHEAD・local branch/commit・tracking比較とConcept/PROGRESS/README限定抜粋を追加。キャッシュ参照のsafe_read Toolを会話Capabilityへ登録。フォルダ・コマンド・ファイル取得はallowlist/固定名のread-only、fresh/staleと未確認文書を区別。コード単体テストを追加したが、実Windows/macOS PC上の観測と実LLM/iPhone/PWA会話は未確認。後続はソースコード部分読取・内部Project IDとの明示紐付け・追加UI。統合済みv0.31.0との回帰と実Windows/macOS/iPhoneの受入はIssue #343で追跡。


- #333 / v0.31.0（実装済み・実Provider未確認）: 安全なPNG/JPEG/WebP添付受付、会話IDに束縛したopaque ID、向き/解像度/形式/件数/容量検査、24時間TTLと削除、DeepSeek Flash Vision観測→共通Brain回答のRead専用経路を追加。画像・認識内容のクラウド送信は設定による明示許可がある場合だけ（既定OFF）。LM Studioは選択モデルのvision能力を実照会できる場合だけ。Steamの既知比率はDecimalで検証。Web/小型Desktop/旧UIの添付・失敗保持・再試行・削除を隔離Chromeで390/1440px確認。関連Core pytest125件+11 subtests、Desktop単体64件成功/1 skip。実DeepSeek/LM Studio画像精度・実Discord・配布版/macOS/PWA実機は未確認。画像Project/GitHub照合は#245/#246、共通Thread/Turnは#303/#304が後続。計画: docs/multimodal-discord-plan.md、20件の受入設計: docs/multimodal-acceptance.md。ローカルmainの未Push修正dc865feと既存storageは保持。

- #338（調査・隔離PoC、本番未移行）: DeepSeek中心で意図/文脈/Tool/複数工程を判断し、Pythonは権限/検証/承認/状態/冪等性/結果保証を担う方針をConcept/Architectureへ明記。#337の安全機能と公開PRは保持。実DeepSeek Flashの合成12ケース×3方式で、実行/停止条件は現行11/12・直接12/12・Discovery12/12、Call合計26/23/30、誤Write試行0/5ずつ。直接方式には引用文翻訳の失敗、Discoveryのpilotには雑談3 Callがあり、一般的な優位性・本番移行の条件は未達。既存61 Toolの全件公開は内部承認Toolを含むため不採用。詳細は docs/ai-first-agent-design.md、結果は reports/ai-first-evaluation.json。次は小さな直接公開集合でnative protocolと既存Pending/承認/結果契約を接続する設計・未調整ケース評価。汎用MCP接続、実データ操作、61 Tool選択精度、実Desktopは未確認。

- #335 / v0.30.3（実装済み・実モデル未確認）: Session開始の失敗会話を5テストで先に再現し、既存Dialogue/Brain/Registry/Agentを接続。stable ID・TTL付き失敗再試行、保存結果照合、active/paused再利用、同時開始の原子性、Context→Actionの条件付き継続、未実行/失敗の誤成功防止を追加。通常雑談1 Call・明示Session操作0 Call、Broker Read専用・既存承認を維持。隔離HTTPと関連自動テスト、Vision差分を重ねた回帰を検証。実LM Studioは接続不可、実Notion/配布Desktop/実モデル応答時間は未確認。変更前origin/mainでも失敗する旧テスト5件は#336で追跡。feat/multimodal-vision・既存storage・ローカルmainの未Push作業は保持。詳細: docs/conversation-action-reliability.md。次は実モデル受入、Task以外の永続Action契約は#303で後続。PR/CI結果はGitHubを正とする。

- #329 / PR #330 / v0.30.2（配布・OS通知実機未確認）: Desktop OS通知音の明示ON（既定無音）と、通知表示要求/show/failed診断を追加。Native通知の寿命保持・既存Web PushとDesktop権限の分離を維持。CI全テストは成功、Desktop関連の単体65件・Backend通知関連17件成功、隔離通知専用smoke成功。一方、全体smokeには音声確認ボタン・統計画面のtimeoutと入力文字列不一致による失敗が残るため、全体E2E成功とは扱わない。Mac/WindowsのOS通知受信・実音・Focus・正式配布DMGインストールは未確認。診断は `docs/desktop-notification-diagnostics.md`。

- #325 / PR #326 / v0.30.1（実TimeTree未確認）: Context Brokerから予定検索queryを渡し、TimeTree予定キャッシュの題名・説明・場所を検索。CAPCOM/カプコン別名、未来優先・無条件全履歴検索の抑止を追加。関連CI通過後にmain反映。実TimeTree・実LLM会話と非公開Sona CoreのE2Eは未確認。

- PR #331 / v0.30.0（CI確認中・実機受入未確認）: Univ Three.js遠景星を恒星色・大小表現へ変更し、WebGLと旧CSSカメラのポインター干渉を抑制。通知センターをSettingsからRemindersへ移動し回帰テストを追加。最終コミットの星点サイズ10は実画面/スマホで視認性・負荷の確認が必要。Desktop通知のPR #330、TimeTree検索のPR #326は別途統合・検証対象。

- #327 / feat/v29: 接続ステータスを上部同期表示・Settings・PCサイドバーへ追加。保存済み診断と同期履歴を表示し、接続確認だけを明示実行する。Notion対象別の再試行・既存競合UIを共用し、ライブ同期hookと競合採用の共有トランザクション不整合も修正。Backend関連53件・UI関連63件/31サブテスト・Frontend17件・Desktop62件成功。隔離Braveで1440/390/320pxと実UniverseのSettings/サイドバー導線、単一再試行・競合採用・部分障害・フォーカス復元を確認。実サービスの再試行/採用・実iPhone/PWA/配布Desktopは未確認。Push/PR/main反映は未実施。詳細は `docs/connection-status.md`。

- #321 / v0.28.0（配布版受入未確認）: v27実操作UX課題を改善。Tasks再クリック/Enterで惑星詳細、WebGL選択とHUD同期、閲覧/編集切替・上部の作業開始・子追加の開閉、固定バー/HUDとスクロールの調整、期限の識別・作業なしの開始導線・競合対象名、音声説明の設定集約を実装。統計は日別内訳/振り返り保存を追加し、Coreの既存集計を共用。新規SQLite表とrevision一致のトランザクションで上書きを防ぎ、未保存の入力と失敗案内を保持。Desktopの同一文書内切替でreadyを失う不具合も修正。Python80件・Frontend17件・Desktop61件成功（macOS限定1件skip）、隔離実Electronの390px/960px・日別保存/409/下書き・9秒経過後の継続と既存復旧/WebGLを確認。実WebのTasks→惑星詳細/HUDと期限表示、稼働APIの今日/過去日を読取確認。実データへの変更・同期競合採用は未実施。多天体/長いラベルの配置、macOS/実iPhone/PWA/配布版/実音声/LLMの受入は残る。詳細は `docs/desktop-v28-ux.md`。関連PRのCI・main反映状態はGitHubを正とする。配布更新と実端末受入は別途。

- v27実操作UX調査: 調査結果は `docs/v27-ux-followup.md`。#321で操作導線を改善し、残る多天体/長いラベルの配置と実端末受入は後続。個人情報を含む画像はローカル保管。v0.27.0の変更はPR #320でmain反映済み。

- #319 / PR #320（main反映済み）: Desktop/Web共通の「統計」タブを追加。今日の合計・セッション数・タスク数・最長、7日間の棒グラフ、今日のタスク別内訳・作業記録を表示する。既存CoreのJST/休憩/日境界集計を使用し、API/DB形式は維持。表示中30秒更新、非表示の取得停止、15秒の待機上限、部分失敗時の前回表示明記、記録なし表示を実装。関連Python57件・Frontend17件・Desktop60件成功（macOS限定1件skip）。隔離実Electronのデスクトップ/390pxで値・割合・JST・記録なし・部分失敗・再試行・ナビと既存動作を確認。稼働APIの今日/7日集計と日別総和一致、競合1件を読み取り確認。競合解決は差分比較とPETIT/Notion明示採用・revision/二重操作ガードが実装済みで回帰成功、実競合への書込みと親404の解消は行っていない。実端末/macOS/実iPhone/PWA/配布版受入は未確認。詳細は `docs/work-statistics.md`。次は実記録で統計の見やすさを確認する。PR #320でmain反映済み。配布版の受入は未確認。

- #318 / PR #320（main反映済み）: 小窓の惑星を削除。作業セッションを上部固定の短い表示と詳細開閉へ集約し、左メニューとの重なりを解消。Chatは会話だけの1列スクロールと常駐入力へ変更。CURRENT CONTEXTとクイック質問はHTML/更新処理から削除し、PWAキャッシュも更新。音声設定を折りたたみ、狭い画面の補助ボタン重なりも修正。Univは惑星本体・周囲の光と他惑星の減光で作業対象を強調し、ミドル/Alt+Middleを平行移動へ変更。Python関連81件、Frontend 17件、Desktop 60件成功（macOS限定1件skip）。隔離実ElectronでWebGL発光/一時停止解除、カメラ移動、長い会話、入力/上部固定、Task/Chat切替、詳細開閉、下書き保持、960px/390px、既存会話/承認/復旧を確認。実データの見た目・操作感、配布版/macOS、実iPhone/PWAキーボードは未確認。PR #320でmain反映済み。配布版の受入は未確認。詳細は `docs/desktop-v27-experience.md`。次はDesktop作業画面を再読込して実タスクで操作感を確認する。

- #316 / Fix/v26: 横のタブバーをUniv初期72px、hover/focus時232pxの一時展開へ変更。矢印で固定/解除し端末へ保存、明示縮小は他ビューでも維持。Web/Desktop共通CSSとPWAキャッシュへ反映。Frontend 17件・関連Python 25件、隔離ElectronでUnivの位置/サイズ不変、キーボード・固定復元・reduced motion・960px/390px表示を確認。実端末の操作感は未確認。未公開v0.26.0へ含め、Desktop本体の再ビルドは不要。

- #315 / Fix/v26（未公開）: Windows更新のサイズ/SHA-256検証・進捗、作業星の強調、IME/Enter長押し/入力復元、Notion競合の差分比較と明示採用、VAPID不要のDesktop通知・ホバーで残る声かけを実装。画面切替後のWorkspace IPC拒否も修正。Desktop 60件成功・macOS限定1件skip、Frontend 17件、Python関連53件成功。Windows x64 NSIS生成・新しい同梱resource確認済み（未署名）。プロジェクトvenvへ不足していたpywebpushを導入し、稼働中APIの依存利用可能とpip checkを確認。実Notionの親404は未解消、実Push/OS通知受信・旧配布版からの更新・実音声・3D発光の実機受入は未確認。通知の音声割込み・25分間隔は後続設計。詳細は `docs/desktop-v26-experience.md`。Push/PR/Releaseは未実施。

- 同期競合（2026-10-12 / 解消 2026-10-13）: 親ページ「音楽活動」のNotion 404に対し、NotionタスクDBへ「音楽活動」を新規再作成して新external_idを発行。子タスク「あなたといたい」の親RelationをNotionへ正常同期。誤ステータス"Mid"で400エラーとなっていた「dotsテスト」もstatus='Yet'へ修正・同期完了し、未解消の同期エラーは全件解消。更新前DBバックアップを作成済み。

- #311 / v0.25.5: PETITは個人利用に限定し、Apple Developer契約・公証を利用しない方針を確定。タグpush時のmacOSはad-hoc署名で、afterSign/DMG内部の署名・リソース一致検証を必須とする。Windows EXEは従来通り、手動Actionsはdevelopment名を維持。v0.25.2タグは動かさない。手動Actionsもタグrefではdevelopment用DMGを重複生成しないよう分岐。未公証DMGはGatekeeperで通常起動が拒否され得るため、v0.25.4タグのWindows npm testはCRLF改行を固定LFで検査する回帰テスト2件が原因で失敗（Mac DMGビルド成功）。v0.25.5でテストの改行正規化とCRLF回帰を追加。VERSION更新とマージメッセージ`[desktop-release]`の組合せでのみタグ作成・リリースを起動するオプトイン導線も追加（手動実行は維持）。v0.25.5のWindows/macOS Release assetをAPIで確認（2026-10-13）。実機受入・更新通知は未完了。


- #309: macOS v0.24.0の署名不整合は旧workflowによる署名スキップが原因。ad-hoc署名・署名直後/DMG完成後の検証・内容一致チェックを追加済み。Safari取得した未公証DMGはGatekeeperで通常起動拒否。今後Apple公証を行わない方針（#311）で、個人端末でのインストールと更新受入は未完了。詳細は`docs/macos-distribution.md`。

- #301 / v0.25.1: DesktopをPCの主入口として、Core正本のThread/Turn/Events・永続承認/結果照会、共通画面状態、ローカルCore管理、下書きのCore/thread/view別保存、起動/復旧/配布を一体設計。`docs/desktop-foundation-design.md` に現行との差分・目標API/所有権・6段階の依存/完了条件を固定。A #302から実装し、B #303、C #304、D #305、E #306、F #307で追跡。設計のみで新API/管理Coreは未実装。Conceptの目的と既存Domain/情報源/承認境界を維持し、過去Web中心設計との優先関係を明記。

- #299 / v0.25.0: 小型会話からアプリ内ワークスペースへ移動し、同梱復旧画面で接続失敗とrenderer停止を区別。小型下書き/送信中文章の保持、待機上限と中断、位置保持、非表示取得休止を追加。Desktop 52件・Frontend 17件・Python UI 25件、隔離実Electronの会話/承認/合成音声/クラッシュ復旧/下書き/非表示を確認。Windows x64開発installer生成・同梱リソース検証済み（未署名）。実インストール、実LLM/マイク、長時間常駐、macOSは未確認。完成条件と次の受入は `docs/desktop-readiness.md`。Backend同梱・端末間会話統合・自然な発話割込みは後続。

- #297: Univ以外のTask Detailを選択タスクからサーバーWork Sessionの対象へ切替。作業なし/終了時は空表示、一時停止中は対象を保持し、自由入力や未取得Taskは作業名だけ表示。ビュー切替・復元・ポーリングへ追従し、Univの選択詳細は維持。関連27テストと隔離ブラウザで確認、実サービス/配布版は未確認。

- #296: 共通の仕上げCSSでWeb / 小型Desktopの配色・文字・余白・境界を統一し、スマホのタスク切替と空一覧の文字潰れ、状態表示の重複を修正。隔離ブラウザで320px / 390px / 1440px、タスク有無・Chat・Settingsテーマ切替・Universe・Desktop HTMLを確認。配布Electron / 実iPhoneキーボード / 実音声・外部サービスは未確認。PR #298でmain反映済み。

- #294: session別SQLite Dialogue Stateにstable Task focus・last action・TTL付き確認所有権を追加。確認回答と短期照応をProject/Brainより先に解決し、成功Task Toolの共通hookで更新。9 Acceptance Criteriaと既存回帰を自動確認、隔離した実アプリ/ブラウザで「ゲーム開発→その子にWEVORA」をと再起動後の同じWEVORA期限更新を確認。Notion未同期親の既存制約を維持し、実Notion同期・配布Desktop/音声会話は未確認。Frontend history互換を維持、次はBackend threadイベント正本への段階移行。

- #292: 会話履歴の復元を自動音声対象外に明示し、Wake直後や遅延復元でも過去の返答を読まず、過去user表示が現在のTTSを停止しない。新規応答/手動再生は維持。実会話は未確認。

- Voice Conversation MVP (#273/#286/#288/#290): Wake→録音→STT→既存Brain/Broker→短文方針→TTS→次録音を接続し、マイク準備/再生待機の上限と遅延結果の破棄を追加。実モデル配布・実マイク/実声/誤起動・実LLM/STT/AivisSpeechの会話品質・Windows/macOS/iPhone受入は未確認。次は `docs/desktop.md` の人間による受入手順。発話による自動割り込みとWake直後の先頭音声引継ぎはMVP後の拡張。

- #288: 連続音声会話のChatリクエストにvoiceモードを付与し、Brainの初回応答・Broker後の応答・Deep Agentへ1〜3文の返答方針を渡す。通常テキスト会話・履歴・承認は維持。実LLMの短さ・自然さは未確認。

- #286: DesktopのWake/音声会話ボタンからSTT→共有Chat/Brain/Broker→TTS→次の録音を接続。返答と再生の両完了を待ち、無音・エラー・非表示・終了・確認付き操作では自動録音を停止。実声/実マイク/OS/iPhone/会話自然さは未確認。

- #273: 未保存のONNX選択を自動設定へ渡すよう修正。Windows/macOS実マイク受入は未確認。

- Issue #284: TimeTree exporterのRequestsがWindows管理ルートを参照できず認証前にTLS検証で失敗していた。子プロセス専用CAへOS信頼ルートを含め、明示CA設定は維持。実同期で1,221件取得・キャッシュ更新・stale=falseを確認（2026-09-30 06:13 UTC）。旧external_syncのNotionテスト1件はAPI不一致で失敗、TimeTreeとは別問題。

- Issue #281: Windows版PETITのDeepSeek接続は、httpx既定CAでWindows管理ルートを参照できず `CERTIFICATE_VERIFY_FAILED` になっていた。DeepSeek通信だけOS信頼ストアを使う検証済みSSLContextへ変更し、FlashモデルIDを`deepseek-flash`へ更新。対象6テスト、Python構文、実DeepSeekのChat/Agent、実FastAPI `/api/chat` で動作確認済み。`pytest`は`.venv`に未導入で実行不可、広範囲の旧`test_assistant_context.py`には今回と無関係な既存失敗が残る。

- Issue #279: Three.js Univのタスク状態更新をシームレス化。完了成功時は対象天体を縮小・減光してから更新し、残存天体は更新前のワールド座標から新配置へ補間する。新規天体は既存登場演出を利用し、Tween中のみ描画。reduced-motion / lite modeでは即時反映。コード・回帰テスト追加済み、実WebGL・実iPhone/macOS性能は未確認。


- Issue #276 / v0.22.0: PETITをローカルAIワークスペースとして再構成。デスクトップ幅では適応型サイドバー、状態・バージョン表示、検索兼コマンドパレット（Ctrl/Cmd+K）、設定ショートカット（Ctrl/Cmd+,）を提供し、狭い幅では既存の四隅ナビゲーションへ戻す。Web/小型Desktopの色・余白・文字・境界・Focus/Loading/Error/Empty/Disabled状態をモノトーンの共通トークンへ統一。Codex内ブラウザの390px/デスクトップ幅、キーボード操作、実Electron fixture smokeで確認済み。配布済みWindows/macOSアプリ、実iPhone/PWA、スクリーンリーダー、実LLM/外部サービスは未確認。

- Desktop v0.21.0 Release: Desktop Release本体とWakeモデル配布を分離。`PETIT_WAKE_MODEL_URL` / `PETIT_WAKE_MODEL_SHA256` がどちらも未設定なら、`wake-model.json` に `included=false` を明示したモデルなしinstallerを正常生成する。URLまたはSHAのどちらかが設定された場合はWakeモデル配布を有効扱いにし、HTTPS・SHA-256検証を必須化するため、半端な設定やSHA不一致はbuild失敗のまま。GitHub Actions Run #90でモデル未同梱のmacOS arm64 DMG / Windows x64 EXEを実生成し、両OSともnpm test・Smoke・installer build・packaged Wake resources・Artifact upload成功。`VERSION`は0.21.0へ同期済み。`.github/workflows/desktop-release.yml` に、mainのversion整合確認→annotated tag作成/再利用→tag refでDesktop Release workflow起動までを1回の手動Actionsで行う導線を追加。`v0.21.0`タグをrelease準備済みmain（`9b6a517`）へ作成し、Desktop Release Run #92でtest・macOS arm64・Windows x64・GitHub Release作成が全て成功。`PETIT-0.21.0-mac-arm64.dmg` / `PETIT-0.21.0-win-x64.exe` をReleaseへ添付済み。macOSは署名資格情報未設定のため個人利用向け未署名DMG。

- Issue #270 Step 3: Desktop openWakeWordのinstaller配布経路を実装。WakeモデルはGit管理外のまま、build時にローカル`storage/wakeword/models/v0.1/hey_petit.onnx`または`PETIT_WAKE_MODEL_URL` + `PETIT_WAKE_MODEL_SHA256`から注入でき、HTTPS・SHA-256検証、`wake-model.json` manifest同梱、packaged resources検証を行う。Wakeモデル配布が未設定でもDesktop Release本体は成立する。未完了は、Wakeを配布する場合の実モデル配布元、インストール版の自動設定→diagnostic、実マイクWake `ready`、実声「Hey プティ」検出と誤起動評価。

- Issue #270 Step 2: Desktop設定にopenWakeWordの「ウェイク環境を自動設定」を追加。Python 3検出→専用venv作成→依存導入→openWakeWord v0.5.1 backbone取得→既存/生成済み`hey_petit.onnx`を管理領域へコピー→マイクを開かないdiagnosticまで一括実行し、managed Python/runtime/model/backboneパスを設定へ保存する。中止・進捗表示・回帰テスト・Python runtime構文チェックを追加。Desktop CIでnpm test・Syntax checks成功。packaged配布経路はStep 3で実装済み。実モデル配布・実マイク`ready`・実声評価は未完了。

- Issue #270 Step 1: Desktop Wake設定をopenWakeWordへ一本化。旧Picovoice/Porcupine AccessKey・PPN・自動生成IPC・暗号化キー保存を撤去し、旧設定を読み込んだ場合も秘密情報と旧モデルmetadataを自動除去する。WakeはONNX分類モデル＋melspectrogram/embedding backbone＋Python runtimeのみを使用。Desktop CIでnpm test・Syntax checks成功。

- Issue #260追加: Three.js Univに天体の登場・選択拡大・発光パルスを実装。実WebGL fixtureで登場・選択・連続選択・reduced motion・描画停止を確認し、関連13テスト成功。大量実データ・実iPhone/macOS性能は未確認。詳細は `docs/universe-motion.md`。

- Issue #260: Web（Universe / Legacy）とDesktop小型会話に共通のメッセージ出現・押下・入力フォーカス・パネル表示アニメーション、Desktop設定の表示・操作反応と録音中の軌道表現を追加。Edgeの1280px / 390px幅と実Electronのfixture smokeで表示・操作・reduced-motionを確認済み。既存PWAからの更新、実iPhone / macOS、配布済みDesktopへの反映は未確認。設定画面CSSの配布にはDesktop更新が必要。

- Issue #255: 現行WebチャットのDOMと音声初期化の不一致を修正。録音→Whisper互換STT、入力方式選択、HTTPS・Mac権限・サービス設定の案内、失敗時の下書き復元を追加。実マイク・実STT・Safari・PWA更新受け入れは未確認。

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- Proactive openerの古い全体エピソード参照を停止し、同一sessionのユーザー発話と現在の作業だけを候補に変更。誤ったepisode_id=2（「全10件のタスクがキャンセル済み」）をSQLite/Chromaから削除し、DBバックアップを保存。関連テスト成功、実アプリ起動・実LLM表示は未確認。

- Issue #258: `scripts/wakeword/` にWindows/Python 3.13の独立したopenWakeWord学習環境を追加。日本語SAPI合成624クリップを話者分離して学習し、`storage/wakeword/models/v0.1/hey_petit.onnx` を生成済み。ONNX構造・出力一致・openWakeWord実推論・関連2テスト・依存整合・構文を確認。しきい値0.45でtest正例12/12検出、負例11/144誤検出。合成音声のみの実験モデルで、常時待機の実用精度は未達。実声・長時間負例・実マイク評価とDesktop統合が次の作業。詳細は `docs/openwakeword.md`。Desktop実行経路はopenWakeWordへ移行済み。

- Issue #253: Windows/macOS向けElectron Desktopの初期実装。既存Webの会話・確認・TTSを共有する小型UI、トレイ・ショートカット、openWakeWordウェイク、Whisper互換STT、GitHub Releases更新通知を追加。Desktop配布はPR=テスト、手動Actions=macOS arm64/Windows x64開発Artifact、version一致`v*`タグ=両OSbuild＋GitHub Release自動添付。macOS署名資格情報がない場合は個人利用向け未署名DMGへfallbackする。一般配布向け署名・公証、実更新、実マイク/モデル/LLM/TTSの受入は未確認。iPhoneはPWAを継続。

- Issue #249 / #245: Web中心のJARVIS設計を `docs/jarvis-agent.md` に整理。BrokerへMemory/BRAIN/Work/Reminders/Handoff、待ち時間・同時実行・Context量の上限、2回目Brainへの状況継続を追加。PC観測は既定無効の任意Module。作業ブランチで関連58テスト・Python構文・diff確認済み。実LLM・外部サービス・PWA E2E、Conversation State統合、永続提案・自律実行は未完了。

- プロダクトの軸は `PETIT_AS_JARVIS`。FastAPIとPWAを基盤に、タスク・予定・会話・知識・開発状況を継続支援する個人用アシスタントとして開発中。
- バージョン管理: v0.22.0。`main`反映時にSemantic Versioning形式で更新し、PROGRESSとWeb UIへ明記する。
- Univ UI 刷新: 大きなカード矩形を全廃し、Core＝中心惑星、親タスク＝惑星、子タスク＝衛星、関係性＝軌道・接続線からなる天体UIへ根本刷新。詳細情報は天体選択時に右側詳細パネルで確認・操作する。
- Univ描画: WebGL依存を追加せず、CSS 3D・radial-gradient・既存SVG接続線で軽量な球体表現を実装。レイヤーは前面HUD、選択対象の説明、惑星・衛星、接続線、背景の順で固定する。
- Issue #215対応: Univ表示時だけページを固定し、100dvhとsafe-area内のThree.js viewportへ切り替える。WebGL成功時はCSS宇宙背景を隠し、Canvasを単一の背景描画面として扱う。星の初回クリックでカメラFocusとHUD選択を同期し、2回目で詳細を開く（PC・390x844ブラウザ確認済み、実iPhone未確認）。
- バージョン管理: v0.18.1。Univの常時WebGL描画を必要時描画へ変更し、PWA全体のメインスレッド負荷を軽減。
- バージョン管理: v0.18.2。四隅型App Shellで非表示になった旧左レールの予約幅を解除し、デスクトップUnivを全幅表示へ復旧。
- バージョン管理: v0.18.3。FastAPIのstartup/shutdownとChroma初期同期を `backend/lifecycle.py` へ分離し、`main.py` はlifecycle登録のみを担当。
- バージョン管理: v0.18.4。Pending Actionの状態管理・確認API・Sona Core分岐・Tool dispatchを `backend/pending_actions.py` へ分離し、Chat/確認APIモデルを `backend/chat_models.py` へ共通化。
- バージョン管理: v0.18.5。`POST /api/chat`、Agent実行、observability、会話保存・artifact保存を `backend/chat.py` へ分離し、`main.py` はChat Router登録のみを担当。iOS Vocal ShortcutもChat moduleへ直接接続。
- バージョン管理: v0.18.6。Issue #227 Phase 2を完了。補助API群とStatic Frontend配線まで `backend/main.py` から分離し、`main.py` はFastAPI生成・Router登録・lifecycle/frontend登録・起動のみを担当するComposition Rootになった。
- バージョン管理: v0.19.0。Issue #227 Phase 3を開始。`ModuleDefinition` / `ModuleRegistry` と `create_app()` を追加し、Router・registrar・依存関係を明示的に組み立てる土台へ移行。`main.py` は `create_app()` を呼ぶ起動shimへ縮小。
- バージョン管理: v0.19.1。Issue #227 Phase 3を完了。`backend.tools` のimport副作用登録を廃止し、built-in Tool catalogを `builtin-tools` Moduleとして明示登録。Chat / Pending ActionはTool bootstrapへの依存を宣言し、Module Registryが起動順を保証する。
- Univ UI 刷新: 大きなカード矩形UIを全廃し、Core＝中心惑星、親タスク＝惑星、子タスク＝衛星、関係性＝軌道・接続線からなる天体UIへ根本刷新。詳細情報は天体選択時に右側詳細パネルで確認・操作する。
- Univ描画: Three.js WebGLを主描画としてCore・親Task・子Task・接続線・星背景を描画し、DOMはラベル・HUD・詳細・操作UIに限定。WebGL利用不可時のみ既存CSS 3D表示へフォールバックする。
- Univ表示領域: Univ表示中はページスクロールを止め、Canvasを100dvhの固定空間として表示。WebGL準備後は外側のCSS宇宙背景を無効化し、スマホHUDはsafe-areaと下部ナビを避ける。
- Univ Focus: 親タスク惑星または子タスク衛星を選ぶと、同じUniv内でカメラが対象系へ寄り、所属する衛星を見やすくする。他の惑星と接続線は暗くし、旧Focusパネルへ自動遷移しない。
- Front UI: 左上に現在領域・同期状態・バージョン、右上にUniv／Tasks／PETITの3アイコン、左下にReminders／Settingsを置く四隅型App Shellへ更新。スマホでは主要タブをアイコンだけにし、safe-areaを考慮する。
- 補助導線: Settingsから詳細設定を備えた旧UIへ直接移動できる。旧UIは廃止せず、移行中の保険・全機能への導線として残す。
- ナビゲーション: 対象パネルの`hidden`・ARIA・active状態を直接同期する。`home`、`focus`、`universe`、`projects`の旧URL／内部呼び出しはUnivへ互換転送する。
- モーション: View間は既存の短いフェードを維持し、Univ内部だけCSS 3Dカメラを利用する。`prefers-reduced-motion`では空間アニメーションとパネル遷移を停止する。
- 制作伴走 / Today: 作業セッションをNotion Task DBの変更なしでPETIT内部Task IDへ紐づけ、状態遷移イベントをSQLiteへ永続化する。20分ごとの継続確認と無応答時の自動停止、タスク別・プロジェクト別・直近1〜90日集計、チャットからの開始・一時停止・再開・終了・実績参照に対応。Today機能自体は残し、トップレベルタブからは外す。
- Issue #223対応: active / paused Work Sessionを通常会話の小さい状況文脈へ追加し、Tool routeを増やさず脱線後も現在作業を認識可能にする。proactive openerは古いproject memoryより実セッションを優先（関連自動テスト済み、実LM Studio未確認）。
- Issue #235対応中: PETIT人格をCore Promptへ一本化し、通常会話1 Call、Tasks / CalendarのReadを `Brain -> Context Broker -> Brain` の原則2 Callで処理する最小縦切りを実装。Read sourceは並列取得し、AI向けfactsへ正規化する。実LM Studio・実Notion/Calendar・latency/token比較は未確認。
- 会話 / Agent Runtime: Tool不要の会話はPETIT Brainの最初のLLM回答で終了し、Tasks / CalendarのReadだけ不足する場合はContext Brokerへ進む。書き込み・複雑処理は既存Agent Tool Loopを維持する。Issue #274で、明示されたタスク作成・変更・完了・親子変更・同期再試行を可逆な`low_risk_write`として同じターン内に実行するよう変更。話題提示や対象曖昧時は書き込まず、予定追加・BRAIN編集・外部紐付け・破壊的操作の確認境界は維持する（関連自動テスト済み、実LLM会話E2E未確認）。
- Prompt / 時刻: PETITの人格・会話原則を共通Core Promptへ統合。動的日時はsystem promptへ常時結合せず、相対日付・時刻を含むターンだけuser側へ必要な精度で注入する。
- 音声: AivisSpeech Engine経由のWAV再生、ブラウザTTS fallback、再試行、直列化、モバイル音声アンロックを実装。実PC／iPhone E2Eは未確認。
- Notionタスク復旧: Tasks画面の明示Notion同期、失敗同期の再試行、競合時の再編集案内を追加。実Notion接続・実ブラウザ操作は未確認。
- へいプティ音声入口（仮実装）: Issue #218 / `feat/petit-vocal-shortcut-prototype` で、iOS Vocal Shortcuts + Appleショートカットから `POST /api/voice` へ音声認識済みテキストを渡し、既存 `/api/chat` へ委譲する導線を追加。PWA自身では常時マイク監視せず、タスクの明示操作は即時実行、確認対象の別操作は既存フローを維持する。実iPhone E2Eは未確認。
- Web Push通知: Service Worker、Push API、VAPID、購読／解除API、カテゴリ別opt-in、通知履歴を実装。cache名をv0.14.1へ更新し、Univ空間と四隅App Shellの資産をprecacheへ追加。
- タスク管理: Notionを外部正本、SQLiteをPETITの即時統合ビューとして扱う。通常取得はHigh優先。ユーザーが作成・変更・完了・親子変更・同期再試行を明示した場合は追加確認なしでSQLiteへ反映し、Notion同期キューへ送る。対象が曖昧な場合は書き込まない。
- Project Continuity: 内部project台帳、alias、source link、checkpoint、handoff、cache-first resumeを統合済み。
- LM Studio: 同一PCの `127.0.0.1:1234/v1/models` は応答済みだが、実環境設定と会話E2Eは継続確認が必要。
- Windows起動導線: `scripts/start-petit-tailscale.ps1` で起動モード選択、Tailscale接続、`.venv` のPETIT起動、`/api/health`確認、管理者権限付きTailscale Serve、ブラウザ起動まで実行する。LM Studioは事前起動が必要。
- 今回の検証: Context Broker単体・Brain routeの回帰テストを追加。GitHub Actions / pytest / 実LM Studio E2Eは未確認。
- 次にやること: v0.22.0のUIを配布版Windows/macOSと実iPhone/PWAで受入確認し、キーボード・スクリーンリーダーの実機検証を行う。並行してWakeはIssue #270で実モデル配布・自動設定diagnostic・実マイク`ready`・実声/誤起動評価を継続し、その後Issue #235の実LM Studio検証へ戻る。

## 履歴

変更を加えるたびに1行追記する（追記専用・既存行は触らない）。時刻は UTC。

| 日付 | 時間 | 回数 | 変更内容 |
|------|------|------|----------|
| 2026-09-10 | 16:42 | #conflict-resolution | origin/mainへfast-forward後、未コミット変更を復帰。競合マーカーなし。対象テストはvenvにpytestがなく未実行。 |
| 2026-08-02 | 08:54 | #1 | v0.1.0としてバージョン管理ルール、PROGRESS表記、Web UI表示を追加 |
| 2026-08-02 | 09:12 | #2 | v0.1.1としてAgent Runtimeと会話ToolフローのMermaid図、AGENTS同期ルールを追加 |
| 2026-08-02 | 09:40 | #3 | v0.2.0としてToday画面、今日の作業時間集計、作業セッション復元APIを追加 |
| 2026-08-02 | 13:22 | #4 | v0.3.0としてLife星座マップとFocusへのProject・Task導線を追加 |
| 2026-08-02 | 14:25 | #5 | v0.3.1として親子タスク変更のTool選択、承認前引数検証、重複確認防止を追加 |
| 2026-08-02 | 14:29 | #6 | v0.4.0としてLifeホーム化、Focusズーム遷移、Today改善、親Task内の小タスク追加を実装 |
| 2026-08-02 | 16:07 | #7 | v0.5.0として全子タスク周回Focus、CSS球体、親移動処理一本化と冪等化を実装（PC・390x844ブラウザ動作確認済み、実Notion書込・実iPhone PWA未確認） |
| 2026-08-02 | 16:32 | #8 | 詳細表示と親子移動のタスクIDを同期し、別タスク操作時に「LiTのデザイン実装」が移動する取り違えを修正（実Notion書込未確認） |
| 2026-08-02 | 18:41 | #9 | v0.5.1としてTaskの2段階Focus、親変更の明示適用、モバイルLife間隔を改善（PC・390x844ブラウザ動作確認済み、実Notion書込未確認） |
| 2026-08-02 | 18:45 | #10 | 関連72テストは成功。全体394テストは既存Backend・旧UI・外部依存範囲で30失敗・8エラーのため未解決として記録 |
| 2026-08-02 | 19:29 | #11 | Issue #174: Focusノード再利用と継続軌道更新で演出の都度再生・移動停止を修正（動作確認済み） |
| 2026-08-02 | 19:51 | #12 | v0.6.0として大改造を完了。PWAスマホ通知のタップ同頭権限要求・SW一本化、Focus OrbitのGPUトランスフォーム化、Cosmic Glass UI全面刷新を実装 |
| 2026-08-02 | 20:03 | #14 | Notion同期失敗（`親タスク`プロパティ欠落および`done_date`引数不一致）の安全ガード・フォールバック修正と失敗キューの修復 |
| 2026-08-03 | 20:13 | #15 | task_sync_queue: createキュー再試行時のNotionページ重複作成を修正。external_id中間保存で冪等性を確保 |
| 2026-08-02 | 20:45 | #16 | Issue #177: v0.7.0共通UIシステム、状態バー、テーマ切替、モバイル下部ナビ、CSS 3D、モーション統一と回帰テストを追加 |
| 2026-08-03 | 04:17 | #17 | Issue #180: v0.8.0としてLife・Focus・Tasksの共有要素遷移、キャンセル可能なTransition Coordinator、タブ指標、スマホTaskカード、Chatシート、PWAキャッシュ統一を実装 |
| 2026-08-03 | 05:12 | #18 | Issue #182: v0.9.0として共有要素遷移を通常フェードへ戻し、全Viewの銀河空間デザイン、Life星系カード、PC・スマホレイアウトを刷新 |
| 2026-08-03 | 09:32 | #19 | v0.12.0としてHomeとFocusをUnivへ統合し、Core中心の操作可能な3D空間、前面HUD、同一空間内のTask Focus・詳細管理、3領域ナビを追加 |
| 2026-08-03 | 19:25 | #20 | Issue #189: v0.13.0としてCore／親タスク惑星／子タスク衛星へ意味構造を統一し、軽量3D球体、同一空間Focus、タブ直接同期を実装 |
| 2026-08-03 | 20:23 | #21 | Issue #189: v0.14.0として四隅型App Shell、右上3アイコン、左上状態表示、左下補助ドック、旧UI設定導線、PWA cache同期を追加 |
| 2026-08-04 | 07:12 | #22 | v0.14.1として静的資産とPWA cacheの版を統一し、App Shell系の二重読込・初期化と初回タスクAPI重複取得を修正（静的回帰・構文確認済み、PC／スマホ実ブラウザ未確認） |
| 2026-08-04 | 07:57 | #23 | Notionプロパティ解析に英語名・日英フォールバック検索（`Parent item`/`親タスク`, `DoneDate`/`Done`等）を追加し、新規端末初期同期時のプロパティ名不一致エラーを自動修正（単体テスト追加・全件通過確認） |
| 2026-08-04 | 08:34 | #24 | 全画面共通UIの再初期化・Service Worker登録共有・Legacy Jobポーリング重複・Corner Shell Observerの自己誘発監視を抑止（関連回帰37件成功、実ブラウザ未完了） |
| 2026-08-04 | 08:34 | #25 | Service WorkerをPush有効化操作まで遅延登録し、通常のUniverse／Legacy起動時の登録・precache待ちを除去（Node構文・関連回帰37件成功、実ブラウザ未完了） |
| 2026-08-04 | 08:54 | #26 | universe-next.jsの更新中Observer一時切断と重複軽減・petit-ui-system/app_shellの監視責務分離および差分DOM更新を実装（関連回帰34件全件成功） |
| 2026-08-04 | 09:10 | #27 | v0.15.0としてUniverse UIを根本刷新。カード矩形UIを全廃し、Core＝中心惑星、親タスク＝惑星、子タスク＝衛星、軌道・接続線からなる純粋な天体システムを実装 |
| 2026-08-05 | 09:26 | #28 | `origin/main`を先に取り込み、`refactor/universe-render-scheduler`を競合解消付きでmainへ統合。関連66テスト、Node/Python構文、差分検査に成功（実ブラウザ・実サービスE2E未確認） |
| 2026-08-05 | 10:50 | #29 | `app.js` と `universe-app.js` のチャット入力キーハンドラーを修正し、Enterキー単体での即時送信を防止、Ctrl/Cmd+Enterのみ送信に統一（関連テスト全件通過） |
| 2026-08-05 | 10:54 | #30 | `chat_input.js`, `chat_keyboard.js`, `app.js`, `universe-app.js` を更新し、IME変換確定のEnter保護・タイマーガード、変換終了後のEnter送信、Shift+Enter改行を実装（関連テスト全件通過） |
| 2026-08-05 | 10:59 | #31 | `univ-space.js`, `univ-space.css`, `universe-webgl-scene.js` を更新し、スマホでのタッチドラッグ宇宙操作対応および2段階タスククリック（1回目フォーカス、2回目詳細表示）を実装（関連テスト全件通過） |
| 2026-08-05 | 11:09 | #32 | `universe-app.js` を更新し、初期化時の過去会話履歴の自動取得・復元機能（restoreHistory）を追加（関連テスト全件通過） |
| 2026-08-05 | 11:18 | #33 | `universe.html` および `universe-app.js` を更新し、2時間アイドル時の自動セッション分割モジュール（session.js）を統合（関連テスト全件通過） |
| 2026-08-05 | 11:30 | #34 | v0.16.0として旧UI（音声音答・モデル切替・通知設定・声かけ頻度・クイック質問等）を新UIへ完全移植。タスク詳細画面での属性フル編集フォームを追加（関連テスト全件通過） |
| 2026-08-05 | 11:35 | #35 | `petit-ui-system.css` および `universe-actions.css` を修正し、スマホ画面でのヘッダー埋もれ・トップバーアクション見切れ・吸着オフセットを改善（テスト49件成功） |
| 2026-08-05 | 12:12 | #36 | `petit-ui-system.js` の `installSpatialMotion` 内のマウス移動による常時チルト・視点追尾 (`pointermove`) を削除し、ドラッグなしの追尾現象を解消（テスト49件成功） |
| 2026-08-05 | 13:45 | #37 | Univ WebGLの入力をOrbitControlsへ明示統合し、PCホイール、1本指回転、2本指ピンチ、複数ポインター時のraycast誤選択、ドラッグ後の慣性回転を修正（関連テスト確認済み、実iPhone未確認） |
| 2026-08-05 | 14:14 | #38 | v0.17.0としてTool不要会話を1回のLLMで完了するOne-pass Conversation Entry、安全な読取fallback、動的時刻のuser側注入、Agent prompt圧縮とMarkdown緩和を実装（Python構文確認・回帰テスト追加、実LM Studio比較未確認） |
| 2026-08-07 | 00:00 | #39 | UIテーマをライト／ダーク／システム選択に対応し、OSのカラースキーム変更へ追従。Three.js Univ空間は暗色を維持し、外側の詳細UIだけライトテーマへ切替 |
| 2026-08-07 | 00:00 | #40 | Univ WebGLの星名ラベルをクリック可能にし、OrbitControlsの空間操作と星名選択を併用可能に変更（関連回帰テスト成功） |
| 2026-08-06 | 17:15 | #41 | Univのラベル選択で元DOMクリックによる全体再描画を避け、Universe選択APIへ統合。再選択時のフォーカス再実行も抑止 |
| 2026-08-12 | 00:00 | #42 | スマホ版でFocusのタスク詳細パネルを非表示化し、ノッチ用safe-areaとチャット入力欄の縦位置を修正（静的確認済み、実iPhone未確認） |
| 2026-08-12 | 00:00 | #43 | 新UIのSettingsへ通知センターを統合し、モデル・Push通知設定を集約。新UIから旧UIへ戻る導線を削除（静的確認済み） |
| 2026-08-13 | 00:00 | #44 | `start-petit-tailscale.bat` と `scripts/start-petit-tailscale.ps1` を追加し、PETIT起動・ヘルスチェック・管理者権限付きTailscale Serve起動を自動化（初版BATはcmdの文字コード・記号解釈問題があり修正、実機UAC・外部Tailnet接続は未確認） |
| 2026-08-13 | 00:00 | #45 | BATを廃止し、`scripts/start-petit-tailscale.ps1` に起動モード選択、Tailscale接続、PETIT起動、ブラウザ起動を統合（PowerShell構文確認済み、実機UAC・外部Tailnet接続は未確認） |
| 2026-08-13 | 00:00 | #46 | デスクトップに `PETIT Launcher.lnk` を作成し、ダブルクリックでPowerShellランチャーを起動できるように設定（ショートカット設定確認済み、実機UAC・外部Tailnet接続は未確認） |
| 2026-08-22 | 16:43 | #47 | Issue #168: Task ID付き作業履歴、状態遷移イベント、今日・期間集計、チャットTool、Universeのサーバーactive同期を実装（関連自動テスト・構文確認済み、実LM Studio・PC／iPhone E2E未確認） |
| 2026-08-17 | 00:00 | #47 | Git整理の中間対応として、`c26db2b` から `feat/chat-work-session` を作成し、整理前の `agent/univ-three-work-chat` を `backup-before-branch-cleanup-20260817` タグへ保存（リモート削除・履歴書き換えは未実施） |
| 2026-08-17 | 00:00 | #48 | GitHub上のリモートブランチを `main` と `feat/chat-work-session` に整理し、重複リモート `PETIT` と旧ローカルブランチ `agent/univ-three-work-chat` を削除（作業ブランチはPush済み、PROGRESS変更は未コミット） |
| 2026-08-17 | 00:00 | #49 | Issue #215: Univ表示時のhtml/body・メイン領域を固定し、safe-area対応の100dvh viewportとWebGL単一背景を実装（関連回帰26件成功、実ブラウザ・実iPhone未確認） |
| 2026-08-16 | 16:36 | #50 | Issue #215: URL直開き時のWebGL未読込と詳細初期化例外を修正し、星の1クリックFocus・HUD同期、全画面Canvas、PC／390x844のHUD・詳細配置を再調整（関連57件・実ブラウザ成功、実iPhone未確認） |
| 2026-08-16 | 23:04 | #47 | Issue #215: v0.18.0としてUnivを100dvh固定Three.js空間へ統一し、WebGL時のCSS背景重複を廃止、mobile safe-area内へHUDを固定（静的回帰テスト追加、実PC／iPhone操作感は未確認） |
| 2026-08-18 | 11:53 | #48 | Issue #218: 「へいプティ」Vocal Shortcut向け `POST /api/voice` を追加し、既存 `/api/chat` へ委譲。最新mainへ競合解消し、確認付き書き込み・回帰テスト・iPhone設定手順を維持（実iPhone E2E未確認） |
| 2026-08-22 | 17:07 | #49 | v0.18.1としてUniv WebGLを必要時描画へ変更し、ラベルDOMの毎フレーム更新・選択時の重複再描画・軽量設定のWebGL無視を修正 |
| 2026-08-22 | 17:21 | #50 | v0.18.2として旧左レールの228px予約幅を解除し、デスクトップUnivの左余白を修正 |
| 2026-08-23 | 05:11 | #51 | PR #222: Tasks画面へNotion明示同期・失敗同期の再試行・競合時の再編集案内を追加。mainのv0.18.2更新を維持して競合解消（実Notion・実ブラウザ未確認） |
| 2026-08-23 | 14:12 | #52 | Issue #223: active / paused Work SessionをOne-pass Conversation Entryへcompact注入し、proactive openerで実セッションを優先（関連48テスト・Python構文確認済み、実LM Studio未確認。旧`test_assistant_context.py`の既存失敗はorigin/mainでも再現） |
| 2026-09-02 | 06:49 | #53 | Issue #227 Phase 2: `/api/health` の実装を `backend/health.py` のAPIRouterへ分離し、`backend/main.py` はRouter登録だけを担当。path/response契約は維持し、Router所有権の回帰テストを追加（実サービスE2E未確認） |
| 2026-09-02 | 07:18 | #54 | Issue #227 Phase 2: `/api/tts` と `/api/tts/status` を `backend/voice.py` のAPIRouterへ分離し、`backend/main.py` はRouter登録だけを担当。path/response契約を維持し、Router所有権の回帰テストを追加（実AivisSpeech E2E未確認） |
| 2026-09-02 | 07:32 | #55 | Issue #227 Phase 2: `GET/POST /api/model-routing` を `backend/model_routing_api.py` のAPIRouterへ分離し、`backend/main.py` はRouter登録だけを担当。更新schema・health cacheクリアも専用Routerへ移動し、Router所有権の回帰テストを追加（実モデル切替E2E未確認） |
| 2026-09-06 | 04:09 | #56 | Issue #227 Phase 2: `POST /api/notion/webhook` を `backend/notion_webhook.py` のAPIRouterへ分離し、endpoint key・JSON・verification token・signature検証を移動。`backend/main.py` はRouter登録だけを担当し、Router所有権の回帰テストを追加（実Notion Webhook E2E未確認） |
| 2026-09-06 | 04:14 | #57 | v0.18.3 / Issue #227 Phase 2: startup/shutdown・Chroma初期同期を `backend/lifecycle.py` へ分離し、`backend/main.py` は `lifecycle.register(app)` のみ担当。lifecycle登録回帰テストを追加（実サービス起動E2E未確認） |
| 2026-09-06 | 12:13 | #58 | v0.18.4 / Issue #227 Phase 2: Pending Actionの10分TTL状態管理・`POST /api/actions/{approval_id}`・Sona Core互換分岐・承認後Tool dispatchを `backend/pending_actions.py` へ分離し、`backend/chat_models.py` に確認APIモデルを共通化。Runtime FlowとRouter所有権テストを更新（実承認E2E未確認） |
| 2026-09-06 | 13:16 | #59 | v0.18.5 / Issue #227 Phase 2: `POST /api/chat`・Agent実行・observability・SQLite会話保存・Chroma/Markdown artifact保存を `backend/chat.py` へ分離。`main.py` はRouter登録のみ担当し、Vocal ShortcutもChat moduleへ直接接続。Router所有権・空入力契約の回帰テストを追加（実LM Studio・実iPhone E2E未確認） |
| 2026-09-06 | 18:03 | #60 | v0.18.6 / Issue #227 Phase 2完了: 補助API群とStatic Frontend配線まで専用モジュールへ分離し、`backend/main.py` をFastAPI生成・Router登録・lifecycle/frontend登録・起動のみのComposition Rootへ縮小。次フェーズはModule Registry（pytest / 実サービスE2E未確認） |
| 2026-09-06 | 18:10 | #61 | v0.19.0 / Issue #227 Phase 3開始: `backend/kernel/modules.py` に `ModuleDefinition` / `ModuleRegistry` を追加し、Router・registrar・依存関係を明示登録。`backend/app.py` の `create_app()` がModule RegistryからFastAPIを構築し、`backend/main.py` は起動shimへ縮小。依存順・重複ID・未知依存・循環依存の回帰テストを追加（pytest / 実サービスE2E未確認） |
| 2026-09-06 | 18:16 | #62 | v0.19.1 / Issue #227 Phase 3完了: `backend.tools` package import時の全built-in Tool副作用登録を廃止し、`backend/tools/builtins.py` の明示catalogを `builtin-tools` Moduleとして登録。Pending Action / ChatのTool依存をModule Registryへ宣言し、単体import時0件・`create_app()`後登録のsubprocess回帰テストを追加（pytest / 実LM Studio E2E未確認） |
| 2026-09-06 | 18:30 | #63 | Issue #235: PETIT Core Promptを共通化し、Tasks / Calendar限定Context Broker、Read並列取得、`Brain -> Broker -> Brain` 2 Call経路、Call数/Context量observability、関連回帰テストとRuntime Mermaidを追加（pytest / 実LM Studio・外部サービスE2E未確認） |
| 2026-09-07 | 06:38 | #64 | Issue #249 / Refs #245: Web中心のJARVIS全体設計、個人Contextの横断Read・期限/最大4枠/サイズ上限・部分失敗、2回目Brainへの状況継続と生成失敗の非保存、任意PC観測Module、FastAPI lifecycle登録互換性を実装。Runtime Mermaid・関連回帰テストを更新（実LLM・外部サービス・PWA/Windows前面アプリE2E未確認） |
| 2026-09-07 | 11:10 | #65 | Issue #253: v0.20.0としてDesktop設計、Electron常駐シェル、小型共有UI、取消可能な音声入力、任意ウェイク、更新通知・手動配布workflowを追加。Desktop境界12テスト・既存関連19テストと31 subtest・macOS実Electronの仮サーバー/生成音声操作を確認。古いPrompt/Router回帰テストを現行構成へ追従（実マイク・Windows・署名済み配布は未確認） |
| 2026-09-08 | 14:16 | #66 | Issue #253: Desktop配布workflowをPRテスト、手動開発Artifact、main上のversion一致`v*`タグによるmacOS arm64/Windows x64ビルド＋GitHub Release自動添付へ整理。タグ/`package.json` version一致とmain履歴チェックを追加（実タグRelease・署名済み配布は未確認） |
| 2026-09-09 | 12:11 | #67 | Issue #255: Web音声入力の現行UI接続を修正し、録音STT・原因別案内・下書き保持を追加（関連Python24件、Web音声7件、Desktop12件成功。Braveの現行DOM＋模擬認識で送信確認、実マイク・実STT未確認） |
| 2026-09-09 | 12:23 | #68 | Issue #256: Desktopにウェイクモデル自動取得・生成、OS暗号化保存、マイク実検出テスト、原因別表示と詳細手動設定を追加。関連21テスト・実Electron操作・Mac arm64展開ビルド成功。キー付きAPI・実マイク・Windows実機は未確認 |
| 2026-09-09 | 15:56 | #69 | Issue #258: openWakeWord独立学習環境・日本語SAPI合成・話者分離評価・WAV検証CLIを追加しhey_petit.onnx v0.1を生成（動作確認済み: ONNX/実推論・2テスト・構文・依存整合。test正例12/12、負例誤検出11/144。実声/長時間待機/Desktop統合は未確認、常時待機精度は未達） |
| 2026-09-09 | 17:38 | #70 | Issue #253 / #258調査: Windowsインストール版PETITの起動と保存設定を確認。STT URL未設定、wakeEnabled=false、Porcupineモデル・保存キー未設定のため音声入口は未構成。実装上ウェイクは小型画面非表示時のみ、openWakeWordはDesktop未統合。設定変更・実マイク検証は未実施 |
| 2026-09-09 | 17:51 | #71 | feat/petit-desktop へ origin/feat/petit-desktop、fix/desktop-wake-auto-setup、main の全最新アップデート・派生ブランチを競合解消して完全マージ統合 |
| 2026-09-10 | 04:11 | #73 | Windows環境におけるwake-settings.test.cjsのURL形式不一致を修正（全21テスト成功） |
| 2026-09-10 | 07:30 | #74 | Porcupine依存を削除し、DesktopをローカルopenWakeWord/ONNX＋Pythonマイクランタイムへ接続。実マイク評価は環境依存で未確認 |

| 2026-09-09 | 21:33 | #74 | Issue #260: Web/小型Desktopの共通モーション、Desktop設定・録音中の軌道表現、PWAキャッシュ更新を実装。動作確認済み: EdgeのUniverse/Legacy（1280px・390px）と実Electron fixture smoke、通常/reduced-motion、diff確認。既存PWA更新・実iPhone/macOS・配布版反映は未確認 |
| 2026-09-09 | 21:43 | #75 | Issue #260: Three.js天体の登場・選択拡大・発光パルスを追加し必要時描画を維持。実WebGL fixture確認・関連13テスト・構文成功。古いSWキャッシュ名のテスト期待値を更新。大量実データ・実iPhone/macOS性能は未確認 |
| 2026-09-10 | 06:50 | #76 | Proactive openerのセッション外エピソード参照を停止し、誤ったepisode_id=2をSQLite/Chromaから削除（関連10テスト成功、実アプリ・実LLM未確認） |
| 2026-09-12 | 10:10 | #77 | Issue #270 Step 1: Desktop Wake設定をopenWakeWordへ一本化し、旧Picovoice/Porcupine AccessKey・PPN・自動設定IPC・暗号化キー保存を撤去。旧設定読込時の秘密情報/metadata除去とopenWakeWordエラー分類の回帰テストを追加（実マイク・installerはStep 3で確認） |
| 2026-09-12 | 10:24 | #78 | Issue #270 Step 2: Desktop設定からopenWakeWord環境を一括準備できる導線を追加。Python検出、専用venv、依存、backbone、既存/生成済みWakeモデルの管理領域化、マイクなしdiagnostic、進捗/中止、managed runtimeパス保存を実装し、Desktop CI成功。packagedモデル同梱・実マイク`ready`・実声はStep 3へ残す。 |
| 2026-09-12 | 10:53 | #79 | Issue #270 Step 3 / PR #272: Desktop openWakeWordのinstaller配布経路を実装。Wakeモデルをbuild時にローカルまたはURL+SHA-256から注入し、manifest同梱・packaged resource検証を追加。Run #76でmacOS arm64 DMG / Windows x64 EXE生成とSmoke/packaged検証に成功。実モデル同梱build、自動設定→diagnostic、実マイク`ready`、実声/誤起動評価は実機受入として継続。 |
| 2026-09-12 | 12:53 | #80 | v0.21.0 Release blockerを解消。Wakeモデル未設定時は未同梱manifest付きinstaller/Releaseを許可し、モデル配布設定が存在する場合だけHTTPS+SHA-256検証を必須化。Run #90でモデルなしmacOS arm64/Windows x64 packageを実生成し全工程成功。`VERSION`同期と1ボタンRelease workflowを追加し、実タグ/Release実行のみ未確認。Issue #270はWake実機受入として継続。 |
| 2026-09-12 | 13:02 | #81 | v0.21.0を正式Release。タグは`9b6a517`へ作成し、Run #92でtest・macOS arm64未署名DMG・Windows x64 EXE・packaged Wake resources・GitHub Release作成が全て成功。Release資産2件を公開。Wakeモデルは未同梱で、実機Wake受入はIssue #270で継続。 |
| 2026-09-19 | 00:33 | #82 | Issue #274: 明示されたタスク作成・変更・完了・親子変更・同期再試行を追加確認なしで即時実行し、全書き込み引数検証と決定論的完了報告を更新（関連70テスト・31 subtest・Python構文・diff確認済み、実LM Studio会話E2E未確認）。 |
| 2026-09-20 | 09:24 | #83 | Issue #276 / v0.22.0: Web/Desktop UIを静かなAIワークスペースへ刷新し、適応型サイドバー、コマンドパレット、共通トークン、状態UIを実装（関連21テスト・Desktop 32 subtest・実Electron fixture smoke・Codex内ブラウザ操作確認済み、配布版/実iPhone/スクリーンリーダーは未確認）。 |
| 2026-09-29 | 23:58 | #84 | Issue #281: DeepSeek通信へOS信頼ストアによる証明書検証を適用し、FlashモデルIDを`deepseek-flash`へ更新（動作確認済み: 対象6テスト・構文・実Chat/Agent・FastAPI `/api/chat`、pytest未導入・旧広範囲テストの既存失敗は未解決）。 |
| 2026-09-30 | 00:06 | #85 | Issue #281のmain反映準備としてPatchバージョンをv0.23.3へ更新し、`VERSION`・Web表示・PWA asset versionを同期。 |
| 2026-09-30 | 06:15 | #86 | Issue #284: TimeTree exporter専用CAへOS信頼ルートを含め、TLS検証失敗を修正（動作確認済み: 実同期1,221件・キャッシュ更新・関連7テスト成功。旧NotionテストのAPI不一致は別途未解決）。 |

| 2026-10-03 | 19:17 | #273 | Wake自動設定へ設定画面で選択中のONNXを渡す。 |

| 2026-10-03 | 19:21 | #286 | Desktopに返答再生完了後の次発話待機と停止制御を追加。 |

| 2026-10-03 | 19:25 | #288 | 音声会話だけに短文応答方針をrequest-localで適用。 |

| 2026-10-03 | 19:31 | #290 | マイク準備/再生待機を上限で停止し、現行Wakeと実機受入手順を整理。 |

| 2026-10-03 | 19:34 | #292 | 非同期で復元した会話履歴の自動読み上げと現在TTSの停止を防止。 |

| 2026-10-06 | 06:26 | #294 | v0.24.0: Dialogue Working MemoryでTask実体参照と確認回答を継続し、開発名詞句のProject誤解析を修正。9ケース自動検証と隔離実ブラウザ会話を確認、実Notion同期は未確認。 |

| 2026-10-06 | 07:54 | #296 | v0.24.1: Web / 小型Desktopの共通仕上げ、スマホタスクの文字潰れと状態表示の重複を修正。隔離ブラウザと関連回帰で確認、配布版・実iPhoneは未確認。 |

| 2026-10-06 | 08:25 | #297 | Univ以外のTask Detailを作業セッション対象へ連動し、選択状態との混同を解消。作業なし/停止/自由入力とUnivの選択詳細を回帰確認。 |
| 2026-10-07 | 19:59 | #299 | v0.25.0: Desktopの作業画面・同梱復旧・小型下書き保持・待機中断・位置保持・非表示取得休止を実装。関連自動テストと隔離Electron確認、Windows開発installer生成。実機/実サービス受入は未確認。 |
| 2026-10-07 | 20:27 | #301 | v0.25.1: Desktop/共通Coreの状態・会話/実行・起動/復旧・画面責務・6段階の移行を設計し、#302〜#307へ分割。目標の新API/管理Coreは未実装。 |
| 2026-10-12 | 09:07 | #309 | v0.25.2: macOS配布の署名スキップを検出し、署名/DMG内容一致検証と正式Releaseの資格情報必須化を追加。ad-hoc再作成の署名検証成功、公証・通常起動は証明書不足で未完了。 |

| 2026-10-12 | 11:15 | — | 同期競合のPETIT側採用を実行したが、Notion親ページの404で失敗。子取得成功・親取得404を実サービスで確認、ローカル競合/親設定保持。親の存在/連携共有確認待ち。 |
| 2026-10-12 | 19:06 | #315 | v0.26.0未公開: Desktop更新・作業星・入力・Notion競合解消・通知/声かけを実装。関連自動回帰、Windows package、Web Push依存復旧を確認。実Notion/配布更新/実機通知/実音声は未確認。 |
| 2026-10-12 | 19:18 | #316 | Univを広く使える可変タブバーを追加。縮小/hover/focus展開/固定保存と既存回帰を隔離Electronで確認。実端末受入は未確認。 |

| 2026-10-12 | 20:35 | #318 | v0.27.0: 小窓の惑星削除、作業バーの上部固定/詳細開閉、Chatの常駐入力/会話スクロール、Univの惑星発光/ミドル移動を実装。関連回帰と隔離実Electronで動作確認済み、実端末/配布版は未確認。 |

| 2026-10-12 | 20:38 | #318 | ChatのCURRENT CONTEXTと3つのクイック質問をCSS非表示からHTML/更新処理の削除へ変更。PWAキャッシュを更新し、関連52件と隔離実Electronで動作確認済み。配布版/実端末は未確認。 |

| 2026-10-12 | 20:50 | #319 | 統計タブへ今日の合計・件数・最長、7日間/タスク別グラフと作業記録を追加。関連134件と隔離Electronで動作確認済み。稼働APIの合計一致と競合1件を読み取り確認、実端末/配布版は未確認。 |

| 2026-10-12 | 20:59 | — | v27の実Web操作UX調査。Tasksの2回目クリック不一致、選択とHUD不一致、詳細の閲覧/編集混在と開始ボタン埋没、切替後HUD重なり、統計/競合の導線を記録。コード修正なし、実Desktop/音声/狭幅は未確認。証拠はstorage/ux-audit-2026-10-13/report.md。 |

| 2026-10-13 | 04:45 | #321 | v0.28.0: 選択/HUD・詳細の開始/編集・期限/競合/音声説明を改善し、日別統計とrevision付き振り返り保存を追加。Desktop同一文書切替のready誤解除も修正。関連158件と隔離Electron、実Web読取で確認。実データの変更・配布版/実端末受入は未実施。 |

| 2026-10-13 | 11:49 | #327 | v0.29.0: 保存済みの接続・同期診断メニューと明示接続確認、Notion失敗対象/再試行/競合導線を追加。秘密情報の伏せ字と部分障害を検証し、競合採用のsnapshot/監査を同一トランザクションへ修正。実サービス・実端末受入は未確認。 |

| 2026-10-15 | 02:39 | #332 | v0.30.3: Task再開のProject誤認と同一Taskのpaused再開を修正。関連86件と隔離HTTP会話の保存・LLM不要を動作確認済み、稼働アプリ/実データは未確認。ローカル固有コミットdc865feを退避ブランチに保持し、新mainとの統合を実施。 |
| 2026-10-19 | 10:52 | #335 | v0.30.3: 会話からSession開始の原因を先に再現し、既存Dialogue/Brain/Agentで対象ID・失敗再試行・実行結果照合・同時開始を改善。隔離HTTP/自動回帰とVision重ね合わせを検証、実モデル/実Notion/配布Desktopは未確認。変更前の旧テスト失敗は#336、一般Action契約は#303で後続。 |

| 2026-10-19 | 11:24 | #338 | AI-First責務分担と3方式を調査・比較し、本番未接続PoCを追加。実DeepSeekの合成12ケース×3方式で直接経路に改善を観測したが、引用翻訳の失敗等が残るため本番移行は見送り。PR #337の安全機能・元checkoutは保持。結果/手順/未確認は docs/ai-first-agent-design.md。 |
| 2026-10-17 | 14:16 | #333 | v0.31.0: 画像添付/Vision観測/Read専用Brain回答とPython比率検証、明示cloud同意・TTL・session境界を実装。関連125件と11 subtests、Desktop64件、隔離Chromeの3 UI×2幅成功。実Provider/Discord/実端末は未確認。 |

| 2026-10-23 | 14:48 | #345 | Project Continuityと既存ローカル観測を確認済みフォルダで接続。登録/解除・同名衝突・Task.project_id・mtime/出典/Git・stale・許可撤回・private/リンク拒否を一時Gitで検証（34件成功）。実データ/実Provider/実端末は未確認。 |
| 2026-10-23 | 14:35 | #345 | 元発言の横断検索と長期記憶の期限/置換/visibilityを追加。無制限保存・bounded取得・旧行保護・並行重複・private除外・予定の完全一致再登録抑止を一時DBで検証。実Provider/Discord/実端末は未確認。 |
| 2026-10-23 | 14:10 | #345 | 単一BrainとThread/Turnの永続化を実装。再送・同時受付・承認・局所書込receipt・履歴分離・SQLiteバックアップを隔離データで検証。旧実行ループと重複登録を削減。実サービス/実端末の受入とRenaissance後続能力は未確認。 |

| 2026-10-24 | 22:20 | #349 | 公式SDKも可という最新指示に従い独立SDK/単一Brain接続PoCを専用branchへ追加。SDK設定と合成契約32件成功、実SDK通信はキー未設定でskipped。本番未接続・目標未達。個人CLI制約と認証/課金/受入の残件を記録。 |

| 2026-10-24 | 22:46 | #349 | v0.33.0: 再更新されたSDK+LM Studio方針に従い、公式SDKを限定Read専用Brainへ接続。実runtime/ローカル推論・会話/Read/履歴・SDK保存再開・取消/timeout・ChromiumのWeb/Desktop sourceを確認。関連81件+5 subtests/Node5件成功。個人CLI・Gemini SDK実通信・配布Desktop/macOS/Writeは未確認、Issue Open・PR #351未マージを維持。 |

| 2026-10-25 | 11:03 | #353 | 2026-10-25-01: v0.34.0 初期設定・AI順位・Google読取連携・日次Calendar同期・運用アラートを実装。隔離Python121件/Node71件と実SDK+LM StudioのTool/承認/保存/再起動/Fallbackを確認。外部本人認証・実サービス/端末/Cloud受入、双方向/Tool後切替は未完了として保持。 |

| 2026-10-25 | 15:25 | #355 | 2026-10-25-02: v0.34.1 CLI導入検出UI・本番拒否・独立直接probe・JSON/NDJSONのMock契約と既存Eventsのsession分離/再送防止を追加。隔離テスト/Chrome/合成process tree終了は動作確認済み。実CLIは未導入でskipped、Google推論/契約枠/実ファイル/実端末は未確認。許諾矛盾とRead専用/Approval境界を残し、導入手順・問い合わせ案を文書化。 |

| 2026-10-27 | 10:11 | #355 | 2026-10-27-01: Windowsの公式agy 1.4.8でAPIキー環境変数なしの日本語JSON/同一conversation NDJSON/合成README read_fileを実証。modelと週次枠98%をCLIで観測、credits 0。月額契約利用はunknown、規約・PETIT本番/実WEVORA・Approval境界は未解決のため無効を維持。

| 2026-10-28 | 13:39 | #357 | 実装済み・未確認: ACP Registry導入、状態/handshake/OAuth設定UI・APIを追加。Windows実AgentのACP v1 initializeとoauth-personal広告を確認。OAuth・推論・利用枠・PETIT Brain・OS隔離は未確認/未接続のため本番Provider化していない。隔離3件とsetup既存20件成功。 |

| 2026-10-29 | 08:15 | #358 | PR #358反映済みorigin/mainとローカルmainを統合。#332のTask再開修正を保持し、新mainのv0.34.0・ACP導入・Runtimeを維持。7ファイル競合を解決。関連テスト21件+29 subtests成功（HTTP保存ケース1件はstorage/settings権限エラーで未確認）。compileall成功。diff --checkは上流追加docsの末尾空白9件を報告。DBバックアップとstorage/vision-uiを保持。 |
| 2026-10-29 | 09:48 | #360 | v0.34.2: AGENTSにコード削除の影響調査・互換性/データ保護・独立PR/回帰確認を明文化。Linkraft/Sona等は監査候補のみ、機能削除なし。実行テストは文書変更のため未実施。 |
| 2026-10-29 | 11:30 | #365 | v0.35.0: 管理者セッションのSQLite DB永続化（再起動耐性・1年有効期限）、UIログアウト、非管理者時の通常会話モード（ツール全般禁止）を実装。 |
| 2026-10-29 | 10:23 | #363 | v0.34.3: Sona Core/Linkraftの旧Adapter・実行分岐・依存・専用テストを撤去。Project Continuity、Notion/GitHub/BRAIN、予定/承認を保持し、既存SQLite行と旧Linkraftリンクは削除せずunsupported/skipped。新回帰追加、GitHub CIと実DB受入はPRで追跡。 |

| 2026-10-30 | 08:32 | #368 | 2026-10-30-01: 実装済み・未確認: SDK撤去と旧設定の明示移行、Provider共通Core境界を追加。関連Python78件・Node5件・Chromium設定/再起動成功（合成Provider）。実Provider/配布端末未確認、Workspaceと会話性能は後続。 |

| 2026-10-30 | 08:46 | #368 | 2026-10-30-02: 実装済み・未確認: Provider共通Workspace/補助session、Codex resume、動的Tool詳細取得、天気/news公開、usage/時間計測を追加。関連pytest95件・Node5件・Chromium1440/390px成功（合成Provider）。実CLIの専用AGENTS読込と検索mode設定を確認。未認証のため実推論・会話速度/品質/検索/実端末は未確認。 |
| 2026-10-29 | 09:51 | #359 | 2026-10-29-02: CLIのみ接続・Codexモデル診断/Tool重複防止を追加。 |
| 2026-10-29 | 10:44 | #362 | 2026-10-29-03: 利用者の明示許可で公式Antigravity CLIをfinish専用Agent/構造化JSON Brainへ接続。 |
| 2026-10-29 | 10:44 | #225 | 2026-10-29-04: 承認付きCLI開発タスク（Task/Job分離、専用clone/Core承認Tool、Web進捗・差分レビュー）を追加。 |
| 2026-10-29 | 10:52 | #359 | 2026-10-29-05: CodexのPATH非依存検出をWindows標準launcher対応の堅牢resolverへ修正。 |
| 2026-10-29 | 10:55 | #362 | 2026-10-29-06: 接続テストの画一エラーを特定reason別の説明・Turn保存へ変更。 |
| 2026-10-29 | 10:59 | #362 | 2026-10-29-07: Codex/Antigravity CLIの候補モデル一覧取得・選択・保存UIを追加。 |
| 2026-11-03 | 06:39 | #372 | v0.40.0: Coding Jobの管理者read-only Activity状態一覧を既存Development Hubへ接続。非機密のID/status/provider/時刻のみ投影、Coding Job未初期化時の副作用なし。実機・再起動回復は未確認。 |
| 2026-11-06 | 08:46 | #345 | 調査: ドキュメント約75本とオープンIssue 55件を棚卸し。Brain記述の不統一（LM Studio/DeepSeek/Antigravity）、Claude Code・アカウント型設定の記述なし、Issueラベル未整備を確認。変更・テストは未実施。 |
| 2026-11-06 | 08:59 | #345 | docs: 文書統一 Step 1。Concept.mdをCLI中心の北極星へ刷新、architecture.md・docs/README.md新設、docsを分野別フォルダへ移動しリンク・workflowパス更新（リンク切れ0件、runtime-flows文書テスト6件OK）。機能変更なし。 |
| 2026-11-06 | 14:56 | #345 | v0.44.0: Claude Code CLIをExecutor（会話Brain・Coding Job）として追加、既定順位を方針順へ、CLI BrainのdiscoverTools拒否と/api/connectionsのImportErrorを修正。新規テスト17件・実CLI smoke確認、既存失敗51件はbaseと同数。実端末・本人ログイン未確認。 |
| 2026-11-06 | 15:12 | #345 | v0.45.0: 旧キーワードルーティング21モジュールとexecute_agent_write・比較PoCを撤去、画像会話をvision_reply.pyへ移設、旧runtime-flows図をarchiveへ。既存失敗テスト51件→21件（残りは全てbaseから既存）。実端末未確認。 |
| 2026-11-07 | 04:05 | #391 | v0.45.1: Univ 3Dでリサイズ・レイアウト変更時の自動全体表示がユーザーの回転/拡縮を巻き戻していた不具合を修正（操作中・操作後は自動フィットしない、明示リセットで解除）。Playwright再現・回帰テスト追加。実機未確認。 |
| 2026-11-07 | 08:50 | - | 再設計の提案文書を追加（未承認・未実装）: docs/brain/agent-home.md（PETIT Home・MCP・自由度L0〜L3・セッション継続）、docs/channels/discord-bot.md（Owner/Guildの2モード、Guildは DeepSeek only・サーバー別DB・Notion・リマインド・人物認知）。Concept §2・§4の改訂は承認待ち。 |
| 2026-11-08 | 01:38 | - | 再設計方針を承認しConcept.mdへ反映: §4 CLIの自由度をL0〜L3へ（Home内自由・ブランチでのテスト/commit確認なし・push/PR/外部送信は承認・不可逆は拒否）、人格ファイルは差分承認、§2にDeepSeek onlyで分離したDiscord Guildモードを追記、§8 Botは自宅PC＋Cloudflare無料枠ならGuild配送のみ。未実装。 |
| 2026-11-08 | 01:49 | #396 #397 | v0.46.0: PETIT Home を人格の単一ソースに（AGENTS/SOUL/USER.md・git管理・差分承認の update_persona_file・承認カードに Core 計算 preview）、Discord Owner モード MVP（別プロセス Bot、Core が owner 判定、非 owner は Brain 0 回、message ID で冪等）。新規テスト21件、既存失敗17件は base と同数。実 Discord 未確認。 |
| 2026-11-08 | 02:05 | #398 #399 | v0.46.0（同ブランチ追加）: PETIT MCP bridge（Turn限定トークン、catalog・検証・risk・承認・receipt は native と同じ、stdio JSON-RPC。実 Claude Code CLI の `mcp list` で接続確認）。Discord 承認ボタン（owner・Discord 由来のみ）と通知 DM（opt-in、claimed→sent/failed、不明は再送しない）。管理者 cookie ミドルウェアが Bearer 窓口を弾いていた不具合を修正。 |
| 2026-11-08 | 02:26 | #400 | v0.46.0（同ブランチ追加）: Claude Code エージェントモード（opt-in）。Home で組込みファイルTool + PETIT MCP、PreToolUse Hook で L0〜L3、Thread ごとに --resume、MCP 承認→同セッションで再開、Turn ごとに Home を git commit。実 CLI で発見: サンドボックス依存が無いと Bash が無保護で動く→Core が依存を確認して Bash を渡さない／承認後の再開で input_json 消費済みにより MCP が失敗→修正。 |
| 2026-11-08 | 05:45 | #401 | v0.46.0（同ブランチ追加）: worktree Tool（open/status/check/commit/push/PR/close）。L1 を「petit/ ブランチへの push まで」に拡張（Concept §4 更新）、PR は承認、main・既定ブランチ・force push は禁止。git・gh は Core が本人の認証で実行、repo の hook 無効。実 CLI で通し確認。 |
| 2026-11-09 | 01:47 | #402 | v0.46.0 を main へマージ（再設計: PETIT Home・MCP・Claude Code エージェントモード・worktree 開発・Discord Owner モード）。CI 13 本成功。 |
| 2026-11-09 | 01:47 | #404 | v0.47.0: Home ファイル Tool を全 Brain に公開（Core が L0/L1 の線を判定、Hook と共通。`.git` は読取も拒否に変更）、Codex エージェントモード（cwd=Home・AGENTS.md=人格・sandbox read-only・shell なし）。実 Codex / agy は未確認。 |
| 2026-11-09 | 02:30 | #403 | v0.48.0: Discord Guild モード土台（D3）。`/api/guild/*`（Bearer サービストークン）、サーバー別 SQLite（`storage/guilds/<guild_id>.db`）、`/petit setup・reset`（Manage Server 権限のみ）・`/petit me・forget-me`、DeepSeek のみの会話、1日上限・ユーザーレート制限、owner の DB/Tool/Home/CLI への到達遮断（`GuildIsolationError`）を実装。実 Discord・実 DeepSeek 未確認。 |
| 2026-11-09 | 03:15 | #406 | v0.48.1: Development Hubの背景Activityに最終取得日時を表示し、通信失敗時に前回成功時刻と取得失敗を区別。 |
| 2026-11-09 | 03:17 | #395 | v0.48.2: Development Hubの背景Activityに状態別フィルター（すべて／待機・実行中／失敗／完了）を追加。 |
| 2026-11-09 | 03:20 | #390 | v0.48.3: Coding Job詳細更新の差分判定拡張（summary/error/checks/workspace/branch）とClaude Code CLI表示を修正。 |
| 2026-11-09 | 03:25 | #393 #394 | v0.48.4: Univ 3Dのカメラ入力をOrbitControlsから自前コントローラへ置換（追跡外の指を無視・ピンチ後ロック・慣性・タップ統合）、見えない旧DOMボタンがCanvas入力を奪っていた不具合とラベルの広すぎる当たり判定を修正。 |
| 2026-11-09 | 05:00 | #408 | v0.49.0: 過去作業時間の事後登録ツール record_past_work を追加（work_sessionsに記録・集計即時反映）、開発者モードでの回答者バッジ常時表示と履歴復元時のmodel_route維持を実装。 |
| 2026-11-09 | 05:56 | #410 | v0.50.0: 会話Turnの表示専用SSEストリーミング（`GET /api/turns/{id}/stream`・`turn_stream.py`）とAPI Brainの`stream=True`ドラフト配信、Toolラウンド/Fallback時のドラフト破棄、Web/Desktop/Universeのリアルタイム進捗表示を実装。 |
| 2026-11-09 | 06:04 | #411 | v0.50.0: DeepSeekを最初の担当にするトグルとCLI委譲（作業用Thread・専用Worker・親Threadへの報告と承認・状態表示）を追加。単体テストと合成Providerの実ブラウザ操作を確認。実CLIの通しはCLI未ログインのため未確認。 |
| 2026-11-09 | 08:37 | - | v0.50.1: システムプロンプトを縮小（人格・原則を短縮、Tool固有の規則をTool説明へ、FrontのCapability一覧からworktree・Coding Job・Home書込を除外）。未編集のPETIT Home AGENTS.mdは新しい既定へ自動更新。DeepSeek評価は変更前60/60・変更後98/100（`reports/prompt-slimming-evaluation.json`）、Front経路は未評価。 |
| 2026-11-09 | 08:38 | #414 | v0.51.0: 設定UI・AI/サービス接続・接続ステータスを再設計（Settings最上部の状態/直通ハブ、setup画面の常設概要バー・状態/キー保存済みバッジ・TimeTree/Googleのカード内同期元切替、接続ステータスの色分けピルと設定直通リンク）。Playwright 1440/390/320pxと関連単体テスト確認済み、実アカウント手動受入は未確認。 |
| 2026-11-09 | 10:01 | #418 | v0.52.0: Chat提案・Develop直接送信をCoding Jobへ統合し、利用枠ルーティング、CLI認証、Git作業とPC操作承認を実装。Codex/Antigravityの合成Tool往復とEverything IPCを実機確認。 |
| 2026-11-10 | 15:00 | - | v0.53.0: Nocord統合・Discord Knowledge Gateway（FTS5/trigram全文検索、添付テキスト抽出、Core API、全入口共通Tool search_discord_archive、Bot非同期ログ収集、/petit archive、Nocord移行スクリプト）。Guild/Personal分離と通常会話の遅延ゼロを保証。pytest 42件全件成功。 |
| 2026-11-10 | 17:50 | #429 | v0.54.0: CLI自由度向上・リポジトリ登録Tool（add_coding_repository）と作業セッション削除Tool（delete_work_session）を追加、委譲先にAntigravity CLIを追加。関連テスト60件全件成功。 |
| 2026-11-11 | 05:45 | - | v0.54.4: iPhone/モバイルWebAppでチャット入力欄と下部ナビが重なる不具合を修正（セーフエリア・実高さ考慮の安全マージン確保、チャット入力フォーカス・仮想キーボード時の下部タブ退避とキーボード直上追従）。 |
| 2026-11-11 | 07:25 | #438 | v0.55.0: チャット応答の安全なMarkdownレンダリング表示対応（見出し・太字・インラインコード・コードブロックコピー・テーブル・引用・リスト、ストリーミング対応、XSSサニタイズ）。 |
| 2026-11-11 | 07:45 | - | fix(backend): uvicornの監視対象をbackend/に限定しstorageクローン時の誤リロードを防止（PETIT-StartDev.bat / scripts / README）。実Antigravity CLIでのCoding Job完走を確認。 |
| 2026-11-11 | 08:29 | #440 | v0.56.0: プティちゃんマスコットを新デザインのWeb/Desktop共通SVGモジュールへ刷新（表情・動作レジストリ、会話/音声状態連動、ブラウザ内歩行、サイズ/色/動き設定、Desktop散歩・おやすみ）。 |
| 2026-11-11 | 10:52 | - | v0.56.1: チャット起票の開発ジョブを開発タブのスレッド階層へ自動投影し、リポジトリ名解決とNotion同期の古いconflict残骸8件を解消。 |
