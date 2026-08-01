# Personal AI Assistant 開発方針

## 1. 目的

自分の生活・予定・タスク・過去の会話や作業ログを把握し、それに基づいて自然に会話できる 自分専用AIアシスタント を作る。

プロダクト名の軸は `PETIT_AS_JARVIS` とし、最終的にはスマホとPCの両方から使える、音声中心の常駐アシスタントを目指す。
朝に「おはよう」と話しかけたり、スマホやPCで「今日何やればいい？」と聞いたときに、予定・タスク・昨日の作業・過去の記憶を参照して、自然な返答をしてくれる状態を目指す。

ただし、最初から音声・常時起動・完全自動化を目指すのではなく、まずは テキストチャットMVP として検証し、その後にスマホ利用と常駐導線を広げる。

なお、このAIは医療的な診断・治療を目的とするものではない。ただし、生活AIとしての使いやすさを高めるために、ADHD的な困りごとである「忘れる」「始められない」「優先順位が決められない」「脱線後に戻れない」にも配慮した設計にする。

---

## 2. 基本方針

このAIは、単語トリガー型のBotではなく、意図理解型の会話AI として設計する。

また、生活AIとしての回答は、単に情報を多く返すのではなく、必要に応じて「今やる1個」「次にやる1個」「後で見ればよいもの」に整理して返す。特に、予定・タスク・リマインダーが多い場合は、一覧をそのまま出すだけでなく、ユーザーが次に動きやすい形へ要約する。

例えば、

* 「おはよう」
    → ただの挨拶として返す
* 「今日のタスク教えて」
    → ユーザーはタスクを知りたがっていると判断し、Notionタスク取得ツールを使う
* 「明日何ある？」
    → スケジュールを知りたがっていると判断し、カレンダー取得ツールを使う
* 「昨日何やったっけ？」
    → 過去ログ・日次要約・会話記録を検索する

というように、ユーザーの発話からAIが意図を判断し、必要なツール/APIを選んで使う。

---

## 3. 中核設計

AI本体は、アプリやDiscord Botではなく、まず ローカルAI Core Server として作る。

Core Serverの役割

* ユーザー発話の受け取り
* LLMへの問い合わせ
* ツール使用判断
* Notion API連携
* Apple Reminders取得（Macのみ）
* カレンダー取得
* SQLite保存
* Markdown / Obsidian出力
* RAG検索
* 最終返答生成

UIは後から差し替えられるようにする。

将来的な入口は以下のように増やせる。

* ローカルWebチャット
* Macアプリ
* Windowsアプリ
* 音声アシスタント
* Discord Bot
* スマホ用Web UI
* ショートカットキー呼び出し

---

## 4. 最初のMVP

MVP名

Personal Assistant

MVPの目的

音声化やアプリ化の前に、以下を検証する。

* AIがユーザーの意図を読めるか
* 必要なツールを選べるか
* Notionのタスクを取得できるか
* Apple Remindersを取得できるか（Macのみ）
* 過去ログを検索できるか
* 会話ログを保存できるか
* 返答が自然か
* 予定やタスクを、次に動きやすい形へ整理できるか
* 記憶設計が破綻しないか

MVPでやること

* テキストチャット
* 普通の雑談
* 今日のNotionタスク取得
* Apple Reminders取得（Macのみ）
* 今日/明日の予定取得
* 過去ログ検索
* 会話ログ保存
* 日次要約作成
* 朝ブリーフィング生成
* 今日の「最初の一手」提案
* 中断後の作業復帰サポート
* 夜の引き継ぎメモ作成

MVPでまだやらないこと

* 音声入力
* 音声読み上げ
* 常時起動
* Discord通話常設
* スマホアプリ化
* 自動タスク作成
* TimeTree直接連携
* 完全自律エージェント化
* 大量のタスク自動生成
* ユーザーを監視・管理するような通知設計
* 完璧な生活改善スコアリング

---

## 5. 対応プラットフォーム

開発初期は MacとWindowsの両対応を想定 する。

ただし、機能によって対応差がある。

理由：

* Apple RemindersはMacでのみEventKit経由で扱える
* WindowsではApple Remindersに直接アクセスできない
* クロスプラットフォーム設計を初期から意識することで拡張性を確保できる

Apple Remindersの扱い

Apple Remindersは、Mac環境でのみ取得可能 とする。

構成：

```text
iPhone Reminders
↓ iCloud同期
Mac Reminders
↓ EventKit
Reminders Sync Agent（Macのみ）
↓
Local AI Core / FastAPI
↓
SQLite
↓
AIが参照
```

Windows環境では、Reminders機能は利用不可、または将来的に代替手段（Notionや他サービス）で補う。

Apple RemindersをAIの正本にするのではなく、入力元の1つ として扱う。

AIが読む正本は、SQLite / Notion / Markdown側に寄せる。

---

## 6. TimeTreeの扱い

TimeTreeは、MVPでは直接連携しない。

理由：

* 公式APIが終了している
* 外部連携が弱い
* スクレイピングは壊れやすい
* 生活AIの予定取得元としては不安定

