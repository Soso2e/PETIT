# PETIT Home — CLIを「判断器」から「自立した作業者」へ

> Status: **目標（方針承認済み 2026-11-08・未実装）** / Last updated: **2026-11-08**
>
> 関連: Concept.md §4・§8・§10、[claude-code-cli.md](claude-code-cli.md)、[persistent-agent-workspace.md](persistent-agent-workspace.md)、[../dev/coding-tasks.md](../dev/coding-tasks.md)
>
> 方針（L0〜L3・人格ファイルの差分承認）は Concept.md §4 に反映済み。実装を変えたら runtime-flows.md を同じ変更で直す。
> 実装されるまで、現行の動作の正本は [claude-code-cli.md](claude-code-cli.md) と [../runtime-flows.md](../runtime-flows.md)。

---

## 1. いま何が弱いか（現状診断）

Concept §4 は「判断と処理をCLIに任せる」と決めたが、実装はCLIの強みをほぼ全部止めている。

| CLIの強み | 現行の扱い | 結果 |
| --- | --- | --- |
| ファイル操作・Shell・検索などの組込みTool | `--tools ""` で全部無効 | ただのLLM APIと同じ。DeepSeekと差が出ない |
| 作業ディレクトリと指示ファイル（CLAUDE.md / AGENTS.md） | 毎回の一時フォルダ。`--setting-sources ""` で読込も無効（Codex は agent-workspace の AGENTS.md のみ） | 人格・方針・覚えたことを自分で育てられない |
| セッション継続（resume） | `--no-session-persistence`、round ごとにプロセス起動 | 長い作業ができない。毎回コンテキストを作り直し、遅くて高い |
| MCP・Skills・Hooks | `--strict-mcp-config` で無効 | PETIT Tool を「JSONで返して Core が実行」という往復に置き換えている |
| 長い自律作業 | native Loop の 8 rounds / 12 calls で停止 | 「任せて放っておく」ができない |
| Coding Job | 専用cloneで list / read / write / 静的check のみ | テストが回せない。Push・PRもない |

つまり **「CLIに任せる」と言いながら、CLIを毎回呼び出す判断関数として使っている**。弱く感じるのは設計どおりの結果で、プロンプトやモデルの問題ではない。

安全側に倒したこと自体は正しかった（承認・冪等性・receipt を守るため）。ただし、守り方が「道具を全部取り上げる」になっている。これを「**居場所を与え、境界で守る**」に切り替えるのが本提案。

---

## 2. 再設計の考え方

### 2.1 PETIT Home：プティが「住む」ディレクトリ

CLIモードのPETITは、専用の作業ディレクトリ **PETIT Home** の中で常に動く。Home が PETIT の「体」になる。

```text
PETIT-Home/                 # 既定: ユーザーが選ぶ場所（例 ~/PETIT-Home）。Git管理する
  AGENTS.md                 # 人格と行動原則の正本（全Brain共通）
  CLAUDE.md                 # "@AGENTS.md" を読み込むだけ（Claude Code用の入口）
  SOUL.md                   # 口調・距離感・好み。ユーザーとプティが一緒に育てる
  USER.md                   # そそについて覚えておくこと（生活リズム、苦手、言い方の好み）
  memory/                   # プティ自身が書くノート（日誌・学び・決めたこと）
  skills/                   # 手順書（例: 朝のブリーフィング、週次ふりかえり、PR作成手順）
  inbox/  outbox/           # 受け取ったファイル / 渡すファイル（添付の受け渡し場所）
  scratch/                  # 自由に使える作業場（調査メモ、試作スクリプト）
  projects/ -> 登録repoへのリンクではなく「どのrepoを触ってよいか」の宣言ファイル
  .claude/settings.json     # 許可・拒否ルール、Hook（Coreへの報告・承認）、MCP（PETIT Tool）
```

- **人格は「システムプロンプトに埋め込む文字列」ではなく、Home 内のファイル**にする。CLI は自分で読み、必要なら（承認つきで）書き換えられる。
- DeepSeek / LM Studio（API Brain）も、同じ `AGENTS.md` + `SOUL.md` + `USER.md` を system prompt として読み込む。**入口やBrainが変わっても秘書はひとり**（Concept §3-4）を、ファイルの共有で守る。
- 現行の `backend/petit_prompt.py` の `CORE_SYSTEM_PROMPT` は、初回だけ `AGENTS.md` の雛形として書き出す。以後の正本は Home のファイル。
- 現行 `agent_workspace.py` の「変更されていたら停止」は、「変更は git の差分としてユーザーに見せる」に変える。
- **人格ファイル（`AGENTS.md` / `SOUL.md` / `USER.md`）の変更は差分承認（決定）**: プティは変更案を作業ブランチ（または `proposals/`）に書き、Core が差分を確認カードで見せ、本人が承認したときだけ反映する。却下した案も履歴に残す。`memory/` `skills/` `scratch/` は L0（確認なし）。
- 人格ファイルを直接書き換える操作は Hook で止め、上の提案の流れへ回す。

### 2.2 PETIT Tool は MCP で渡す

いまの「CLIがJSONでTool名を返す → Coreが実行 → 次のroundでまた起動」をやめ、**PETIT Core を MCP サーバー（stdio）として CLI に接続**する。

