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
| **L1 作業** | 登録した repo の **作業用 worktree / ブランチ**（PETIT Home の `worktrees/`） | コードを書く、テスト・lint・build を実行、ブランチへ commit、**自分の `petit/` ブランチへ push** | なし（実行記録は残す） |
| **L2 外に出る** | GitHub・外部サービス・送信 | PR 作成、Issue コメント、メール・Discord 送信、Notion 書き込み | **承認**（今の確認カード） |
| **L3 不可逆** | 本人の資産そのもの | main（既定ブランチ）への push、force push、他のブランチへの push、ファイル削除（Home・worktree 外）、課金、秘密値の読取 | **拒否**（ルールで常に止める） |

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
| **H1 Home と人格の一元化** | Home を作り、`AGENTS.md` / `SOUL.md` / `USER.md` を全 Brain の人格の正本にする。Home を git 管理 | どの Brain・入口でも同じ人格ファイルから応答する。ファイル変更が差分で見える  **実装済み（v0.46.0・#396）** |
| **H2 PETIT MCP サーバー** | Tool Registry を MCP（stdio）で公開。risk・承認・receipt は既存のまま | Claude Code から MCP 経由で Read Tool と承認つき Write が動き、receipt が残る **実装済み（v0.46.0・#398）。実 Turn への組込みは H3** |
| **H3 Claude Code エージェントモード** | cwd=Home、組込みTool有効、権限ルール + Hook、`--resume` によるセッション継続 | Home 内で自由に作業し、L2 は承認、L3 は拒否されることをテストで確認 **実装済み（v0.46.0・#400）。実 CLI で通し確認済み** |
| **H4 Coding Job v2** | 登録 repo の git worktree で作業、テスト実行、ブランチ commit。push / PR は承認つき Core Tool | 実 repo で「Issue → ブランチ → テスト → PR（承認）」が通る **実装済み（v0.46.0・#401）。実 CLI で通し確認済み（PR の実作成は未確認）** |
| **H5 Codex / Antigravity CLI の追従** | 同じ Home・MCP・段階ルールを各 CLI の設定へ写す | 3 CLI で同じシナリオが通る。差分は文書に記録 **実装済み（v0.47.0・#404）。実 Codex / agy は未確認** |

最初に Claude Code で作る理由: 権限ルール・Hook・MCP・`--resume` がそろっていて、L0〜L3 の境界を最も素直に実装できるため。Concept の Executor 順位（Antigravity CLI 最優先）は会話 Brain の順位として残し、エージェントモードの対応順とは分けて扱う。

---

## 4.1 H1 の実装（v0.46.0・#396）

- `backend/petit_home.py`: Home の場所は環境変数 `PETIT_HOME`、未設定なら `~/PETIT-Home`。足りないファイルだけ作り、既存は上書きしない。git があれば初期化して commit する。
- `petit_home.persona()`: `AGENTS.md` + `SOUL.md` + `USER.md` を連結（1ファイル 8,000 文字まで）。HTML コメントだけの空テンプレートは入れない。Home を読めないときは `petit_prompt.CORE_SYSTEM_PROMPT` に戻す。
- 使う場所: `brain._run`（native / Claude Code / Antigravity CLI の system）、`vision_reply`、Codex の agent-workspace `AGENTS.md`。
- Tool: `get_persona`（safe_read）、`update_persona_file`（confirm_write。変更後の全文を渡す）。確認カードには Tool Registry の `preview` で Core が計算した unified diff を出す（モデルが書いた差分は使わない）。承認後に一時ファイル経由で置換し、git commit する。
- agent-workspace: Core が生成した内容（ハッシュを `agent-workspace.generated` に記録）と旧形式の生成内容だけ再生成し、手編集は従来どおり停止する。
- 未実装: Home の場所を設定画面で変える UI、Desktop のプレビュー表示、CLI の組込みTool有効化（H3）。

## 4.2 H2 の実装（v0.46.0・#398）

- `backend/agent_bridge.py`: Core が Turn ごとに使い捨てのトークンを発行する（`issue(request_id)`、30分、メモリ上のみ・ハッシュで保持）。`POST /api/agent-bridge/tools/list` と `/tools/call` は Bearer トークン必須。
  - 公開 catalog は native Loop と同じ `brain.schemas()`。引数は同じ JSON Schema 検証。
  - `confirm_write` は実行せず `store.propose` で承認待ちを返す（確認カードには Core 計算の preview）。それ以外は `brain.execute` で実行し、書き込みは effect receipt を残す。
  - 実行中（queued / running）の Turn だけ、管理者の Turn だけ。1 Turn あたり 40 回まで。
