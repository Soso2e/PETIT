# Project Source Refresh

PETIT updates external project state only when the user explicitly starts or resumes a registered project. Ordinary chat, greetings, and unrelated tool turns do not run this flow.

## Selection boundary

The refresh target is derived from PETIT's internal `projects.id`. PETIT reads only `project_source_links` rows that satisfy all of the following:

- `project_id` is the selected project
- `status = active`
- `confirmed_at IS NOT NULL`

Unconfirmed candidates, removed links, and links belonging to another internal project are not sent to an adapter.

## Provider behavior

### Notion

Notion is called at most once during a resume turn, even if the internal project has multiple confirmed Notion identities. The existing project/task Relation adapter performs its normal TTL-aware read sync. Notion remains the canonical editable source; PETIT stores mappings and caches.

### Linkraft

Linkraft is refreshed per confirmed external project ID for the selected internal project. PETIT does not call the broad all-linked-project sync during resume. Each project keeps its own delta cursor and freshness state under:

```text
linkraft:project:<external project id>
```

The Linkraft API independently enforces the configured owner identity, so PETIT cannot broaden access by changing a local query.

### Unsupported providers

Confirmed providers without a registered refresh adapter are reported as `skipped`. PETIT does not guess an endpoint or treat the provider name as executable code.

## Failure behavior

Source refresh is best effort and never replaces the saved checkpoint path.

- A source failure records `last_failure_at` and the sanitized error.
- A previous successful cache remains available and is marked stale.
- Other confirmed providers continue refreshing.
- PETIT still builds `ProjectResumeContext` from checkpoints, events, episodes, and handoff notes.
- The deterministic renderer discloses failed or stale providers.
- LM Studio is not required.

## Observability

`ProjectResumeContext.reference_counts()` includes:

- `source_refresh_attempted`
- `source_refresh_failed`
- `source_refresh_skipped`
- existing source and stale-source counts

These fields appear under the existing project-continuity `model_route.resume_references` payload.

## Verification

Run:

```bash
python -m unittest \
  tests.test_project_source_refresh \
  tests.test_project_resume \
  tests.test_linkraft_owner_sync \
  tests.test_notion_adapter_v2
python -m compileall backend tests
```
