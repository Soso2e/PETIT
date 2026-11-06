# CLAUDE.md — PETIT

開発ルールの正本は **[AGENTS.md](AGENTS.md)**。Claude Code もこれに従う。本ファイルには入口だけを置き、ルールを重複して書かない。

## 作業開始時に読むもの

1. [AGENTS.md](AGENTS.md) — 開発ルール（Git・PR・テスト・バージョン・Progress Log）
2. [Concept.md](Concept.md) — 目指す姿と判断基準（北極星）
3. [docs/architecture.md](docs/architecture.md) — 現行の実装概要と、目標との差
4. [PROGRESS.md](PROGRESS.md) — 現在地・未確認・直近の履歴
5. 関連するIssue・PRと、[docs/README.md](docs/README.md) から辿れる分野別の詳細

## 特に間違えやすい点

- `main` を base に、`feat/` `fix/` `docs/` `refactor/` ブランチで作業し PR を出す。`main` に直接コミットしない（`develop` ブランチは使っていない）。
- 会話処理・Tool 実行を変えたら、同じ変更内で [docs/runtime-flows.md](docs/runtime-flows.md) の Mermaid 図も更新する。
- 新しい文書の置き場所と書き方は [docs/README.md](docs/README.md) の配置ルールに従う。
- PROGRESS.md の履歴は追記専用で、時刻は UTC。