- `backend/petit_mcp.py`（`python -m backend.petit_mcp`）: 依存なしの stdio JSON-RPC。`initialize` / `tools/list` / `tools/call` / `ping`。Tool の失敗は `isError` の結果として返す。
- Core 全体の管理者 cookie と同一 Origin のチェックは、Bearer で守る `/api/agent-bridge/` と `/api/channels/discord/` には適用しない（`setup_api.TOKEN_AUTH_PREFIXES`）。
- 確認済み: 実 Claude Code CLI（2.1.x）の `claude mcp list` で接続と Tool 一覧の取得（使い捨ての設定フォルダで実施）。
- 未実装: 実際の Turn で CLI を MCP つきで起動すること、MCP から出た承認の承認後の再開（どちらも H3）。

## 4.3 H3 の実装（v0.46.0・#400）

設定画面の Claude Code カードで「エージェントモードを使う」を ON にしたときだけ動く（既定 OFF。OFF なら従来の JSON 判断方式）。

- `backend/claude_agent.py`: 1 Turn につき公式 `claude` を1回起動する。
  - `-p --output-format json --restricted --strict-mcp-config --mcp-config <一時ファイル> --settings <一時ファイル> --permission-mode acceptEdits --tools Read,Write,Edit,Glob,Grep --allowedTools mcp__petit --disable-slash-commands --append-system-prompt <人格+規則>`、cwd = PETIT Home。
  - `--restricted` でユーザー・プロジェクトの設定を読まず、ファイル Tool を Home に閉じ込め、設定・git ファイルへの書き込みを拒否する。
  - MCP 設定（Turn 限定トークン入り）と settings は 0600 の一時ファイルで渡し、Turn 後にトークンを失効させる。API キーや PETIT の秘密値は子プロセスへ渡さない。
  - Thread ごとの CLI セッションを `provider_sessions`（`claude_agent`）に保存し、次の Turn は `--resume`。人格・モデル・Bash 可否・Hook 版が変わったら新しいセッション。
  - MCP から承認待ちが出たら Turn は `waiting_approval`。承認すると、同じセッションに承認結果を渡して `--resume` で続ける。
  - Turn の終わりに Home の変更を git commit（`PETIT: <request_id>`）。push はしない。
- `backend/agent_hooks.py`（PreToolUse Hook）: L0〜L3 の線。Home 外・`..`・`~`・秘密ファイル名・`.git`/`.claude` への書き込みは拒否。人格ファイルの直接編集は拒否して `update_persona_file` へ誘導。Bash では外部通信・公開・インストール（L2）、sudo・Home 外の削除など（L3）を拒否。WebFetch・WebSearch・サブエージェント・他の MCP も拒否。
- Bash: 「Bash も許可する」を ON にし、かつ Claude Code の OS サンドボックスが実際に使えるとき（Linux: `bwrap` と `socat`、macOS: `sandbox-exec`）だけ渡す。Windows では渡さない。
  - 実機で判明: 依存が無いと CLI は警告だけ出してサンドボックス無しで Bash を実行する。そのため Core 側で依存を確認して、無ければ Bash を渡さない（`bash_withheld` を記録）。
- 承認後の再開: Core は Turn が最初に止まったとき `input_json` を消すので、再開中の MCP は「承認済みの操作がある Turn」を管理者の Turn として扱う（承認は管理者か Discord の owner しかできない）。

実 CLI での通し確認（Linux 開発コンテナ・haiku・合成データ）:

| 確認 | 結果 |
| --- | --- |
| Home の `memory/` への書き込み（L0）と Turn 後の git commit | 確認済み |
| SOUL.md の直接 Edit を Hook が拒否し、エージェントが回避せず報告 | 確認済み（denials 1） |
| MCP 経由の PETIT Tool（get_current_time） | 確認済み |
| update_persona_file → 差分つき承認待ち → 承認 → 同じセッションで再開 → SOUL.md 反映・commit | 確認済み |
| Bash（サンドボックス内） | 未確認（コンテナにサンドボックス依存がないため Bash は渡していない） |
| Windows / macOS、本人アカウント | 未確認 |

## 4.4 H4 の実装（v0.46.0・#401）