- CLI は 1 回のセッションの中で、タスク・予定・記憶・通知などの PETIT Tool を自分の判断で何度でも呼べる。
- Tool Registry・schema・risk・承認・receipt は今のまま Core 側にある。MCP は呼び出し口が変わるだけで、**承認の境界は動かない**。
- 確認が必要な書き込みは、MCP の結果として「承認待ち（approval_id）」を返し、CLI はそれをユーザーに伝えて待つ。承認後の実行は今と同じく Core が一度だけ消費する。
- Codex / Antigravity CLI も MCP に対応しているので、同じサーバーを共有できる（Codex の dynamic Tool bridge は段階的に置き換え）。

### 2.3 自由度は「信頼の段階」で決める

「Shell禁止」の一律ルールを、場所と操作ごとの段階に置き換える。

| 段階 | 範囲 | 例 | 確認 |
| --- | --- | --- | --- |
| **L0 自由** | PETIT Home の中 | メモを書く、skills を作る、scratch でスクリプトを試す、Web調査 | なし（git で全履歴を残す） |
| **L1 作業** | 登録した repo の **作業用 worktree / ブランチ** | コードを書く、テスト・lint・build を実行、ブランチへ commit | なし（開始時に Job として記録） |
| **L2 外に出る** | GitHub・外部サービス・送信 | push、PR 作成、Issue コメント、メール・Discord 送信、Notion 書き込み | **承認**（今の確認カード） |
| **L3 不可逆** | 本人の資産そのもの | main への直接 push、ファイル削除（Home・worktree 外）、課金、秘密値の読取 | **拒否**（ルールで常に止める） |

- 境界は CLI 自身の権限設定（Claude Code の `permissions.allow / deny`、Codex の sandbox 設定）と **Hook** で実装する。Hook（PreToolUse）が L2 の操作を検出したら Core に承認を問い合わせ、L3 は即拒否する。
- 秘密値は今と同じく子プロセスへ渡さない。GitHub への push などは Core 側の Tool（承認つき）経由にし、CLI に token を持たせない。
- この4段階は Concept §4 に反映済み（2026-11-08）。旧方針「CLIに任意のShellや無制限のファイル操作を直接は開放しない」を置き換えた。

### 2.4 セッションを持つ

- Core の Thread ごとに CLI セッション ID を保存し（既存 `provider_sessions` を流用）、次の Turn は `--resume` で続ける。round ごとのプロセス起動をやめる。
- 長い仕事（「WEVORA の続きを進めて」）は **Job** として切り出し、バックグラウンドで最後まで走らせる。進捗は Hook（PostToolUse / Stop）で Core に流し、Web・Desktop・Discord のどこからでも見られる。
- 8 rounds / 12 calls の上限は会話 Turn だけに残し、Job は「時間・費用・回数」の予算で止める。

---

## 3. 何を Core に残すか（変えないこと）

- Thread / Turn / 承認 / receipt / 記憶 / タスク・予定の**正本は Core（SQLite・Notion・Obsidian）**。Home の `memory/` はプティの作業ノートで、正本の代わりにはしない。
- 「完了したと言っただけでは完了にしない」（Concept §3-6）。Job の完了は、テスト結果・commit・PR の実在を Core が確かめてから表示する。
- CLI は公式バイナリ・本人ログインで動かす（Concept §4）。
- Brain の優先順位と Fallback は残す。ただし Home を使う「エージェントモード」に対応するのは CLI だけで、API Brain は今の native Loop のまま。

---

## 4. 段階導入

| 段 | 内容 | 完了条件 |
| --- | --- | --- |
| **H1 Home と人格の一元化** | Home を作り、`AGENTS.md` / `SOUL.md` / `USER.md` を全 Brain の人格の正本にする。Home を git 管理 | どの Brain・入口でも同じ人格ファイルから応答する。ファイル変更が差分で見える |
| **H2 PETIT MCP サーバー** | Tool Registry を MCP（stdio）で公開。risk・承認・receipt は既存のまま | Claude Code から MCP 経由で Read Tool と承認つき Write が動き、receipt が残る |
| **H3 Claude Code エージェントモード** | cwd=Home、組込みTool有効、権限ルール + Hook、`--resume` によるセッション継続 | Home 内で自由に作業し、L2 は承認、L3 は拒否されることをテストで確認 |
| **H4 Coding Job v2** | 登録 repo の git worktree で作業、テスト実行、ブランチ commit。push / PR は承認つき Core Tool | 実 repo で「Issue → ブランチ → テスト → PR（承認）」が通る |
| **H5 Codex / Antigravity CLI の追従** | 同じ Home・MCP・段階ルールを各 CLI の設定へ写す | 3 CLI で同じシナリオが通る。差分は文書に記録 |

最初に Claude Code で作る理由: 権限ルール・Hook・MCP・`--resume` がそろっていて、L0〜L3 の境界を最も素直に実装できるため。Concept の Executor 順位（Antigravity CLI 最優先）は会話 Brain の順位として残し、エージェントモードの対応順とは分けて扱う。

---

## 5. 決定事項と残りの問い

| 項目 | 状態 |
| --- | --- |
| 自由度の線引き L0〜L3 | **決定**（2026-11-08） |
| Concept §4 の書き換え | **決定・反映済み** |
| 人格ファイルの変更 | **決定**: 差分を見せて本人が承認 |
| Home の場所 | 未決定。提案: 既定は `~/PETIT-Home`（ユーザーが直接開ける場所）、設定で変更可。Obsidian Vault 内に置くかは H1 実装時に確認する |

## 6. 未確認

- 各 CLI の利用規約上、自作アプリから組込みTool有効で常駐させる使い方の扱い（Concept §10 と同じ論点）。
- Windows での Hook・MCP（stdio）の挙動。
- エージェントモードでの利用枠の消費量（現行の round ごと起動との比較）。
