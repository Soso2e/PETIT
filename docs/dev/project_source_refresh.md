# Project Source Refresh

PETIT refreshes only explicitly confirmed external project sources when a user starts or resumes a registered project. Ordinary chat does not trigger a project-source refresh.

## Selection boundary

The target comes from the internal `projects.id` and only active, confirmed `project_source_links` belonging to that project are eligible. Unconfirmed, removed or other-project links are never sent to an adapter.

## Supported providers

- **Notion:** Once per resume turn, using existing project/task TTL-aware synchronization
- **GitHub:** Only the confirmed repository identities, with bounded read-only evidence refresh
- **BRAIN/Obsidian:** Only confirmed mapped notes through the existing read adapter

Providers without an adapter are reported as `skipped` and no endpoint or permission is inferred.

## Removed Linkraft integration (v0.34.3)

Linkraft's client, owner-project sync, Tool registrations, setup variables, and refresh branch are removed. Previously saved `project_source_links` with `provider='linkraft'` are **preserved** as unsupported/skipped. Historical `tasks_cache`, `project_events`, synchronization state, and dedicated `linkraft_*` tables are **not** deleted or migrated. No startup schema changes or implicit cleanup is performed. Before any future data cleanup, separately inventory and back up the user's actual SQLite database.

## Failure and observability

A failed supported source never blocks saved checkpoints, project events, or resume context. Other providers continue. The existing `ProjectResumeContext.reference_counts()` retains `source_refresh_attempted`, `source_refresh_failed`, and `source_refresh_skipped`; stale caches are distinguished from successful refresh.

## Verification

```bash
python -m unittest tests.test_project_source_refresh tests.test_project_resume tests.test_removed_integrations tests.test_notion_adapter_v2
python -m compileall backend tests
```