将来的には、予定の正本をGoogle Calendar / Apple Calendar / Notion側に寄せ、TimeTreeは表示・共有用として扱うのが望ましい。

---

## 7. ツール呼び出し設計

AIに自由にAPIを叩かせるのではなく、AIには 使いたいツール名と引数だけを出させる。

実際のAPI実行はPython側で行う。

基本フロー

```text
ユーザー発話
↓
LLMが意図を判断
↓
必要なら tool_call を出す
↓
FastAPI側がツールを実行
↓
結果をLLMに戻す
↓
LLMが自然文で返答
```

最初に用意するツール

```text
get_tasks(date, status, priority)
Notionからタスクを取得する
get_reminders(date, status)
Apple Remindersからリマインダーを取得する（Macのみ）
get_schedule(date)
カレンダー予定を取得する
search_memory(query, date_range)
過去ログ・会話記録・Obsidianメモを検索する
save_memory(content, type)
覚えるべき情報を保存する
create_daily_summary(date)
その日の会話・作業・タスクを要約する
suggest_next_action(context)
予定・タスク・リマインダー・過去ログをもとに、今やる最小の一手を提案する
create_handoff_note(date)
明日の自分が再開できるように、途中の作業・次の一手・注意点をまとめる
restore_context(query)
中断後に、直前まで何をしていたか、次に何をすればよいかを復元する
```

---

## 8. 技術構成

Backend

```text
FastAPI
Python
SQLite
LM Studio
Chroma
Markdown / Obsidian
```

Frontend MVP

```text
ローカルWeb UI
localhostで開く簡易チャット
```

将来的なDesktop App

```text
Tauri
または
Electron
```

基本的には、軽さを考えるとTauri優先。

LLM

```text
LM Studio
```

用途別にモデルを分ける可能性あり。

```text
通常会話：LM Studio上の軽めのローカルLLM
ツール判断：JSON出力が安定するモデル
要約処理：LM Studio上の少し強めのモデル
難しい推論：必要時のみ外部API
```

---

## 9. フォルダ構成案

```text
personal-ai-assistant/
  backend/
    main.py
    lmstudio_client.py
    router_agent.py
    response_agent.py
    config.py
  tools/
    notion_tasks.py
    apple_reminders.py
    calendar.py
    memory_search.py
    daily_summary.py
  storage/
    app.db
    logs/
      2026-06-23.md
    memory/
      profile.md
      preferences.md
      projects.md
  frontend/
    index.html
    app.js
    style.css
  docs/
    architecture.md
    tool_design.md
    memory_design.md
    mvp_plan.md
```

---

## 10. データ設計

SQLite

```text
conversations
- id
- timestamp
- user_text
- assistant_text
- intent
- used_tools
- summary_id
daily_summaries
- date
- summary
- done_items
- tomorrow_hint
- mood_or_energy
- created_at
handoff_notes
- id
- date
- current_project
- stopped_at
- next_action
- blockers
- created_at
focus_sessions
- id
- started_at
- ended_at
- task_title
- status
- interruption_note
- next_action
tasks_cache
- id
- source
- title
- status
- due_date
- priority
- external_id
- updated_at
reminders_cache
- id
- title
- notes
- due_date
- completed
- list_name
- external_id
- updated_at
calendar_events_cache
- id
- source
- title
- start_time
- end_time
- location
- description
- updated_at
```

Markdown / Obsidian

```text
/AI_Daily/
  2026-06-23.md
  2026-06-24.md
/AI_Memory/
  profile.md
  preferences.md
  projects.md
  recurring_tasks.md
```

Markdownは人間が読む用。
SQLiteはAIが扱う構造化データ用。
Chromaは意味検索用。

---

## 11. 開発フェーズ

Phase 0：設計

* 要件整理
* ツール一覧設計
* データベース設計
* Notion DB構造確認
* Apple Reminders取得方法確認（Mac）

Phase 1：テキストチャットMVP

* FastAPIサーバー
* LM Studio接続
* 簡易Webチャット
* 会話ログ保存
* ツール呼び出しの基本実装

Phase 2：生活データ取得

* Notionタスク取得
* Apple Reminders取得（Macのみ）
* カレンダー取得
* 今日/明日のブリーフィング生成

Phase 3：記憶機能

* 会話ログ要約
* 日次要約作成
* 長期記憶候補抽出
* Markdown出力
* ChromaによるRAG検索
* 作業復帰用のハンドオフメモ作成
* 「今やる1個」を返す next action 生成
* 中断後に前の文脈へ戻る restore context 機能

Phase 4：デスクトップアプリ化

* TauriまたはElectronでデスクトップ化
* Mac / Windows対応
* メニューバー常駐（Mac）
* ショートカットキー呼び出し
* 通知機能
* 起動時自動実行

Phase 5：音声化

* 音声入力
* 音声読み上げ
* 「おはよう」会話
* 朝ブリーフィング読み上げ
* 将来的に常時待ち受け検討

