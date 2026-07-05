# PETIT — Personal AI Assistant (MVP)

会話から意図を読み取り、ツールを使って生活・タスク・予定・記憶を支える、
自分専用のローカル AI アシスタント。詳しい思想は [`Concept.md`](./Concept.md) を参照。

この MVP は **ブラウザ（localhost）で動くテキストチャット** で、
LLM は **LM Studio**（OpenAI 互換のローカルサーバー）を利用します。

## 構成

```
backend/   FastAPI サーバー・エージェントループ・ツール
frontend/  チャット UI（静的ファイル）
storage/   SQLite などの実行時データ（git 管理外）
```

## セットアップ

1. 依存をインストール:

   ```bash
   pip install -r requirements.txt
   ```

2. LM Studio を起動し、ローカルサーバー（OpenAI 互換）を有効にする。
   デフォルトは `http://localhost:1234/v1`。モデルをロードしておく。

3. サーバー起動:

   ```bash
   uvicorn backend.main:app --reload
   # または
   python -m backend.main
   ```

4. ブラウザで <http://127.0.0.1:8000> を開く。

## 環境変数（任意）

| 変数 | 既定値 | 説明 |
|------|--------|------|
| `PETIT_LM_BASE_URL` | `http://localhost:1234/v1` | LM Studio のエンドポイント |
| `PETIT_LM_MODEL` | `local-model` | 使用モデル名（LM Studio 上の id） |
| `PETIT_HOST` / `PETIT_PORT` | `127.0.0.1` / `8000` | サーバーの待受 |

## 現在使えるツール

- `save_memory` / `search_memory` — 記憶の保存・検索
- `get_tasks` / `add_task` — タスクの取得・追加（ローカル DB）
- `get_schedule` / `add_schedule` — 予定の取得・追加（ローカル DB）
- `create_daily_briefing` — 予定・タスク・最近の流れから朝ブリーフィングを作成

LM Studio が未起動でもサーバーは落ちず、UI 上にエラーを表示します。

## 開発

- 主軸ブランチは `develop`。機能追加は `feat/<機能名>`。
- 変更のたびに `PROGRESS.md` に追記する。
- ルール詳細は [`CLAUDE.md`](./CLAUDE.md)。
