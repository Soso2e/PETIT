# GitHub Project Evidence

PETIT reads GitHub as a source of verifiable engineering events. It does not treat a commit, pull-request merge, successful check, or deployment as proof that an entire project is complete.

## Setup

Configure a read-only-capable GitHub token in PETIT's environment:

```env
PETIT_GITHUB_TOKEN=
PETIT_GITHUB_API_URL=https://api.github.com
PETIT_GITHUB_API_VERSION=2022-11-28
PETIT_GITHUB_SYNC_TTL_SECONDS=300
PETIT_GITHUB_INITIAL_LOOKBACK_DAYS=30
PETIT_GITHUB_MAX_PAGES=3
PETIT_GITHUB_MAX_CHECK_COMMITS=50
PETIT_GITHUB_MAX_DEPLOYMENTS=20
```

The token is never written to SQLite, source-link metadata, project events, or error text. Use the smallest repository read permissions that still allow PETIT to read the required private repository metadata, contents/history, pull requests, checks, and deployments.

## Confirmation-first mapping

A repository is inspected by `owner/name` or a `github.com` URL. Inspection creates a `github_repository_candidates` row only. It does not create a trusted project relation.

After user approval, PETIT writes an active confirmed source link:

```text
provider = github
external_id = owner/name
```

Resume-time refresh reads only links that match the selected internal project and satisfy:

```text
status = active
confirmed_at IS NOT NULL
```

Unconfirmed candidates, removed links, and repositories linked to another internal project are not queried.

## Evidence model

PETIT preserves source meaning instead of collapsing GitHub activity into a single progress state.

| GitHub fact | PETIT evidence/event | What it proves |
|---|---|---|
| Commit on default branch | `commit` / `commit_pushed` | A specific code revision exists |
| Open PR | `pull_request` / `pull_request_opened` | A review/integration proposal exists |
| Merged PR | `pull_request` / `pull_request_merged` | The PR was integrated into its base branch |
| Successful check | `check_run` / `check_succeeded` | That named automated check succeeded for a SHA |
| Failed check | `check_run` / `check_failed` | That named automated check failed |
| Successful deployment status | `deployment` / `deployment_succeeded` | GitHub reports deployment success for an environment/ref |
| Failed deployment status | `deployment` / `deployment_failed` | GitHub reports deployment failure |

Important boundaries:

- Commit existence does not prove implementation completeness.
- Check success can support automated-test evidence, but does not prove real-browser or production verification.
- PR merge does not prove deployment.
- Deployment success does not prove that the user verified production behavior.
- GitHub events never overwrite `project_checkpoints` automatically.

## Incremental refresh

Each confirmed repository stores a `next_since` cursor. The first read is bounded by `PETIT_GITHUB_INITIAL_LOOKBACK_DAYS`; later reads use the saved cursor.

Checks are re-read for both newly seen commit SHAs and the current default-branch head, allowing an in-progress check to become final without requiring another commit. Recent deployments are bounded by `PETIT_GITHUB_MAX_DEPLOYMENTS`, and PETIT compares the latest deployment-status timestamp as well as the deployment timestamp.

## Failure behavior

- A failed refresh records source failure state under `github:repo:<owner/name>`.
- The last successful evidence cache and cursor remain available.
- Resume continues from PETIT checkpoints and saved events.
- The deterministic resume message discloses stale or failed GitHub refreshes.
- Errors redact the configured token.

## Conversation examples

```text
https://github.com/Soso2e/PETIT をプロジェクトに紐付けたい
GitHubリポジトリ候補を見せて
GitHub候補をPETITへ紐付けて
GitHubの進捗を同期して
```

Repository mapping and ignoring require the existing approval preview. Sync and inspection are read-only.

## Verification

```bash
python -m unittest \
  tests.test_github_evidence \
  tests.test_github_client_evidence \
  tests.test_github_evidence_routing \
  tests.test_project_source_refresh \
  tests.test_project_resume
python -m compileall backend tests
```
