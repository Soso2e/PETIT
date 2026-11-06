# GitHub Daily Review

PETITがアクセス可能なGitHubリポジトリを横断し、前回確認以降の開発差分を朝ブリーフィングと会話から確認する読み取り専用機能です。

Project Continuity向けの`GitHub evidence`とは役割を分けます。

- GitHub evidence: 確認済みの1プロジェクトとrepositoryを紐付け、commit・PR・check・deploymentを進捗証拠として保存する
- GitHub Daily Review: 個人がアクセスできる全repositoryを横断し、前回以降に何が変わったかを日次で把握する

## セットアップ

private repositoryを含める場合は、最小権限のread tokenを設定します。

```env
PETIT_GITHUB_TOKEN=
PETIT_GITHUB_DAILY_REVIEW_ENABLED=1
PETIT_GITHUB_DAILY_REVIEW_HOUR=8
PETIT_GITHUB_DAILY_REVIEW_TIMEZONE=Asia/Tokyo
```

推奨権限は、対象repositoryのmetadata、contents、commits、pull requests、checksを読み取れる範囲だけです。tokenはSQLite、結果JSON、エラー、ログへ保存しません。

## 動作

PETIT起動中は、指定timezoneの指定時刻以降に1日1回レビューします。既定では15分ごとに実行要否だけ確認します。

初回は過去24時間、以降は最後に安全に進められたglobal cursor以降を対象にします。

```text
repository一覧
↓
archived・disabled・空repositoryを除外
↓
commit・更新PR・checkを取得
↓
変更repositoryのPROGRESS.mdを取得
↓
LM Studio Agentで短くレビュー
↓
失敗時はPython定型文へフォールバック
↓
SQLiteへ結果とcursorを保存
```

一部repositoryの取得に失敗した場合、取得できた内容は表示しますがglobal cursorは進めません。これにより、失敗したrepositoryの差分を次回取りこぼしません。

同じ日の朝ブリーフィングでは保存済みレビューを再利用します。「最新に更新して」など明示した場合だけ、前回cursor以降を再取得します。

## 会話例

```text
GitHub全体で前回から何が変わった？
全リポジトリの開発差分をレビューして
GitHubの新コミットを確認して
GitHubレビューを最新に更新して
```

会話では`review_github_activity`を決定論的に実行します。GitHubへの書き込み、Issue作成、merge、修正は行いません。

## 朝ブリーフィング

朝の`/api/proactive`と`/api/briefing`は、GitHubレビューの要点を予定・タスク・最近の流れと一緒に扱います。

- 失敗CIがある場合は次の一手として優先する
- 通常の更新は、期限付きタスクや直近予定の後に扱う
- commitやPRだけでプロジェクト全体の完了を断定しない

PETITを閉じている間は実行できません。アプリを閉じていても届くOS通知は別機能です。

## 設定

| 変数 | 既定値 | 説明 |
|---|---:|---|
| `PETIT_GITHUB_DAILY_REVIEW_ENABLED` | `1` | 朝レビューを有効化 |
| `PETIT_GITHUB_DAILY_REVIEW_HOUR` | `8` | local hour |
| `PETIT_GITHUB_DAILY_REVIEW_TIMEZONE` | `Asia/Tokyo` | IANA timezone |
| `PETIT_GITHUB_DAILY_REVIEW_POLL_MINUTES` | `15` | 実行要否の確認間隔 |
| `PETIT_GITHUB_DAILY_REVIEW_LOOKBACK_HOURS` | `24` | 初回の遡り時間 |
| `PETIT_GITHUB_DAILY_REVIEW_MAX_REPOSITORIES` | `50` | 1回のrepository上限 |
| `PETIT_GITHUB_DAILY_REVIEW_MAX_COMMITS_PER_REPO` | `10` | LLMへ渡すcommit上限 |
| `PETIT_GITHUB_DAILY_REVIEW_PROGRESS_MAX_CHARS` | `1800` | repositoryごとのPROGRESS抜粋上限 |
| `PETIT_GITHUB_DAILY_REVIEW_INCLUDE_FORKS` | `0` | forkを対象に含める |

## 境界

- commitは実装全体の完了を証明しない
- check成功は実画面・本番動作を証明しない
- PR mergeはdeploymentを証明しない
- `PROGRESS.md`は自己申告なので、GitHub上の事実と分けて扱う
- line-by-lineのコードレビューではなく、日次の開発catch-upを目的とする