Phase 6：補助連携

* Discord Bot
* 外出先からの問い合わせ
* 朝通知
* タスク追加
* スマホWeb対応

---

## 12. MVPの成功条件

最初の成功条件は以下。

ローカルWebチャットで、
「今日何やればいい？」
と聞いたら、

- Notionタスク
- Apple Reminders（Macのみ）
- 今日の予定
- 昨日の作業ログ

を必要に応じて参照し、
自然な文章で今日の行動方針を返せる。

このとき、単にタスク一覧を返すのではなく、「今やる1個」「次にやる1個」「後で見ればよいもの」に整理して返せることを重視する。

さらに、

「昨日何してたっけ？」
と聞いたら、
過去の会話ログや日次要約から関連情報を探して返せる。

ここまでできればMVP成功。

---

## 13. 現時点の決定事項

* 単語トリガー型ではなく、意図理解型AIにする
* 最初はテキストチャットMVP
* 本体はローカルAI Core Server
* ローカルLLM基盤はLM Studioを使用する
* UIは後から差し替え可能にする
* Discord常設は本命にしない
* 最初からアプリ化しない
* MVP後にTauri / ElectronでMac / Windowsアプリ化する
* Apple RemindersはMac限定で取得する
* TimeTree直接連携は後回し
* Notion / SQLite / Markdown / Chromaを中心に記憶設計する
* 音声化はMVP検証後に行う
* 生活AIとして、忘れても戻れる・中断しても復帰できる設計を重視する
* AIは大量の情報を渡すのではなく、必要に応じて次に取る行動を小さく絞る
* AIはユーザーを管理する存在ではなく、横にいる補助輪として振る舞う

---

## 14. 次にやること

次に進めるべきは、いきなり実装ではなく、以下の3つ。

1. Notion DB構造の確認

* タスクDBの項目
* ステータス
* 期限
* 優先度
* プロジェクト
* 今日のタスク判定方法

2. Apple Reminders取得の最小検証（Mac）

* MacでEventKitからリマインダー一覧を取得できるか
* 期限付きリマインダーを取得できるか
* 完了済み/未完了を分けられるか
* リスト名を取得できるか

3. Tool Routerの最小実装

以下の発話で、AIが正しいツールを選べるか確認する。

```text
今日のタスク教えて
明日何ある？
昨日何してたっけ？
この話覚えておいて
おはよう
```

この検証が通れば、開発を本格化する。

4. 生活補助としての返答方針の検証

以下の発話で、AIが情報を増やしすぎず、次の行動へ整理できるか確認する。

```text
今日やること多すぎる
何から始めればいい？
さっき何してたっけ？
途中で止まってた作業に戻りたい
明日の自分に引き継ぎたい
```

---

## 15. 最終イメージ

最終的には、MacまたはWindowsに常駐し、スマホからも呼び出せる自分専用AIとして動く。

```text
そそ：
おはよう
AI：
おはよう。今日は6月23日、火曜日。
今日は13時から予定があって、Notion上の優先タスクは3件。
Apple Remindersには未完了が2件あるよ。（Mac環境の場合）
昨日はAIアシスタントの設計と、開発方針の整理をしていた。
今日はまずNotionタスクの確認から始めるのがよさそう。
```

目指すものは、ただのチャットBotではなく、

自分の生活・制作・予定・記憶を横断して支えてくれる、ローカル常駐のPersonal AI Assistant。

そのうえで、忘れても戻れる、中断しても再開できる、タスクが多くても次の一手に変換できる生活補助AIを目指す。

`PETIT_AS_JARVIS` の到達イメージは、スマホからの即応とPC常駐の両方で、会話・通知・音声入出力が切れずにつながっている状態。

---

## 16. 通知基盤

通知は、PETITがユーザーを監視・管理するためではなく、本人が選んだ重要事項をアプリ外でも受け取るための補助導線として扱う。

基本原則:

* 通知カテゴリは初期OFFとし、ユーザーが有効化する。端末でPush通知を明示的に許可した場合だけ、無限計測防止の作業セッション通知を同時にONにし、個別にOFFへ戻せるようにする
* 通知判断、通知イベント保存、配信Providerを分離する
* 通知イベントと配信結果はSQLiteへ残し、送信済みと未送信を区別する
* Web版はService Worker、Push API、VAPIDによるWeb Pushを使う
* VAPID秘密鍵は環境変数またはGit管理外の秘密鍵ファイルから読む
* Web Push未設定・通知拒否・購読なしでも、会話や既存機能を止めない
* iPhoneネイティブ版では、同じ通知判断ロジックにAPNs Providerを接続する

最初の通知カテゴリは、作業セッションの声かけ、予定前リマインド、Highタスク、朝ブリーフィング、GitHub CI失敗とする。通知頻度を増やすより、必要な通知だけが届き、簡単に停止できることを優先する。

作業セッションはサーバー側にも保存し、20分ごとに継続を確認する。確認から20分返事がなければ自動停止し、終了操作を忘れても経過時間が無限に増えないようにする。
