# AGENTS.md — PETIT 開発ルール

このファイルは Codex（および開発者）が PETIT を開発するときの共通ルールをまとめたもの。
詳細な製品コンセプトは `Concept.md` を参照。

## プロジェクト概要

PETIT は「会話から色々やってくれる自分専用 AI アシスタント」。
- ローカル LLM（LM Studio などの OpenAI 互換エンドポイント）で動かす
- MVP は **ブラウザ（localhost）で動くテキストチャット**
- 単語トリガー型ではなく、**意図理解 → ツール選択 → 実行 → 自然文返答** 型

## 技術構成（MVP）

- Backend: FastAPI + Python（標準ライブラリ中心、依存は最小）
- LLM: LM Studio（OpenAI 互換 `/v1/chat/completions`、tool calling 利用）
- 記憶: SQLite（`storage/app.db`）。将来 Chroma による意味検索 / Markdown 出力を追加
- Frontend: 静的ファイル（HTML / CSS / Vanilla JS）を FastAPI から配信

## ディレクトリ構成

```
PETIT/
  backend/
    main.py            FastAPI アプリ・エンドポイント・静的配信
    config.py          設定（環境変数で上書き可）
    db.py              SQLite 初期化・アクセス
    lmstudio_client.py LM Studio への HTTP クライアント
    agent.py           意図理解 + ツール実行ループ
    tools/
      registry.py      ツール登録・スキーマ・ディスパッチ
      memory.py        記憶の保存 / 検索
      tasks.py         タスク取得（MVP はローカル DB / 将来 Notion）
      schedule.py      予定取得（MVP はローカル DB / 将来 Calendar）
  frontend/            チャット UI（index.html / app.js / style.css）
  tools/               バックエンド外の単体ツール（TimeTree バックアップ等）
  scripts/             セットアップ・自動化スクリプト
  storage/             app.db などの実行時データ（git 管理外）
  requirements.txt
  Concept.md           製品コンセプト（正本）
  AGENTS.md            このファイル
  PROGRESS.md          変更履歴ログ（表形式）
```

## Git 運用ルール（重要）

- **`develop`** ブランチを開発の主軸とし、ここに都度コミット & プッシュする。
- 機能追加は **`feat/<機能名>`** ブランチを切って作業し、完了後に `develop` へ取り込む。
- `main` は安定版。直接コミットしない。
- プッシュは `git push -u origin <branch>`。
- Codex は、実装・修正・設定変更・ドキュメント更新など作業単位として区切れる変更を行い、必要な確認が済んだら、原則として随時コミットする。
- 既存の未コミット変更がある場合は、今回の作業範囲と混ぜない。必要なら対象ファイルを絞ってステージングし、今回分だけコミットする。
- リモートへの Push は、ユーザーが明示的に Push またはコミットプッシュを依頼した場合に行う。

## Progress Log

このプロジェクトでは、作業進捗を `PROGRESS.md` の1ファイルに記録する。
ファイルは2部構成：

- **現在の状態 / 未確認・TODO** — いま開いている状態（未検証・次にやること）。最新内容で上書きしてよい。
- **履歴** — 変更履歴（表形式・1行サマリー）。追記専用。

### 作業開始時

* 最初に `PROGRESS.md` を読む。
* 「現在の状態 / 未確認・TODO」で未検証・次にやることを確認する。
* 「履歴」で直近の変更を確認し、今回の回数（`#N`）を決める。

### 作業終了時

* 変更・調査・設計判断・テストを行った場合は、必ず「履歴」の表に1行追記する。既存の行は削除・要約・上書きしない。
* 未確認の状態や次にやることが変わったら、「現在の状態 / 未確認・TODO」を最新内容に上書きする。

### 追記形式（PROGRESS.md）

```md
| YYYY-MM-DD | HH:mm | #N | 変更内容（1行サマリー） |
```

### 記録ルール

* 実際に行ったことだけを書く。
* 未確認の内容は「未確認」と書く。
* テストしていない場合は「未実施」と書く。
* 問題がない場合は「特になし」と書く。

## コーディング方針

- 依存は最小限。まず標準ライブラリで解けないか考える。
- LM Studio が起動していなくてもサーバーは落ちず、UI に分かるエラーを返す。
- ツールは `tools/registry.py` に登録すれば LLM から呼べるようにする（追加が容易な設計）。
- 返答は「情報を全部出す」のではなく、必要なら「今やる1個 / 次 / 後で」に整理する（Concept.md 準拠）。