- `backend/worktrees.py` と Tool（`backend/tools/worktrees.py`）:

  | Tool | 段階 | 中身 |
  | --- | --- | --- |
  | `open_worktree` | L1 | 登録 repo（設定の `coding_roots`）から、origin の既定ブランチを元に `Home/worktrees/<repo>-<id>` と `petit/<slug>-<id>` ブランチを作る。`git fetch` は試すだけ |
  | `list_worktrees` / `get_worktree_status` | 読取 | 開いている worktree、未 commit の変更・commit・差分の統計 |
  | `run_worktree_check` | L1 | テスト・ビルド・静的検査だけ（`python -m pytest`、`npm test` / `npm run <script>`、`npx eslint` など、`go test`、`cargo test`、`make` など）。シェルなし・PETIT の秘密値なし・600秒・出力の末尾 20,000 文字。何度でも実行し直せる |
  | `commit_worktree` | L1 | `git add -A` と commit（作者 PETIT） |
  | `push_worktree` | L1 | 作成時の `petit/` ブランチだけを `HEAD:refs/heads/<branch>` で push。commit を引数で指定し HEAD と一致したときだけ。既定ブランチ・main など・他のブランチ・force は不可 |
  | `create_worktree_pull_request` | L2（承認） | push 済みのときだけ、PC の `gh` ログインで PR を作る。確認カードには Core が計算した「ブランチ → 既定ブランチ・commit 一覧・差分の統計・本文」 |
  | `close_worktree` | L1 | worktree のフォルダを片付ける（ブランチは残す） |

- git は Core が実行し、repo の git hook は無効（`core.hooksPath=/dev/null`）。push と PR は PC の本人の git / gh の認証を使い、CLI には渡さない。
- `worktrees/` は Home の中にあるので、エージェントモードのファイル Tool でそのまま編集できる。Home の git 管理からは外す（`.gitignore`）。Hook は worktree 内の `.git` への書き込みと、Bash からの `git worktree` を拒否する。
- 注意: `run_worktree_check` は repo のテストコードを PC 上で実行する（OS サンドボックスなし・ネットワーク制限なし）。登録した自分の repo だけが対象。
- 実 CLI での確認（haiku・ローカルの合成 repo と bare origin）: 「登録 repo 確認 → worktree 作成 → 関数とテストを追加 → pytest 2 passed → commit → `petit/` へ push → PR は差分つきで承認待ち」が通り、origin の main は変わらないことを確認。GitHub への PR の実作成は未確認。

## 4.5 H5 の実装（v0.47.0・#404）

Codex と Antigravity CLI の組込みファイル Tool は、PETIT 側からフォルダ境界を保証できない（[antigravity-cli.md](antigravity-cli.md)）。そこで CLI ごとのサンドボックスや Hook に頼らず、**Home のファイル操作そのものを Core の Tool にした**。どの Brain から呼んでも同じ線になる。

| Tool | 段階 | 中身 |
| --- | --- | --- |
| `list_home_files` / `read_home_file` / `search_home_files` | 読取 | Home（と worktrees/）の一覧・行範囲の読取・文字列検索。秘密ファイル・`.git`・リンクは出さない |
| `write_home_file` / `edit_home_file` | L0 / L1（確認なし） | 新規・上書き・追記、1か所だけ一致する置換。Home の変更はその場で git commit（worktree は `commit_worktree` で） |

- 線は Claude Code の Hook と同じ `agent_hooks.path_decision`: Home の外・`..`・`~`・秘密ファイル名・`.git`（**読取も拒否**。`.git/config` にリモートの認証情報が入ることがあるため。Hook 側も同じに変更）・人格ファイルの変更（`update_persona_file` へ誘導）。
- **Codex エージェントモード**（設定の Codex カード、既定 OFF・管理者の Turn だけ）: 作業場所を PETIT Home にし、Home の `AGENTS.md`（人格）を Codex が直接読む。Core の規則（`brain.INSTRUCTIONS` と Home / worktree の使い方）は developerInstructions で渡す。Codex 自身の sandbox は read-only・shell なしのままで、ファイル操作と開発はすべて上の Tool と worktree Tool（`petit_read_tool` 経由）。
- **Antigravity CLI・DeepSeek・LM Studio**: 呼び出し方は変えない。公開 catalog に上の Tool が入り、system に Home の使い方を一文足した（`brain.HOME_HINT`）。`brain.INSTRUCTIONS` は旧形式の agent-workspace 判定に使うので変えていない。
- 未確認: 実 Codex / agy での動作（この開発環境に未導入）。Codex の `instructionSources` が Home の AGENTS.md を返すかは実機で確かめる必要がある（一致しないと Turn は失敗として止まる）。

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
