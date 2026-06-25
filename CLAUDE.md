# CLAUDE.md — PETIT 開発ルール

このファイルは Claude（および開発者）が PETIT を開発するときの共通ルールをまとめたもの。
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
  storage/             app.db などの実行時データ（git 管理外）
  requirements.txt
  Concept.md           製品コンセプト（正本）
  CLAUDE.md            このファイル
  PROGRESS.md          変更履歴ログ
```

## Git 運用ルール（重要）

- **`develop`** ブランチを開発の主軸とし、ここに都度コミット & プッシュする。
- 機能追加は **`feat/<機能名>`** ブランチを切って作業し、完了後に `develop` へ取り込む。
- `main` は安定版。直接コミットしない。
- プッシュは `git push -u origin <branch>`。

## PROGRESS.md ルール（重要）

変更を加えるたびに `PROGRESS.md` に1行追記する。フォーマット:

| 日付 | 時間 | 回数 | 変更内容 |

- 「回数」は通し番号（#1, #2, ...）で、変更ごとに必ずインクリメントする。
- 時刻は UTC でも JST でもよいが、混在させない（このリポジトリは UTC で記録）。

## コーディング方針

- 依存は最小限。まず標準ライブラリで解けないか考える。
- LM Studio が起動していなくてもサーバーは落ちず、UI に分かるエラーを返す。
- ツールは `tools/registry.py` に登録すれば LLM から呼べるようにする（追加が容易な設計）。
- 返答は「情報を全部出す」のではなく、必要なら「今やる1個 / 次 / 後で」に整理する（Concept.md 準拠）。
